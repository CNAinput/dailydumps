# Esquema dos dados

Este documento descreve cada ficheiro do arquivo, os formatos e as regras com que são gerados. Os nomes de campos, colunas, chaves JSON e ficheiros estão em inglês técnico, em snake_case.

## Convenções gerais

- **Dia** é o dia civil de Lisboa (`Europe/Lisbon`). A janela de um dia é `[00:00, 24:00)` hora de Lisboa, convertida para UTC. Há por isso dias de 23 horas (último domingo de março) e de 25 horas (último domingo de outubro). Um dia só é arquivado depois das 23:00 de Lisboa desse dia, o fecho do mercado.
- **Mercado**: aberto todos os dias das 11:00 às 23:00 de Lisboa. Fechado, os preços ficam congelados. Podem aparecer ticks alguns segundos depois das 23:00, e entram no dia a que pertencem.
- **Instante** (`ts_utc`, `snapshot_at`, `generated_at`): UTC, sempre com o sufixo `Z`. Os ticks têm sempre 6 dígitos de fração (`2026-10-26T11:00:07.170863Z`) e os instantes de execução têm segundos (`2026-10-27T23:17:00Z`). O texto ordena como o tempo.
- **Números**: os preços são lidos como decimais exatos e escritos tal como estão na base de dados (`64.4`, não `64.40`). No JSON são números e nunca texto.
- **Tipo de instrumento** (`asset_type`): `company` (empresa) ou `asset` (ativo). Um ativo pertence a uma empresa (`owner_company_code`). Os índices são ativos com `is_index` verdadeiro. O par `(code, asset_type)` identifica um instrumento, porque os códigos de uma empresa e de um ativo podem coincidir. Os códigos podem ter caracteres como `&` (por exemplo `P&P10`).
- **Ficheiros**: UTF-8 sem BOM, fim de linha LF, CSV separado por vírgulas com aspas só quando necessário, JSON com indentação de 2 espaços. O `.gitattributes` impede que o Git converta os fins de linha, o que alteraria os `sha256`.
- **Privacidade**: nunca se exportam identificadores de contas nem de utilizadores. O comando `verify` rejeita chaves cujo nome sugira contas, utilizadores ou Discord. A única exceção são os nomes públicos dos beneficiários de dividendos (ver [dividend_payouts](#dividend_payoutsaaaa-mm-ddjson)), que nunca são identificadores.
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

## dividend_payouts/AAAA-MM-DD.json

Pagamentos de dividendos feitos nesse dia civil de Lisboa: quanto a tesouraria pôs, a média e quanto recebeu cada beneficiário. Só existe nos dias em que houve pelo menos um pagamento, e só a partir de **2026-10-30**, o primeiro dia em que o bot passou a registá-los. Os pagamentos anteriores não ficaram guardados em lado nenhum e não se reconstituem. O manifesto diz, em cada dia coberto, quantos pagamentos tem (campo `dividend_payouts`, com 0 nos dias sem ficheiro).

| Campo | Significado |
|-|-|
| `schema_version`, `date` | versão do esquema e dia |
| `payouts[]` | um objeto por política paga, ordenado por `paid_at`, `code` e `asset_type` |

Cada elemento de `payouts[]`:

| Campo | Significado |
|-|-|
| `code`, `asset_type` | instrumento que pagou |
| `paid_at` | instante do pagamento, em UTC |
| `percentage` | percentagem do saldo da tesouraria que a política distribui |
| `pool` | valor a distribuir: essa percentagem aplicada ao saldo da tesouraria antes do pagamento (o que a tesouraria contribui) |
| `total_paid` | soma do que foi pago. Pode ficar alguns cêntimos abaixo de `pool` por causa dos arredondamentos de cada parcela |
| `beneficiaries` | número de beneficiários pagos |
| `average` | `total_paid` a dividir por `beneficiaries`, arredondado a 2 casas (metade para cima) |
| `total_shares` | total das shares detidas que entraram na divisão |
| `origin` | `bot` se o bot o registou no momento do pagamento, `reconstruction` se foi reconstituído depois |
| `payments[]` | um objeto por beneficiário, do maior valor para o menor, com desempate pelo `beneficiary` |

Cada elemento de `payments[]`:

| Campo | Significado |
|-|-|
| `beneficiary` | nome público do beneficiário (ver abaixo) |
| `kind` | `pessoal`, `empresa` ou `estado` |
| `shares` | shares que o beneficiário detinha no pagamento |
| `amount` | quanto recebeu: `pool` vezes `shares` a dividir por `total_shares`, arredondado a 2 casas |

Regras escolhidas:

- **Cada beneficiário é uma conta.** Uma pessoa que detenha shares na conta pessoal e numa empresa aparece em duas linhas, porque os rótulos são diferentes. Uma conta cujo valor arredondado seria 0 não é paga e não aparece, mas as suas shares contam em `total_shares`.
- **O nome público nunca é um identificador.** Nas contas pessoais é o nome global do perfil de Discord (o nome de utilizador, se o perfil não tiver nome global), e não o nome que a pessoa usa no servidor. Nas contas de empresa é o código de mercado da empresa (ou o nome da conta, se não tiver código) e no Banco Público é `Estado`. Se o bot não consegue resolver o nome (por exemplo, a pessoa já não está no servidor) o rótulo é `Desconhecido`. O arquivo faz o mesmo a qualquer rótulo vazio ou que contenha 15 ou mais dígitos seguidos (o aspeto de um identificador do Discord) e emite um aviso. Dois beneficiários podem ter o mesmo rótulo.
- **O dia de um pagamento** é o dia civil de Lisboa do instante em que foi pago (`paid_at`), e não o dia para que estava agendado. Um pagamento que o bot só faça depois da meia-noite (por exemplo, depois de uma paragem) pertence por isso ao dia seguinte, e nunca ao ficheiro de um dia que já foi arquivado.
- **Retenção.** O bot só guarda os pagamentos 14 dias na base de dados e apaga-os depois: o arquivo copia-os no próprio dia e é ele que os mantém. Um dia gerado quando já passaram 14 dias (por exemplo, depois de uma paragem longa do workflow, ou num `backfill`) já não consegue lê-los. Esse dia fica sem ficheiro **e sem o campo `dividend_payouts` no manifesto**, para nunca afirmar que não houve pagamentos, e a execução emite um aviso. Regenerar um dia assim não apaga nem altera o ficheiro e o campo que ele já tinha.
- **Validação.** A soma dos `amount` tem de ser igual a `total_paid`, a soma das `shares` não pode exceder `total_shares`, os valores têm no máximo 2 casas, `kind`, `origin` e `asset_type` têm de ser dos valores acima e `paid_at` tem de estar dentro do dia. O `verify` volta a gerar o ficheiro a partir dos próprios pagamentos e exige que fique byte a byte igual, o que também confere a média, a contagem e a ordem.
- **Reconstrução de 2026-10-30.** Os pagamentos da P&PNV (09:57) e da ACHIP (14:10) desse dia foram feitos antes de o bot os registar, e têm `origin` igual a `reconstruction`. Os valores de cada conta vêm do registo de auditoria do bot (`balance_changed`), e as shares foram deduzidas e conferidas: para todos os 16 beneficiários, `pool` vezes `shares` a dividir por `total_shares`, arredondado a 2 casas, dá exatamente o valor pago. Não há outras reconstruções.

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
| `dividend_payouts` | só nos dias a partir de 2026-10-30: número de pagamentos de dividendos do dia, que estão em `dividend_payouts/`. É 0 nos dias sem pagamentos, que não têm ficheiro. Falta nos dias anteriores e nos dias gerados depois de o bot já ter apagado os pagamentos (14 dias) |
| `regenerations[]` | só nos dias regenerados: `at`, `previous_generated_at`, `previous_sha256`, `previous_rows` |

O `partial` é verdadeiro quando a abertura do mercado desse dia (11:00 de Lisboa) é anterior a `generated_at` menos 40 dias, a retenção do bot. Na prática só o primeiro dia disponível pode ser parcial.

## SHA256SUMS

Somas SHA-256 no formato do `sha256sum`, de todos os ficheiros gerados: `prices/`, `snapshots/`, `summary/`, `dividend_payouts/`, `daily/`, `manifest.json`, `instruments.json`, `dividends.json`, `taxes.json` e `status.json`. O `events.csv` não entra, porque é mantido à mão. Verifica-se com `sha256sum -c SHA256SUMS`.

## status.json

| Campo | Significado |
|-|-|
| `last_date` | último dia arquivado |
| `generated_at` | instante da última execução que escreveu dados |
| `ticks` | ticks desse dia |
| `instruments` | instrumentos com ticks nesse dia |
| `ok` | `true` se o último dia arquivado é o último dia fechado |

## Imutabilidade

O ficheiro de um dia nunca é sobrescrito. Se um recálculo diferir do ficheiro arquivado, a execução falha e não escreve nada. Isto acontece de forma natural depois de um split, porque a base de dados passou a ter os preços do dia nas unidades novas. A única forma de substituir um dia é pedi-lo explicitamente (`python -m cnadump regenerate AAAA-MM-DD`, ou a entrada `force_date` do workflow). A substituição fica registada no `manifest.json` com o `sha256` anterior. O mesmo vale para o ficheiro de pagamentos de dividendos: se a base de dados passar a ter pagamentos diferentes dos arquivados para um dia (por exemplo, um pagamento que o bot só fez depois de o dia ser arquivado), a execução falha e o dia tem de ser regenerado. Regenerar não apaga um ficheiro de pagamentos cujos pagamentos desapareceram da base de dados. Os pull requests não podem alterar estes ficheiros: o workflow `verify-pr` falha se tocarem em `prices/`, `summary/`, `snapshots/`, `dividend_payouts/`, `daily/` ou nos ficheiros gerados da raiz.

## Validação antes de escrever

São erros duros, que não escrevem nada e terminam com código de saída 2: contagem de linhas diferente da anunciada pelo servidor, timestamps fora da janela do dia, preços não finitos ou não positivos, ticks duplicados `(ts, code, asset_type)`, tipos de ativo desconhecidos, mais de um servidor (`guild_id`) nos dados, dia sem nenhum tick, e, quando o último dia fechado é gerado antes das 11:00 do dia seguinte (a base de dados ainda está no estado do fecho), um último tick que não iguala o `current_price` atual de algum instrumento. Nos dias a partir de 2026-10-30 são também erros duros os pagamentos de dividendos inválidos (ver as regras de validação em [dividend_payouts](#dividend_payoutsaaaa-mm-ddjson)). São avisos, que não bloqueiam: instrumento sem ticks num dia em que já existia, lacunas de mais de 2 horas entre as 11:00 e as 23:00, e rótulos de beneficiários de dividendos que foram trocados por `Desconhecido`.

## Site e API estática (GitHub Pages)

Gerados pelo workflow a partir dos ficheiros já guardados (`python -m cnadump build-pages`). O site é o conteúdo da pasta `web/`, e a API e os ficheiros de dados juntam-se-lhe na mesma raiz.

### API

Os endereços da API não dependem do site: `build-pages` nunca deixa o `web/` ocupá-los.

| Endereço | Conteúdo |
|-|-|
| `latest.json` | último dia arquivado, ficheiros do dia (incluindo `dividend_payouts`, ou `null` se não houve pagamentos) e resumo do fecho |
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
| `dividend_payouts/AAAA-MM-DD.json` | só os dias com pagamentos de dividendos |

Ficam de fora os ticks (`prices/`), que o site lê de `https://raw.githubusercontent.com/CNAinput/dailydumps/main/prices/` só quando alguém os pede (a origem está em `TICKS_BASE`, no `web/js/config.js`). Fica de fora também o `instruments.json` do repositório, porque o `instruments.json` da API tem o mesmo nome; o seu conteúdo está nos snapshots.

### Regras do `build-pages`

- O `web/index.html` tem de existir, senão o comando falha (código de saída 2) e não escreve nada.
- Os ficheiros de `web/` são copiados para a raiz do site, exceto os ocultos (nomes que começam por ponto) e `__pycache__`.
- O `web/` não pode ter ficheiros com os endereços da API, com os ficheiros da lista acima, nem dentro das pastas `instruments/`, `daily/`, `summary/`, `snapshots/`, `dividend_payouts/` e `prices/`. Se tiver, o comando falha e lista os caminhos em conflito.
- A página inicial do site é o `index.html` do `web/`. A API é descrita em `api.html`.
