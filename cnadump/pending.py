"""Eventos estruturais por registar: compara instantâneos consecutivos com o events.csv."""

import csv
import io
import json
import subprocess
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from . import events as ev
from .errors import DumpError, ValidationError
from .fmt import plain
from .store import EVENTS
from .timeutil import parse_date

TITLE = "Eventos por registar em events.csv ({day})"
KIND_EVENTS = {"appeared": ("ipo",), "disappeared": ("delisting",), "shares": ("split", "issuance")}
SPLIT_CAP_RANGE = (Decimal("0.65"), Decimal("1.5"))


@dataclass(frozen=True)
class Change:
    kind: str
    code: str
    asset_type: str
    date_from: date
    date_to: date
    before: Optional[dict]
    after: Optional[dict]

    @property
    def key(self):
        return (self.code, self.asset_type)


@dataclass(frozen=True)
class Issue:
    title: str
    body: str


def diff_snapshots(prev, new):
    """Códigos que apareceram ou desapareceram e instrumentos cujo shares_total mudou."""
    old = {(i["code"], i["asset_type"]): i for i in prev["instruments"]}
    cur = {(i["code"], i["asset_type"]): i for i in new["instruments"]}
    start, end = parse_date(prev["date"]), parse_date(new["date"])
    changes = []
    for key in sorted(set(old) | set(cur)):
        if key not in old:
            changes.append(Change("appeared", key[0], key[1], start, end, None, cur[key]))
        elif key not in cur:
            changes.append(Change("disappeared", key[0], key[1], start, end, old[key], None))
        elif old[key]["shares_total"] != cur[key]["shares_total"]:
            changes.append(Change("shares", key[0], key[1], start, end, old[key], cur[key]))
    return changes


def is_covered(change, events):
    return any(
        e.key == change.key and e.event in KIND_EVENTS[change.kind] and change.date_from <= e.date <= change.date_to
        for e in events
    )


def pending_changes(repo):
    days = repo.snapshot_days()
    if len(days) < 2:
        return []
    data = repo.read(EVENTS)
    events, errors = ev.parse_events(data) if data is not None else ([], [])
    if errors:
        raise ValidationError(errors)
    pending = []
    for first, second in zip(days, days[1:]):
        prev = repo.read_json(repo.snapshot_rel(first), exact=True)
        new = repo.read_json(repo.snapshot_rel(second), exact=True)
        pending += [c for c in diff_snapshots(prev, new) if not is_covered(c, events)]
    return pending


def _csv_line(values):
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="").writerow(values)
    return buffer.getvalue()


def suggestion(change):
    """Linha sugerida para o events.csv. É só um ponto de partida: o dono confirma tudo."""
    day = change.date_to.isoformat()
    if change.kind == "appeared":
        return _csv_line([day, change.code, change.asset_type, "ipo", "", "", change.after["shares_total"], "", ""])
    if change.kind == "disappeared":
        return _csv_line([day, change.code, change.asset_type, "delisting", "", change.before["shares_total"], "", "", ""])
    before, after = int(change.before["shares_total"]), int(change.after["shares_total"])
    cap_before = Decimal(change.before["price"]) * before
    cap_after = Decimal(change.after["price"]) * after
    if before > 0 and cap_before > 0 and SPLIT_CAP_RANGE[0] < cap_after / cap_before < SPLIT_CAP_RANGE[1]:
        factor = plain((Decimal(after) / Decimal(before)).normalize())
        return _csv_line([day, change.code, change.asset_type, "split", factor, before, after, "", ""])
    return _csv_line([day, change.code, change.asset_type, "issuance", "", before, after, "", ""])


def _describe(change):
    name = f"`{change.code}` ({change.asset_type})"
    if change.kind == "appeared":
        return f"- {name}: apareceu, com `shares_total` {change.after['shares_total']}."
    if change.kind == "disappeared":
        return f"- {name}: desapareceu (tinha `shares_total` {change.before['shares_total']})."
    return (
        f"- {name}: `shares_total` passou de {change.before['shares_total']} para {change.after['shares_total']} "
        f"(preço {change.before['price']} para {change.after['price']})."
    )


def issue_for(day, changes):
    first = min(c.date_from for c in changes)
    lines = [
        f"Entre os instantâneos de {first} e {day} foram detetadas alterações que ainda não constam de `events.csv`:",
        "",
        *[_describe(c) for c in changes],
        "",
        "Linhas sugeridas para acrescentar ao `events.csv` (confirma o tipo, a data e os números antes de submeter):",
        "",
        "```csv",
        *[suggestion(c) for c in changes],
        "```",
        "",
        "A data de um evento é o dia civil de Lisboa em que a alteração foi aplicada na base de dados. "
        "As regras completas estão em `docs/OPERATIONS.md`. Depois de o pull request ser aceite, esta issue pode ser fechada.",
    ]
    return Issue(TITLE.format(day=day), "\n".join(lines))


def pending_issues(repo):
    by_day = {}
    for change in pending_changes(repo):
        by_day.setdefault(change.date_to, []).append(change)
    return [issue_for(day.isoformat(), by_day[day]) for day in sorted(by_day)]


def run_gh(args):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8")


def open_pending_issues(repo, runner=run_gh, log=print):
    """Abre uma issue por dia com eventos por registar, sem duplicar as que já existem."""
    created = []
    for issue in pending_issues(repo):
        try:
            listed = runner(["gh", "issue", "list", "--state", "all", "--search", f'"{issue.title}" in:title',
                             "--json", "title", "--limit", "100"])
        except FileNotFoundError as exc:
            raise DumpError("O comando gh não está instalado: não é possível abrir issues.") from exc
        if listed.returncode != 0:
            raise DumpError(f"gh issue list falhou: {listed.stderr.strip()}")
        if issue.title in {item["title"] for item in json.loads(listed.stdout or "[]")}:
            log(f"Já existe uma issue com o título: {issue.title}")
            continue
        made = runner(["gh", "issue", "create", "--title", issue.title, "--body", issue.body])
        if made.returncode != 0:
            raise DumpError(f"gh issue create falhou: {made.stderr.strip()}")
        log(f"Issue aberta: {issue.title}")
        created.append(issue.title)
    return created
