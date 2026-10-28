# Arquivo de dados do mercado da CNA

[![dump](https://github.com/CNAinput/dailydumps/actions/workflows/dump.yml/badge.svg)](https://github.com/CNAinput/dailydumps/actions/workflows/dump.yml)
[![último dia arquivado](https://img.shields.io/endpoint?url=https%3A%2F%2Fcnainput.github.io%2Fdailydumps%2Fbadge.json)](https://cnainput.github.io/dailydumps/latest.json)

Arquivo público e permanente dos dados diários do mercado de ações da economia virtual da CNA, uma comunidade de Discord em português. Os valores estão em coins (¢), uma moeda fictícia.

O bot da CNA só guarda 40 dias de histórico de preços e apaga o resto. Este repositório copia todos os dias esses preços, e outros dados que já são públicos, para ficarem permanentes e abertos à comunidade.

## O que contém

| Caminho | Conteúdo |
|-|-|
| `prices/AAAA/AAAA-MM-DD.csv` | todos os ticks de preço do dia, tal como na base de dados |
| `daily/ohlc.csv` | abertura, máximo, mínimo, fecho e número de ticks por instrumento e dia |
| `daily/ohlc_adjusted.csv` | o mesmo, ajustado aos splits registados em `events.csv` |
| `snapshots/AAAA-MM-DD.json` | estado no fecho: shares, shares em circulação e capitalização |
| `summary/AAAA-MM-DD.json` | resumo do fecho: índices, maior subida e descida, maiores empresas |
| `instruments.json` | instrumentos do último instantâneo, com o slug usado nos endereços |
| `dividends.json`, `taxes.json` | política de dividendos e impostos em vigor |
| `events.csv` | IPO, splits, emissões e retiradas de cotação, registados à mão |
| `manifest.json`, `SHA256SUMS`, `status.json` | integridade e estado do arquivo |

Os formatos e as regras de cada ficheiro estão em [docs/SCHEMA.md](docs/SCHEMA.md).

## Cobertura

O arquivo começa a **2026-09-18**, o primeiro dia que ainda existia na base de dados quando foi criado. Os dias até ao momento da criação foram arquivados de uma só vez (`backfill`) e a partir daí o arquivo é diário.

- Os dias de `backfill` não têm snapshot nem capitalização: a história de shares detidas não se consegue reconstituir. Nos resumos desses dias os campos de capitalização são `null` e `market_cap_available` é `false`.
- O primeiro dia pode ter perdido ticks pela retenção do bot. Esses dias ficam com `partial` verdadeiro no `manifest.json`. Neste momento nenhum dia está marcado como parcial: o primeiro dia arquivado começa às 11:00 de Lisboa, a hora de abertura.
- Há um buraco real nos dados: em 2026-10-13 todos os instrumentos ficaram cerca de 4 horas seguidas sem ticks (entre as 17:03 e as 21:23 de Lisboa). Os ficheiros refletem o que a base de dados tinha.
- Os índices têm alguns ticks isolados com o valor exato `100`, que é o valor base. Também estão na base de dados e são arquivados tal como estão.

## Como usar

Os ficheiros são texto (CSV e JSON, UTF-8, fim de linha LF) e podem ser lidos diretamente no GitHub ou clonando o repositório.

```python
import csv

with open("daily/ohlc.csv", encoding="utf-8", newline="") as ficheiro:
    for linha in csv.DictReader(ficheiro):
        print(linha["date"], linha["code"], linha["close"])
```

Para confirmar que nada foi alterado: `sha256sum -c SHA256SUMS`.

Também há uma API estática em <https://cnainput.github.io/dailydumps/>: [`latest.json`](https://cnainput.github.io/dailydumps/latest.json) (último dia e resumo), [`dates.json`](https://cnainput.github.io/dailydumps/dates.json), [`instruments.json`](https://cnainput.github.io/dailydumps/instruments.json), `instruments/{slug}.json` (série diária, série ajustada e eventos de cada instrumento) e [`badge.json`](https://cnainput.github.io/dailydumps/badge.json).

### O que convém saber

- **Um dia é o dia civil de Lisboa.** Os instantes dos ticks estão em UTC e há dias de 23 horas (março) e de 25 horas (outubro). O mercado está aberto todos os dias das 11:00 às 23:00 de Lisboa.
- **Splits.** Quando o bot faz um split reescreve todo o histórico, mas os ficheiros já arquivados não mudam. Os preços de dias gerados antes do split estão nas unidades antigas. Para uma série contínua usa `daily/ohlc_adjusted.csv`, ou `events.csv` e o `generated_at` de cada dia no manifesto.
- **Os ficheiros de dias passados são imutáveis.** Só são substituídos por um pedido explícito, que fica registado no manifesto.
- **Capitalização** é o preço vezes as shares em circulação (as detidas), nunca vezes as shares autorizadas.
- **Privacidade.** Não se exportam identificadores de contas nem de utilizadores.

## Contribuir

- **Dado errado**: [abre uma issue](https://github.com/CNAinput/dailydumps/issues/new/choose) com o modelo "Dado errado". Os ficheiros de dias passados não se corrigem por pull request.
- **Evento estrutural** (IPO, split, emissão, retirada de cotação): acrescenta uma linha ao `events.csv` num pull request. Quando o workflow deteta uma alteração por registar abre uma issue com as linhas sugeridas. O guia está em [docs/OPERATIONS.md](docs/OPERATIONS.md).
- Os pull requests só podem alterar o `events.csv`, a documentação, o código e os testes. O workflow `verify-pr` falha se tocarem em ficheiros de dias passados.

## Desenvolvimento

Python 3.10 ou superior, sem dependências externas (o pacote `tzdata` só é preciso no Windows).

```bash
python -m unittest discover -s tests -t .
python -m cnadump verify
```

Mais detalhes, o funcionamento do workflow e o que o dono tem de configurar estão em [docs/OPERATIONS.md](docs/OPERATIONS.md). As fontes de dados e o acesso verificado estão em [docs/SOURCES.md](docs/SOURCES.md).

## Licenças

O código tem licença MIT ([LICENSE](LICENSE)) e os dados têm licença CC BY 4.0 ([LICENSE-DATA.md](LICENSE-DATA.md)).

Mantido pelo Instituto de Plataformas e Utilidades Tecnológicas da CNA (organização [CNAinput](https://github.com/CNAinput)).
