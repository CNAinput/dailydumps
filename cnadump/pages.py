"""Site e API estática para o GitHub Pages, gerados a partir dos ficheiros já commitados."""

import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from . import events as ev
from .errors import ValidationError
from .fmt import json_bytes, read_csv
from .slugs import assign_slugs
from .store import (
    DIVIDENDS, EVENTS, INSTRUMENTS, MANIFEST, OHLC, OHLC_ADJUSTED, SCHEMA_VERSION, STATUS, SUMS, TAXES,
)
from .timeutil import last_closed_day, parse_date

WEB_DIR = "web"
# Ficheiros do arquivo copiados para o site com o caminho do repositório. Os ticks (prices/) ficam de fora,
# o site lê-os do GitHub. O instruments.json do repositório também, porque o da API tem o mesmo nome.
SITE_FILES = (OHLC, OHLC_ADJUSTED, EVENTS, MANIFEST, STATUS, SUMS, DIVIDENDS, TAXES)
SITE_FOLDERS = ("summary", "snapshots", "dividend_payouts")
API_FILES = ("latest.json", "dates.json", "instruments.json", "badge.json", "api.html")
# Caminhos da API e dos dados: o site (web/) não os pode usar.
RESERVED_FILES = frozenset(API_FILES) | frozenset(SITE_FILES) | {INSTRUMENTS}
RESERVED_FOLDERS = frozenset({"instruments", "daily", "summary", "snapshots", "prices", "dividend_payouts"})

API_HTML = """<!doctype html>
<html lang="pt-PT">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>API do arquivo de dados do mercado da CNA</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 42rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
code { background: rgba(127, 127, 127, 0.2); padding: 0.1em 0.3em; border-radius: 3px; }
</style>
</head>
<body>
<p><a href="index.html">Voltar ao arquivo</a></p>
<h1>API do arquivo de dados do mercado da CNA</h1>
<p>API estática com os dados diários do mercado. Os dados estão sob a licença CC-BY 4.0.</p>
<ul>
<li><a href="latest.json"><code>latest.json</code></a>: o último dia arquivado, com o resumo do fecho.</li>
<li><a href="dates.json"><code>dates.json</code></a>: todos os dias arquivados.</li>
<li><a href="instruments.json"><code>instruments.json</code></a>: os instrumentos e o seu slug.</li>
<li><code>instruments/{slug}.json</code>: metadados, série diária e eventos de cada instrumento.</li>
<li><a href="badge.json"><code>badge.json</code></a>: estado para um selo do shields.io.</li>
</ul>
<p>Estes ficheiros do repositório também estão aqui, com o mesmo caminho: <code>daily/ohlc.csv</code>,
<code>daily/ohlc_adjusted.csv</code>, <code>events.csv</code>, <code>manifest.json</code>, <code>status.json</code>,
<code>SHA256SUMS</code>, <code>dividends.json</code>, <code>taxes.json</code>, <code>summary/AAAA-MM-DD.json</code>,
<code>snapshots/AAAA-MM-DD.json</code> e <code>dividend_payouts/AAAA-MM-DD.json</code> (os pagamentos de dividendos
do dia, só nos dias em que houve).</p>
<p>Os ticks de cada dia (<code>prices/AAAA/AAAA-MM-DD.csv</code>) estão no repositório.</p>
@@REPOSITORIO@@
</body>
</html>
"""


def _series(rows, key):
    return [
        {
            "date": r[0],
            "open": Decimal(r[3]), "high": Decimal(r[4]), "low": Decimal(r[5]), "close": Decimal(r[6]),
            "ticks": int(r[7]),
        }
        for r in rows if (r[1], r[2]) == key
    ]


def _event_json(event):
    return {
        "date": event.date.isoformat(),
        "event": event.event,
        "factor": event.factor,
        "shares_before": event.shares_before,
        "shares_after": event.shares_after,
        "document_id": event.document_id,
        "notes": event.notes,
    }


def _badge(last, now):
    gap = last_closed_day(now) - parse_date(last)
    color = "brightgreen" if gap <= timedelta(0) else "yellow" if gap == timedelta(days=1) else "red"
    return {"schemaVersion": 1, "label": "último dia", "message": last, "color": color}


def api_html(repository):
    """Página da API. A ligação ao repositório só aparece com um `dono/nome` válido."""
    link = ""
    if repository and re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        link = f'<p><a href="https://github.com/{repository}">Repositório no GitHub</a></p>'
    return API_HTML.replace("@@REPOSITORIO@@", link)


