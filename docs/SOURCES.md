# Fontes de dados

Este documento regista o que o arquivo lê da base de dados e como o acesso foi verificado. O script só faz pedidos GET ao PostgREST e um POST à função pública de leitura `rpc_get_market_aggregates`. Não escreve na base de dados e não usa credenciais privadas.

## Acesso

| Item | Valor |
|-|-|
| URL | variável `SUPABASE_URL` |
| Chave | variável `SUPABASE_ANON_KEY` (chave anónima, pública por desenho) |
| Cabeçalhos | `apikey` e `Authorization: Bearer`, ambos com a chave anónima |
| Linhas visíveis | política RLS `guild_id = cna_guild_id()` (um só servidor) |
| Escrita | nenhuma |

## Tabelas e colunas lidas

| Tabela | Colunas lidas | Tipos na base de dados |
|-|-|-|
| `price_history` | `code`, `asset_type`, `price`, `timestamp`, `guild_id` (ordenação extra por `id`) | text, text (`company` ou `asset`), double precision, timestamptz, bigint |
| `companies` | `code`, `name`, `current_price`, `shares_total`, `creation_date` | text, text, double precision, integer, timestamptz |
| `assets` | `code`, `name`, `current_price`, `shares_total`, `is_index`, `owner_company_code`, `creation_date` | text, text, double precision, integer, boolean, text, timestamptz |
| `dividends` | `code`, `asset_type`, `percentage`, `distribution_days`, `next_distribution`, `last_distribution` | text, text, double precision, integer, timestamptz, timestamptz |
| `server_taxes` | `juros`, `income`, `iva`, `last_changed` | double precision (3), timestamptz |

A função `rpc_get_market_aggregates()` devolve uma linha por instrumento com shares detidas: `code` (text), `asset_type` (text), `held_shares` (bigint). Os instrumentos sem nenhuma share detida não aparecem, e o arquivo trata-os como zero.

### Colunas que nunca são lidas

`account_id` e `majority_owner` (identificam contas ou utilizadores), os `id` de cada tabela (excepto a ordenação de `price_history`, que não os devolve) e os restantes campos de gestão (`is_ipo`, `ipo_date`, `index_divisor`, `index_cap_basis`, `last_majority_check`). O `creation_date` é usado apenas internamente, para não avisar "sem ticks" antes de um instrumento existir, e não é exportado.

### Significado dos impostos

| Coluna | Significado no bot | Chave exportada |
|-|-|-|
| `juros` | taxa de juro (percentagem por dia) aplicada aos empréstimos novos | `loan_interest_pct` |
| `income` | imposto sobre os salários, cobrado para o Banco Público | `income_tax_pct` |
| `iva` | IVA incluído no preço das compras na loja, entregue ao Banco Público | `vat_pct` |

## Comportamento do PostgREST observado

- O máximo é de 1000 linhas por pedido. O cliente pagina com `limit` e `offset` e avança pelo número de linhas realmente recebidas.
- Com `Prefer: count=exact` a resposta traz `Content-Range: 0-999/TOTAL`. Quando há mais linhas do que as devolvidas, o estado HTTP é **206** e não 200. O cliente aceita os dois.
- O endpoint OpenAPI (`GET /rest/v1/`) só aceita a chave de serviço. Os tipos acima vêm de `information_schema.columns` e dos próprios dados.
- `timestamp` chega em UTC com o formato `2026-10-08T16:57:59.859173+00:00`. A parte fraccionária tem de 0 a 6 dígitos e os zeros finais são omitidos.
- `price` chega como número JSON. O arquivo lê-o como `Decimal` para preservar o texto exacto.

## Retenção

A tarefa `prune_old_data` do bot apaga `price_history` com mais de 40 dias, de 24 em 24 horas. O primeiro dia disponível pode por isso estar cortado, e o arquivo marca-o como `partial` quando a abertura do mercado desse dia é anterior a `generated_at` menos 40 dias.

## Verificação de acesso (2026-10-27)

| Pedido | Estado | Resultado |
|-|-|-|
| GET `price_history` (1 linha, `count=exact`) | 206 | `0-0/70887` |
| GET `companies` | 206 | `0-0/6` |
| GET `assets` | 206 | `0-0/8` |
| GET `dividends` | 206 | `0-0/4` |
| GET `server_taxes` | 200 | `0-0/1` |
| POST `rpc_get_market_aggregates` | 200 | 13 linhas |

Conferido com SELECT à base de dados real: a chave anónima vê todas as linhas de `price_history` (um só `guild_id`, nenhum `timestamp` nulo, nenhum preço não positivo ou não finito, nenhum duplicado em `(timestamp, code, asset_type)`). O primeiro tick existente é de 2026-09-17T10:00:07Z.
