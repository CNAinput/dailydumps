# Operação

Guia para quem mantém o arquivo. Os formatos e as regras dos dados estão em `docs/SCHEMA.md` e as fontes em `docs/SOURCES.md`.

## Como funciona

O workflow `dump` corre várias vezes por dia e cada execução faz o mesmo: calcula os **dias fechados que ainda não têm ficheiro**, do dia a seguir ao último arquivado até ao último fecho (as 23:00 de Lisboa), com um máximo de 40 dias para trás, que é a retenção do bot. Se não há nada a fazer, termina sem alterações e sem pedidos à base de dados.

| Hora de Lisboa | O que acontece |
|-|-|
| cerca de 23:15 | primeira tentativa do dia: arquiva o dia que acabou de fechar, com snapshot |
| 00:15 até 10:30 | repetições de cerca de 3 em 3 horas, só para o caso de a primeira ter falhado |
| depois das 11:00 | um dia que só seja arquivado agora fica sem snapshot (`source` igual a `backfill`), porque o mercado já reabriu e as shares detidas já mudaram |

O cron está em UTC e cobre o horário de verão e o de inverno (`17 22,23,1,4,7,9 * * *`, sem usar o minuto 00 para fugir ao congestionamento do GitHub). Algumas execuções caem antes do fecho e não fazem nada, e isso é intencional. O script decide sempre pelo relógio de Lisboa.

Cada execução que gera dados faz, por esta ordem: testes, geração, ajuste das séries aos eventos, verificação de integridade, commit com rebase e push, abertura de issues para eventos por registar, geração e publicação do site e da API estática no GitHub Pages, e ping ao Healthchecks.io. Se um passo falhar, o ping de falha é enviado e o GitHub envia um email.

## O que o dono tem de configurar

O repositório é <https://github.com/CNAinput/dailydumps> e a API estática fica em <https://cnainput.github.io/dailydumps/>. Por esta ordem:

1. **Carregar os ficheiros** para a branch `main` (a branch ainda não está protegida).
2. **Definir as duas variáveis do repositório**, em [Settings, Secrets and variables, Actions, Variables](https://github.com/CNAinput/dailydumps/settings/variables/actions): `SUPABASE_URL` e `SUPABASE_ANON_KEY`. São variáveis e não segredos porque a chave anónima é pública por desenho. Os valores estão no `site/app/js/config.js` do projeto do bot.
3. **Ativar o Pages com a fonte GitHub Actions**, em [Settings, Pages](https://github.com/CNAinput/dailydumps/settings/pages), Source. Tem de ser feito antes da primeira execução, porque o passo de publicação falha se o Pages não estiver ativo.
4. **Criar o check no Healthchecks.io** com período de 1 dia e tolerância (grace time) de cerca de 2 horas, e guardar o URL de ping como segredo `HEALTHCHECK_URL` em [Settings, Secrets and variables, Actions, Secrets](https://github.com/CNAinput/dailydumps/settings/secrets/actions). É opcional: sem o segredo, o ping é simplesmente ignorado.
5. **Confirmar a equipa do CODEOWNERS.** O `.github/CODEOWNERS` indica `@CNAinput/devs`: a equipa tem de existir na organização e ter permissão de escrita no repositório.
6. **Proteger a branch principal** com um [ruleset](https://github.com/CNAinput/dailydumps/settings/rules/new?target=branch) (Settings, Rules, Rulesets, New branch ruleset): enforcement Active, alvo a branch por omissão, e as regras "Restrict deletions" e "Block force pushes". **Não** ativar "Require a pull request before merging" nem "Require status checks to pass": o workflow `dump` faz push direto com o `GITHUB_TOKEN` e essas regras bloqueá-lo-iam. Os pull requests de terceiros continuam verificados pelo `verify-pr`.
7. **Verificar as permissões do workflow** em [Settings, Actions, General](https://github.com/CNAinput/dailydumps/settings/actions). O ficheiro `dump.yml` pede escrita no `permissions`, mas se a organização limitar o `GITHUB_TOKEN` a leitura e o push falhar com 403, escolher "Read and write permissions".
8. **Disparar a primeira execução manual**: Actions, `dump`, Run workflow, sem preencher nenhuma entrada.

## Variáveis e segredos

| Nome | Tipo | Onde | Obrigatório |
|-|-|-|-|
| `SUPABASE_URL` | variável | workflow e `.env` local | sim |
| `SUPABASE_ANON_KEY` | variável | workflow e `.env` local | sim |
| `HEALTHCHECK_URL` | segredo | workflow e `.env` local | não |
| `GH_TOKEN` | automático (`github.token`) | workflow | para abrir issues |
| `CNADUMP_NOW` | ambiente | só ensaios locais | não |

O `.env` local é ignorado pelo Git. O `.env.example` mostra o formato. A chave anónima só lê o que as políticas RLS já expõem, e o arquivo nunca usa a chave de serviço nem escreve na base de dados: faz pedidos GET e um único POST, à função pública de leitura `rpc_get_market_aggregates`.

## Workflows

- **`dump.yml`**: agendado e manual. Tem uma única concorrência (`dump`), que serializa as execuções sem cancelar nenhuma. As permissões são as mínimas necessárias: escrever o conteúdo, abrir issues e publicar no Pages. Tem duas entradas manuais: `backfill_from` (gera dias passados sem snapshots a partir dessa data) e `force_date` (regenera um dia já arquivado, o que fica registado no manifesto). Só publica a API estática quando houve alterações ou numa execução manual.
- **`verify-pr.yml`**: em cada pull request corre os testes, a verificação de integridade, o `sha256sum -c SHA256SUMS` e a guarda `guard`, que falha se o pull request tocar em `prices/`, `summary/`, `snapshots/`, `dividend_payouts/`, `daily/` ou nos ficheiros gerados da raiz (`manifest.json`, `SHA256SUMS`, `status.json`, `instruments.json`, `dividends.json`, `taxes.json`). Só o `events.csv`, a documentação, o código e os testes podem mudar por pull request.
- **Versões das actions**: estão fixadas por tag de versão exata (`actions/checkout`, `actions/setup-python`, `actions/upload-pages-artifact` e `actions/deploy-pages`). Para maior rigor podem passar a SHA de commit: troca-se `@v7.0.1` pelo SHA de 40 caracteres do mesmo release, deixando a versão num comentário.

## O site

O site vive na pasta `web/` e é publicado, com a API estática, pelo workflow `dump`. Usa só HTML, CSS e JavaScript puros: sem dependências, sem passo de compilação e sem recursos externos (uma política de segurança de conteúdo no `index.html` recusa tudo o que não venha do próprio domínio ou do `raw.githubusercontent.com`).

**Republicar depois de alterar o `web/`.** O GitHub Pages só republica quando o `dump` corre, às horas agendadas ou à mão. Um commit que só mexa no `web/` não dispara nada. Depois de carregar os ficheiros, abre Actions, `dump`, Run workflow, sem preencher nenhuma entrada. Numa execução manual o site e a API são sempre gerados e publicados, mesmo que não haja nada novo para arquivar. O GitHub Pages guarda os ficheiros em cache até 10 minutos: os dados são pedidos com revalidação, mas o CSS e os scripts podem demorar a atualizar (Ctrl+F5 resolve).

**Testar no computador.**

```bash
python -m cnadump build-pages _site
python -m http.server 8000 -d _site
```

Depois abre <http://localhost:8000>. Os módulos do site não funcionam a partir de `file://`.

**Onde mudar o quê.** Em `web/js/config.js`: o repositório, a origem dos ticks (`TICKS_BASE`; se ficar vazia o site lê os ticks do próprio domínio, e então o `build-pages` tem de passar a copiar `prices/`), o modelo do endereço dos despachos (`DOCUMENT_URL`, com `{id}`; vazio, mostra só o número), o máximo de dias por pesquisa de ticks e o limiar dos avisos de poucos ticks. As cores estão no início do `web/css/site.css`, com o tema escuro a seguir a preferência do sistema.

**Garantias.** O `tests/test_web.py` verifica que o `web/` não usa `innerHTML` nem equivalentes (os nomes das empresas são escritos por utilizadores do Discord), que não carrega nada de fora, que tem a política de segurança de conteúdo e que todos os módulos existem e são usados. O `tests/test_style.py` aplica ao `.css` e ao `.js` as regras de estilo do resto do repositório (sem travessões nem dois traços seguidos; as propriedades personalizadas do CSS só valem em ficheiros `.css`).

Os testes correm no `dump` antes de arquivar. Um erro de estilo ou de segurança num ficheiro do `web/` carregado diretamente na `main` faz o `dump` dessa noite falhar até ser corrigido. Não se perdem dados, porque a base de dados guarda 40 dias.

## Exploração local

Requer Python 3.10 ou superior. Não há dependências, exceto o `tzdata` no Windows.

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/python -m cnadump verify
```

No Windows o interpretador do ambiente é `.venv\Scripts\python.exe`. Os comandos leem o `.env` da raiz do repositório. Nos exemplos abaixo `python` quer dizer o interpretador do ambiente.

| Comando | O que faz |
|-|-|
| `python -m cnadump day [AAAA-MM-DD]` | gera os dias fechados em falta (ou só a data indicada) |
| `python -m cnadump backfill [AAAA-MM-DD]` | gera dias passados sem snapshots, desde a data indicada ou o primeiro dia disponível |
| `python -m cnadump regenerate AAAA-MM-DD` | substitui o ficheiro de um dia já arquivado e regista-o no manifesto |
| `python -m cnadump adjust` | regenera `daily/ohlc_adjusted.csv` a partir do `events.csv` |
| `python -m cnadump verify` | verifica a integridade do repositório |
| `python -m cnadump pending` | mostra os eventos estruturais por registar (`pending open` abre as issues com o `gh`) |
| `python -m cnadump build-pages [pasta]` | gera o site (`web/`) e a API estática (por omissão em `_site/`) |
| `python -m cnadump guard` | lê caminhos do stdin e falha se algum só puder ser escrito pelo workflow |
| `python -m cnadump ping ok` ou `fail` | envia o ping ao Healthchecks.io, se houver URL |

`CNADUMP_NOW` (um instante ISO 8601 com fuso, por exemplo `2026-10-27T23:17:00+00:00`) substitui o relógio, só para ensaios. Sem ele usa-se a hora atual.

| Código de saída | Significado |
|-|-|
| 0 | tudo certo, ou nada a fazer |
| 1 | erro de configuração, de rede, ou argumento inválido |
| 2 | erro duro nos dados (nada foi escrito) ou ficheiro de um dia que já existe e difere |
| 3 | a verificação de integridade ou a guarda dos pull requests falhou |

## Erros duros: o que fazer

Qualquer erro duro termina com o código 2 e uma mensagem em português, e **não escreve nada**. A execução seguinte volta a tentar. Em todos os casos o repositório fica como estava, e os dias anteriores ao problema não são perdidos enquanto a base de dados os guardar (40 dias).

| Mensagem | Causa provável | O que fazer |
|-|-|-|
| `Contagem diferente em price_history` ou `A contagem ... mudou durante a leitura` | falha de rede, ou dados a mudar durante a leitura | esperar pela repetição seguinte; se persistir, abrir o Supabase e comparar |
| `timestamps fora da janela do dia` | o servidor devolveu linhas que o filtro do dia devia excluir | resposta inesperada do servidor: investigar antes de repetir |
| `preços não finitos ou não positivos` | dado corrompido na base de dados | corrigir na origem; só depois o dia pode ser arquivado |
| `ticks duplicados` | linha repetida em `price_history` | corrigir na origem |
| `dia sem nenhum tick` | o bot esteve parado o dia todo, ou a chave anónima perdeu o acesso | ver abaixo, em "Um dia sem ticks" |
| `o último tick de X é A mas o preço atual é B` | o preço atual foi alterado sem registo no histórico, ou há ticks por ler | corrigir a origem (por exemplo um split mal aplicado) e repetir |
| `mais de um servidor (guild_id)` | as políticas RLS passaram a expor outro servidor | rever as políticas; o arquivo é de um só servidor |
| `já existe com N ticks e o recalculado tem M` | o dia mudou na base de dados (típico depois de um split) | normal: o ficheiro arquivado mantém-se; para o substituir usar `regenerate` |
| `dividend_payouts, linha N: ...` (por exemplo `a soma dos pagamentos (...) difere de total_paid`, `origin desconhecido`, `kind desconhecido`) | uma linha de `dividend_payouts` inválida, em geral por um erro do bot ao registar | corrigir a linha na origem; só depois o dia pode ser arquivado |
| `os pagamentos de dividendos da base de dados diferem de dividend_payouts/...` | o bot registou um pagamento depois de o dia ter sido arquivado (por exemplo, esteve parado depois das 23:00) | usar `regenerate` nesse dia |
| `Acesso recusado pelo servidor (HTTP 401)` | URL ou chave erradas nas variáveis do repositório | corrigir as variáveis |
| `web/index.html em falta: o site não pode ser publicado` | a pasta `web/` ou o `index.html` foi apagado | repor o `web/` e disparar o `dump` à mão |
| `web/...: o caminho pertence à API ou aos dados` | um ficheiro do `web/` usa um endereço reservado | mudar o nome ou apagar esse ficheiro |

## Registar um evento estrutural

Os IPO, splits, emissões e retiradas de cotação registam-se à mão em `events.csv`, por pull request. O workflow nunca escreve neste ficheiro.

1. Quando o instantâneo de um dia difere do anterior (`shares_total` mudou, ou um código apareceu ou desapareceu) e o `events.csv` ainda não cobre a alteração, o workflow abre uma issue com o título `Eventos por registar em events.csv (AAAA-MM-DD)`. O título é estável, por isso a mesma situação nunca abre duas issues, mesmo depois de a issue ser fechada. O corpo traz as linhas sugeridas.
2. Abre um pull request que acrescente a linha ao `events.csv`, com o `document_id` do despacho se existir. Os pull requests são verificados: o cabeçalho, os tipos, o factor e as contas das shares têm de estar certos.
3. Depois do merge, a execução seguinte regenera `daily/ohlc_adjusted.csv`.

**A data de um evento** é o dia civil de Lisboa do primeiro ficheiro diário gerado depois da alteração. Na prática é o dia em que a alteração foi aplicada. Se foi aplicada entre as cerca de 23:17, quando o ficheiro desse dia já foi gerado, e a meia-noite, regista-se o dia seguinte. As issues sugerem a data correta. Se um dia foi gerado depois da meia-noite (numa repetição) e a alteração foi aplicada mais tarde nesse mesmo dia, esse ficheiro tem preços antigos mas não é ajustado: regenera-o com `force_date` depois da alteração.

Exemplos (os números são os reais de 2026-10-11 e 2026-10-13):

```csv
2026-10-11,P&PNV,asset,issuance,,250000,750000,83,Emissão de 500000 shares.
2026-10-11,NEWTE,company,split,4,75000,300000,84,Split líquido 1 para 4.
```

Quando uma alteração tem vários passos no mesmo dia, regista-se o efeito líquido por ordem (aqui uma emissão e depois um split).

## Regenerar um dia

Só por pedido explícito: Actions, `dump`, Run workflow, `force_date` com a data. O ficheiro do dia é substituído e o `manifest.json` guarda em `regenerations` o instante, o `sha256` e o número de ticks anteriores. Se o recalculado for igual ao arquivado não muda nada. Os pull requests nunca podem fazer isto.

Usa-se, por exemplo, quando um dia foi arquivado com dados que a origem corrigiu, ou para um dia arquivado antes de um split que se queira nas unidades novas.

## Pagamentos de dividendos

O bot regista cada pagamento de dividendos na tabela `dividend_payouts` (uma linha por política paga, com o valor distribuído e o que recebeu cada beneficiário), e cada dia arquivado a partir de 2026-10-30 leva os pagamentos desse dia civil de Lisboa num ficheiro `dividend_payouts/AAAA-MM-DD.json`. O pagamento é às 23:00, por isso entra no ficheiro do próprio dia, arquivado cerca das 23:17. O formato está em `docs/SCHEMA.md`.

- **O bot tem de estar atualizado.** Se o bot em produção ainda não escreve em `dividend_payouts`, os pagamentos desse dia não existem na base de dados e o dia fica com `dividend_payouts` a 0 no manifesto. O registo de auditoria do bot (`audit_events`) guarda durante 3 dias o valor pago a cada conta, por isso nesse prazo ainda se reconstrói à mão (ver o último ponto).
- **A base de dados só guarda os pagamentos 14 dias.** O arquivo copia-os no próprio dia e o bot apaga-os depois (`prune_old_data`), por isso a tabela fica sempre pequena. Se o `dump` ficar parado mais de 14 dias, os dias que ficarem por arquivar nesse intervalo saem sem pagamentos (com um aviso, e sem o campo `dividend_payouts` no manifesto); os preços continuam recuperáveis até 40 dias. O alerta de 26 horas do Healthchecks.io existe precisamente para que isto nunca chegue a acontecer.
- **Um pagamento que o bot só faça depois de o `dump` do dia ter corrido** (esteve parado às 23:00 e pagou, por exemplo, às 23:40) não entra no ficheiro desse dia, e as execuções normais não dão por isso porque só olham para a frente. Acrescenta-se com `regenerate` (Actions, `dump`, `force_date` com a data), que fica registado em `regenerations`. Se o pagamento só chegar depois da meia-noite, pertence ao dia seguinte e não há nada a fazer.
- **Reconstruir um pagamento à mão** (só se o registo falhou): inserir a linha em `dividend_payouts` com `origin` igual a `reconstruction`, com a soma dos `amount` igual a `total_paid`, e depois `regenerate` do dia. Convém conferir cada parcela com `pool` vezes `shares` a dividir por `total_shares`, arredondado a 2 casas.

## Um dia sem ticks

Se o bot esteve parado durante um dia inteiro, esse dia não existe na base de dados e o arquivo recusa-o (`dia sem nenhum tick`). Nada pode ser inventado, e o dia tem de ficar de fora do arquivo. Para o ultrapassar sem bloquear os dias seguintes:

1. Actions, `dump`, Run workflow, com `backfill_from` igual ao dia **a seguir** ao dia vazio. Isto arquiva todos os dias desde essa data (sem snapshots, porque o mercado já reabriu).
2. A partir daí as execuções diárias normais retomam: o `day` só olha para a frente a partir do último dia arquivado, por isso o buraco não volta a bloquear.

O dia em falta fica visível no `dates.json`. O mesmo procedimento serve para qualquer dia que não possa ser arquivado por um erro duro que só a origem pode corrigir e que não se queira esperar.

## Alertas

- **Email do GitHub** quando um workflow falha, sem configuração adicional.
- **Healthchecks.io** (dead man's switch): cada execução bem-sucedida envia um ping, mesmo as que não tinham nada para fazer, e uma execução falhada envia o ping de falha. Com período de 1 dia e tolerância de cerca de 2 horas, o Healthchecks.io avisa se passarem mais de 26 horas sem nenhum ping, o que cobre falhas que nem chegam a correr (agendamento desativado, repositório inacessível, chave revogada, conta suspensa). Num repositório público o GitHub desativa os workflows agendados após 60 dias sem atividade; se isso acontecer a falta de pings avisa, e reativa-se o workflow no separador Actions. Os pings falhados não fazem falhar a execução.

## Limites a conhecer

- A retenção do bot é de 40 dias: um dia que o arquivo não consiga gerar durante 40 dias perde-se.
- O arquivo não tem como reconstituir shares detidas passadas. Os dias arquivados depois do fecho (backfill) não têm snapshot nem capitalização.
- Os agendamentos do GitHub podem atrasar. Por isso há repetições até às 10:30, e um dia que só seja gerado depois das 11:00 fica sem snapshot.
- O ajuste de séries só trata splits. Reverse splits entram com um `factor` inferior a 1.
- Os ticks que o site mostra vêm do `raw.githubusercontent.com`, que guarda em cache cerca de 5 minutos e pode limitar pedidos em excesso. Uma pesquisa de ticks carrega no máximo 60 dias, cerca de 80 KB cada.
