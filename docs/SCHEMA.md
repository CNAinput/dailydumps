# Esquema dos dados

Este documento descreve cada ficheiro do arquivo, os formatos e as regras com que são gerados. Os nomes de campos, colunas, chaves JSON e ficheiros estão em inglês técnico, em snake_case.

## Convenções gerais

- **Dia** é o dia civil de Lisboa (`Europe/Lisbon`). A janela de um dia é `[00:00, 24:00)` hora de Lisboa, convertida para UTC. Há por isso dias de 23 horas (último domingo de março) e de 25 horas (último domingo de outubro). Um dia só é arquivado depois das 23:00 de Lisboa desse dia, o fecho do mercado.
- **Mercado**: aberto todos os dias das 11:00 às 23:00 de Lisboa. Fechado, os preços ficam congelados. Podem aparecer ticks alguns segundos depois das 23:00, e entram no dia a que pertencem.
- **Instante** (`ts_utc`, `snapshot_at`, `generated_at`): UTC, sempre com o sufixo `Z`. Os ticks têm sempre 6 dígitos de fração (`2026-10-26T11:00:07.170863Z`) e os instantes de execução têm segundos (`2026-10-27T23:17:00Z`). O texto ordena como o tempo.
- **Números**: os preços são lidos como decimais exatos e escritos tal como estão na base de dados (`64.4`, não `64.40`). No JSON são números e nunca texto.
- **Tipo de instrumento** (`asset_type`): `company` (empresa) ou `asset` (ativo). Um ativo pertence a uma empresa (`owner_company_code`). Os índices são ativos com `is_index` verdadeiro. O par `(code, asset_type)` identifica um instrumento, porque os códigos de uma empresa e de um ativo podem coincidir. Os códigos podem ter caracteres como `&` (por exemplo `P&P10`).
- **Ficheiros**: UTF-8 sem BOM, fim de linha LF, CSV separado por vírgulas com aspas só quando necessário, JSON com indentação de 2 espaços. O `.gitattributes` impede que o Git converta os fins de linha, o que alteraria os `sha256`.
- **Privacidade**: nunca se exportam identificadores de contas nem de utilizadores. O comando `verify` rejeita chaves cujo nome sugira contas, utilizadores ou Discord.
- **Moeda**: coins (¢), da economia virtual da CNA.

## prices/AAAA/AAAA-MM-DD.csv

Todos os ticks do dia, uma linha por tick, tal como na base de dados (`price_history`).

| Coluna | Significado |
|-|-|
| `ts_utc` | instante do tick, em UTC |
| `code` | código do instrumento |
| `asset_type` | `company` ou `asset` |
| `price` | preço do instrumento nesse instante |

Ordenado por `ts_utc`, `code` e `asset_type`. Os índices `P&P10` e `PPA10` gravam um ponto por minuto com o mercado aberto. As empresas e os ativos gravam um ponto a cada 30 minutos, mais um por cada operação que mova o preço.