def _site_files(web):
    """Caminhos (com barras) dos ficheiros de `web/`, sem os ocultos. Falha se o site estiver incompleto ou colidir."""
    if not (web / "index.html").is_file():
        raise ValidationError(f"{WEB_DIR}/index.html em falta: o site não pode ser publicado.")
    found = []
    for path in sorted(web.rglob("*")):
        rel = path.relative_to(web)
        if path.is_file() and not any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            found.append(rel.as_posix())
    clashes = [rel for rel in found if rel in RESERVED_FILES or rel.split("/", 1)[0] in RESERVED_FOLDERS]
    if clashes:
        raise ValidationError(
            [f"{WEB_DIR}/{rel}: o caminho pertence à API ou aos dados e não pode ser usado pelo site" for rel in clashes]
        )
    return found


def _site_data(repo):
    """Ficheiros do arquivo que o site serve, por caminho relativo. Só os que existem."""
    found = {}
    for rel in SITE_FILES:
        data = repo.read(rel)
        if data is not None:
            found[rel] = data
    for folder in SITE_FOLDERS:
        base = repo.root / folder
        if base.is_dir():
            for path in sorted(base.glob("*.json")):
                found[f"{folder}/{path.name}"] = path.read_bytes()
    return found


def _put(out, rel, data):
    target = out / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def build_pages(repo, out, now, repository=None, web=None):
    """Escreve o site e a API em `out` e devolve os caminhos relativos criados."""
    manifest = repo.load_manifest()
    dates = sorted(manifest["days"])
    if not dates:
        raise ValidationError("Não há nenhum dia arquivado: não há nada para publicar.")
    web = Path(web) if web is not None else repo.root / WEB_DIR
    site = _site_files(web)
    last = dates[-1]
    ohlc = repo.load_ohlc_rows()
    adjusted_data = repo.read(OHLC_ADJUSTED)
    adjusted = read_csv(adjusted_data)[1] if adjusted_data else ohlc
    events_data = repo.read(EVENTS)
    events = ev.parse_events(events_data)[0] if events_data else []

    registry = repo.read_json(INSTRUMENTS) or {"instruments": []}
    known = {(i["code"], i["asset_type"]): i for i in registry["instruments"]}
    keys = sorted({(r[1], r[2]) for r in ohlc} | set(known))
    slugs = assign_slugs(keys, {k: v["slug"] for k, v in known.items()})

    files = {}
    entry = manifest["days"][last]
    last_rows = [r for r in ohlc if r[0] == last]
    day = parse_date(last)
    files["latest.json"] = {
        "schema_version": SCHEMA_VERSION,
        "date": last,
        "generated_at": entry["generated_at"],
        "source": entry["source"],
        "partial": entry["partial"],
        "rows": entry["rows"],
        "instruments": len(last_rows),
        "files": {
            "prices": repo.prices_rel(day),
            "summary": repo.summary_rel(day),
            "snapshot": repo.snapshot_rel(day) if repo.read(repo.snapshot_rel(day)) is not None else None,
            "dividend_payouts": repo.payouts_rel(day) if repo.read(repo.payouts_rel(day)) is not None else None,
        },
        "summary": repo.read_json(repo.summary_rel(day), exact=True),
    }
    files["dates.json"] = {
        "schema_version": SCHEMA_VERSION,
        "first": dates[0],
        "last": last,
        "count": len(dates),
        "dates": [
            {"date": d, "source": manifest["days"][d]["source"], "partial": manifest["days"][d]["partial"],
             "rows": manifest["days"][d]["rows"]}
            for d in dates
        ],
    }
    files["instruments.json"] = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_date": registry.get("snapshot_date"),
        "instruments": [
            {"code": k[0], "asset_type": k[1], "name": known.get(k, {}).get("name"), "slug": slugs[k]} for k in keys
        ],
    }
    for key in keys:
        meta = known.get(key, {})
        files[f"instruments/{slugs[key]}.json"] = {
            "schema_version": SCHEMA_VERSION,
            "code": key[0],
            "asset_type": key[1],
            "slug": slugs[key],
            "name": meta.get("name"),
            "is_index": meta.get("is_index"),
            "owner_company_code": meta.get("owner_company_code"),
            "daily": _series(ohlc, key),
            "daily_adjusted": _series(adjusted, key),
            "events": [_event_json(e) for e in events if e.key == key],
        }
    files["badge.json"] = _badge(last, now)

    written = []
    out.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        _put(out, rel, json_bytes(content))
        written.append(rel)
    _put(out, "api.html", api_html(repository).encode("utf-8"))
    written.append("api.html")
    for rel in site:
        _put(out, rel, (web / rel).read_bytes())
        written.append(rel)
    for rel, data in _site_data(repo).items():
        _put(out, rel, data)
        written.append(rel)
    return sorted(written)