Os preços são os da base de dados no momento em que o ficheiro foi gerado. Quando o bot faz um split, reescreve todo o histórico da base de dados, e por isso os ficheiros gerados depois do split já estão nas unidades novas e os gerados antes ficam nas unidades antigas. Ver [Ajuste por eventos](#ajuste-por-eventos).

## daily/ohlc.csv

Uma linha por instrumento e dia, acrescentada dia a dia.

| Coluna | Significado |
|-|-|
| `date` | dia civil de Lisboa |
| `code`, `asset_type` | instrumento |
| `open` | preço do primeiro tick do dia |
| `high`, `low` | maior e menor preço do dia |
| `close` | preço do último tick do dia |
| `ticks` | número de ticks do instrumento nesse dia |

Ordenado por `date`, `code` e `asset_type`. O `ohlc.csv` é sempre recalculável a partir dos ficheiros `prices/`, e o comando `verify` confere-o.

## daily/ohlc_adjusted.csv

Mesmas colunas do `ohlc.csv`, com `open`, `high`, `low` e `close` ajustados aos splits de `events.csv`. É derivado e regenerável: nunca se edita à mão e é reescrito pelo workflow (`python -m cnadump adjust`). Quando não há splits que se apliquem a uma linha, a linha é igual à do `ohlc.csv`. Os valores ajustados têm no máximo 4 casas decimais e, se terminarem em zeros, ficam pelo menos com 2 (`20.00`, `19.9725`).

### Ajuste por eventos

Para um split de factor `N` (as shares ficam multiplicadas por `N` e o preço dividido por `N`), as linhas ajustadas ficam divididas por `N`. A questão é saber **a que dias** se aplica.

> Um evento só ajusta os dias cujo `generated_at` seja anterior ao início da data do evento (00:00 de Lisboa).

O `generated_at` de cada dia está no `manifest.json`. A razão: os ticks vêm da base de dados, que já reflete os splits anteriores ao momento em que o ficheiro foi gerado. Um dia gerado antes do split está nas unidades antigas e tem de ser dividido. Um dia gerado depois do split (ou regenerado depois dele) já está nas unidades novas e não pode ser dividido outra vez, porque seria ajustado duas vezes. Vários splits do mesmo instrumento multiplicam os factores. As emissões, os IPO e as retiradas de cotação não alteram preços e não ajustam nada.

Consequência para quem regista eventos (ver `docs/OPERATIONS.md`): a data a registar é o dia civil de Lisboa do **primeiro ficheiro diário gerado depois da alteração**. Normalmente é o dia em que a alteração foi aplicada. Se foi aplicada entre as cerca de 23:17, quando o ficheiro desse dia já foi gerado, e a meia-noite, regista-se o dia seguinte. As issues abertas automaticamente sugerem a data certa, porque usam o dia do primeiro instantâneo que já reflete a alteração.

## snapshots/AAAA-MM-DD.json

Estado do mercado no fecho. Só existe em execuções diárias reais feitas com a base de dados ainda no estado do fecho (entre as 23:00 do dia e as 11:00 do dia seguinte), nunca em backfill: a história das shares detidas não é reconstituível.

| Campo | Significado |
|-|-|
| `schema_version`, `date`, `snapshot_at` | versão do esquema, dia e instante do instantâneo |
| `instruments[]` | um objeto por instrumento, ordenado por `code` e `asset_type` |

Cada instrumento tem `code`, `name`, `asset_type`, `is_index`, `owner_company_code` (`null` nas empresas), `price` (o preço atual no fecho), `shares_total` (shares autorizadas), `shares_in_circulation` (shares detidas, a soma das posições de todas as contas) e `market_cap`.

A **capitalização** é `price` vezes `shares_in_circulation`, arredondada a 2 casas, e nunca `price` vezes `shares_total`. As shares autorizadas e ainda não detidas não valem nada no mercado. Para os índices, `market_cap` é o valor das unidades do índice detidas por investidores e não entra em nenhum total de mercado.

## instruments.json

Cópia do último instantâneo, com mais o campo `slug` em cada instrumento, e os campos `snapshot_date` e `snapshot_at`. Só é criado e atualizado em execuções que tiram instantâneo.

O **slug** é seguro para nomes de ficheiro e URL (`^[a-z0-9]+(-[a-z0-9]+)*$`): minúsculas, sem acentos, com `&` escrito `and` (`P&P10` dá `p-and-p10`). Os slugs são estáveis: um slug já atribuído nunca muda quando aparece outro instrumento com um nome parecido. Se dois instrumentos derem o mesmo slug, o segundo recebe o tipo como sufixo (`newte-company`) e depois um número. Os nomes de dispositivo do Windows (`con`, `nul`, `com1` e semelhantes) não são usados.

## summary/AAAA-MM-DD.json

Resumo do fecho do dia, com as mesmas regras do resumo "Fecho do Mercado" que o bot publica no Discord.

| Campo | Significado |
|-|-|
| `schema_version`, `date` | versão do esquema e dia |
| `market_cap_available` | `true` se existe snapshot desse dia |
| `indices[]` | para cada índice com ticks nesse dia: `code`, `name`, `open`, `close`, `change_pct` |
| `biggest_riser` | maior subida do dia, ou `null` |
| `biggest_faller` | maior descida do dia, ou `null` |
| `calm_day` | `true` se não houve nem subida nem descida relevante |
| `top_market_cap` | as 3 maiores empresas por capitalização, ou `null` |
| `total_market_cap` | capitalização total das empresas, ou `null` |
| `companies_count` | número de empresas no instantâneo, ou `null` |

Regras escolhidas:

- `open` é o primeiro tick do dia e `close` o último. O bot usa o preço atual como fecho, que é igual ao último tick enquanto o mercado está fechado, e o arquivo confere essa igualdade antes de arquivar.
- `change_pct` é `(close - open) / open * 100`, arredondado a 2 casas (metade para cima), face ao **primeiro tick do dia**.
- A maior subida e a maior descida consideram empresas e ativos que não são índices e que têm ticks nesse dia. Cada uma traz `code`, `asset_type`, `name`, `open`, `close` e `change_pct`.
- Só há `biggest_riser` se a melhor variação for superior a +0,05 % e só há `biggest_faller` se a pior for inferior a -0,05 %. A descida nunca repete o instrumento da subida. Em caso de empate ganha o menor `code` (e depois o menor `asset_type`).
- `top_market_cap` lista (`rank`, `code`, `name`, `market_cap`) as 3 empresas (`company`) com maior capitalização positiva, com desempate pelo `code`. `total_market_cap` é a soma das capitalizações de todas as empresas (as de capitalização zero incluídas) e `companies_count` o seu número. Ativos e índices não entram.
- Os campos de capitalização só existem quando há snapshot desse dia. Em backfill ficam `null` e `market_cap_available` é `false`.
- Um instrumento sem metadados atuais (por exemplo retirado de cotação) é tratado como instrumento normal e o seu `name` é `null`.

## dividends.json

Política de dividendos em vigor, sem identificadores de contas.

| Campo | Significado |
|-|-|
| `policies[].code`, `asset_type` | instrumento |
| `percentage` | percentagem do saldo da tesouraria a distribuir em cada pagamento |
| `distribution_days` | dias entre pagamentos |
| `next_distribution`, `last_distribution` | instantes do próximo e do último pagamento |

## taxes.json

Impostos em vigor, em percentagem.

| Campo | Coluna de origem | Significado |
|-|-|-|
| `loan_interest_pct` | `juros` | juro por dia dos empréstimos novos |
| `income_tax_pct` | `income` | imposto sobre os salários |
| `vat_pct` | `iva` | IVA incluído no preço das compras na loja |
| `last_changed` | `last_changed` | instante da última alteração |

## events.csv

Eventos estruturais, registados à mão por pull request. O workflow nunca escreve neste ficheiro.

| Coluna | Significado |
|-|-|
| `date` | dia civil de Lisboa (ver [Ajuste por eventos](#ajuste-por-eventos)) |
| `code`, `asset_type` | instrumento |
| `event` | `ipo`, `split`, `issuance` ou `delisting` |
| `factor` | só nos splits: as shares ficam multiplicadas por este número e o preço dividido por ele |
| `shares_before`, `shares_after` | `shares_total` antes e depois, se conhecidos |
| `document_id` | identificador do despacho no portal, se existir |
| `notes` | texto livre |

Regras validadas: cabeçalho exato; `event` e `asset_type` válidos; `factor` positivo e diferente de 1, obrigatório nos splits e proibido nos outros eventos; num split, `shares_after` é `shares_before` vezes o `factor`; numa emissão, `shares_after` é maior que `shares_before`; datas por ordem cronológica (vários eventos do mesmo dia mantêm a ordem do ficheiro); sem linhas repetidas.

## manifest.json

```json
{
  "schema_version": 1,
  "days": {
    "2026-10-26": {
      "generated_at": "2026-10-27T23:17:00Z",
      "rows": 1762,
      "sha256": "...",
      "source": "backfill",
      "partial": false
    }
  }
}
```

| Campo | Significado |
|-|-|
| `generated_at` | instante em que o ficheiro do dia foi gerado |
| `rows` | número de ticks do dia |
| `sha256` | soma de controlo do ficheiro `prices/` do dia |
| `source` | `daily` se o dia tem snapshot, `backfill` se foi arquivado depois do fecho sem snapshot |
| `partial` | `true` se a retenção do bot pode ter apagado os primeiros ticks do dia |
| `regenerations[]` | só nos dias regenerados: `at`, `previous_generated_at`, `previous_sha256`, `previous_rows` |

O `partial` é verdadeiro quando a abertura do mercado desse dia (11:00 de Lisboa) é anterior a `generated_at` menos 40 dias, a retenção do bot. Na prática só o primeiro dia disponível pode ser parcial.

## SHA256SUMS

Somas SHA-256 no formato do `sha256sum`, de todos os ficheiros gerados: `prices/`, `snapshots/`, `summary/`, `daily/`, `manifest.json`, `instruments.json`, `dividends.json`, `taxes.json` e `status.json`. O `events.csv` não entra, porque é mantido à mão. Verifica-se com `sha256sum -c SHA256SUMS`.

## status.json

| Campo | Significado |
|-|-|
| `last_date` | último dia arquivado |
| `generated_at` | instante da última execução que escreveu dados |
| `ticks` | ticks desse dia |
| `instruments` | instrumentos com ticks nesse dia |
| `ok` | `true` se o último dia arquivado é o último dia fechado |

## Imutabilidade

O ficheiro de um dia nunca é sobrescrito. Se um recálculo diferir do ficheiro arquivado, a execução falha e não escreve nada. Isto acontece de forma natural depois de um split, porque a base de dados passou a ter os preços do dia nas unidades novas. A única forma de substituir um dia é pedi-lo explicitamente (`python -m cnadump regenerate AAAA-MM-DD`, ou a entrada `force_date` do workflow). A substituição fica registada no `manifest.json` com o `sha256` anterior. Os pull requests não podem alterar estes ficheiros: o workflow `verify-pr` falha se tocarem em `prices/`, `summary/`, `snapshots/`, `daily/` ou nos ficheiros gerados da raiz.

## Validação antes de escrever

São erros duros, que não escrevem nada e terminam com código de saída 2: contagem de linhas diferente da anunciada pelo servidor, timestamps fora da janela do dia, preços não finitos ou não positivos, ticks duplicados `(ts, code, asset_type)`, tipos de ativo desconhecidos, mais de um servidor (`guild_id`) nos dados, dia sem nenhum tick, e, quando o último dia fechado é gerado antes das 11:00 do dia seguinte (a base de dados ainda está no estado do fecho), um último tick que não iguala o `current_price` atual de algum instrumento. São avisos, que não bloqueiam: instrumento sem ticks num dia em que já existia, e lacunas de mais de 2 horas entre as 11:00 e as 23:00.

## Site e API estática (GitHub Pages)

Gerados pelo workflow a partir dos ficheiros já guardados (`python -m cnadump build-pages`). O site é o conteúdo da pasta `web/`, e a API e os ficheiros de dados juntam-se-lhe na mesma raiz.

### API

Os endereços da API não dependem do site: `build-pages` nunca deixa o `web/` ocupá-los.

| Endereço | Conteúdo |
|-|-|
| `latest.json` | último dia arquivado, ficheiros do dia e resumo do fecho |
| `dates.json` | todos os dias arquivados, com `source`, `partial` e `rows` |
| `instruments.json` | instrumentos com `code`, `asset_type`, `name` e `slug` |
| `instruments/{slug}.json` | metadados, série diária (`daily` e `daily_adjusted`) e `events` de um instrumento |
| `badge.json` | estado no formato endpoint do shields.io (`schemaVersion`, `label`, `message`, `color`) |
| `api.html` | página que descreve a API e liga ao site |

### Ficheiros do arquivo servidos pelo site

O site lê estes ficheiros do seu próprio domínio. Têm o mesmo caminho e o mesmo conteúdo, byte a byte, que no repositório.

| Caminho | Nota |
|-|-|
| `daily/ohlc.csv`, `daily/ohlc_adjusted.csv` | todos os instrumentos e dias |
| `events.csv` | só se existir |
| `manifest.json`, `status.json`, `SHA256SUMS` | integridade e estado |
| `dividends.json`, `taxes.json` | política em vigor |
| `summary/AAAA-MM-DD.json` | um por dia arquivado |
| `snapshots/AAAA-MM-DD.json` | só os dias com snapshot |

Ficam de fora os ticks (`prices/`), que o site lê de `https://raw.githubusercontent.com/CNAinput/dailydumps/main/prices/` só quando alguém os pede (a origem está em `TICKS_BASE`, no `web/js/config.js`). Fica de fora também o `instruments.json` do repositório, porque o `instruments.json` da API tem o mesmo nome; o seu conteúdo está nos snapshots.

### Regras do `build-pages`

- O `web/index.html` tem de existir, senão o comando falha (código de saída 2) e não escreve nada.
- Os ficheiros de `web/` são copiados para a raiz do site, exceto os ocultos (nomes que começam por ponto) e `__pycache__`.
- O `web/` não pode ter ficheiros com os endereços da API, com os ficheiros da lista acima, nem dentro das pastas `instruments/`, `daily/`, `summary/`, `snapshots/` e `prices/`. Se tiver, o comando falha e lista os caminhos em conflito.
- A página inicial do site é o `index.html` do `web/`. A API é descrita em `api.html`.
