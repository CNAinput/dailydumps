"""Verificação de integridade do repositório e guarda dos pull requests."""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from . import events as ev
from .fmt import csv_bytes, json_bytes, read_csv
from .model import Tick
from .ohlc import OHLC_HEADER, PRICES_HEADER, compute_ohlc
from .payouts import build_payouts, covers, within_retention
from .slugs import RESERVED, SLUG_RE
from .store import (
    DIVIDENDS, EVENTS, INSTRUMENTS, MANIFEST, OHLC, OHLC_ADJUSTED, STATUS, SUMS, TAXES, Transaction, sha256_hex,
    sums_text,
)
from .timeutil import day_window, parse_date, parse_timestamp

PROTECTED_PREFIXES = ("prices/", "summary/", "snapshots/", "daily/", "dividend_payouts/")
PROTECTED_FILES = frozenset({MANIFEST, SUMS, STATUS, INSTRUMENTS, DIVIDENDS, TAXES})
FORBIDDEN_KEYS = re.compile(r"account|user|discord|majority", re.IGNORECASE)


@dataclass
class VerifyReport:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def protected_changes(paths):
    """Caminhos alterados que só o workflow pode escrever."""
    found = []
    for raw in paths:
        path = raw.strip().replace("\\", "/")
        if path and (path.startswith(PROTECTED_PREFIXES) or path in PROTECTED_FILES):
            found.append(path)
    return sorted(set(found))


def _forbidden_keys(value, where, errors):
    if isinstance(value, dict):
        for key, item in value.items():
            if FORBIDDEN_KEYS.search(key):
                errors.append(f"{where}: a chave {key!r} sugere um identificador de conta ou utilizador")
            _forbidden_keys(item, where, errors)
    elif isinstance(value, list):
        for item in value:
            _forbidden_keys(item, where, errors)


def _check_prices_file(repo, day, entry, errors):
    rel = repo.prices_rel(day)
    data = repo.read(rel)
    if data is None:
        errors.append(f"{rel}: o manifesto lista o dia mas o ficheiro não existe")
        return None
    if sha256_hex(data) != entry.get("sha256"):
        errors.append(f"{rel}: o sha256 não corresponde ao manifesto")
    if b"\r" in data:
        errors.append(f"{rel}: tem fins de linha CRLF")
    header, rows = read_csv(data)
    if header != PRICES_HEADER:
        errors.append(f"{rel}: cabeçalho inválido")
        return None
    if len(rows) != entry.get("rows"):
        errors.append(f"{rel}: {len(rows)} linhas mas o manifesto indica {entry.get('rows')}")
    start, end = day_window(day)
    ticks, previous = [], None
    for number, row in enumerate(rows, start=2):
        try:
            if len(row) != 4 or row[2] not in ("company", "asset"):
                raise ValueError("linha inválida")
            ts = parse_timestamp(row[0])
            price = Decimal(row[3])
            if not price.is_finite() or price <= 0:
                raise ValueError("preço inválido")
        except (ValueError, ArithmeticError) as exc:
            errors.append(f"{rel}, linha {number}: {exc}")
            return None
        if not start <= ts < end:
            errors.append(f"{rel}, linha {number}: timestamp fora da janela do dia")
        order = (row[0], row[1], row[2])
        if previous is not None and order <= previous:
            errors.append(f"{rel}, linha {number}: linhas fora de ordem ou duplicadas")
        previous = order
        ticks.append(Tick(ts, row[1], row[2], price))
    return ticks


def _generated_in_retention(day, entry):
    """True se o dia foi gerado enquanto o bot ainda guardava os seus pagamentos."""
    try:
        return within_retention(day, parse_timestamp(entry["generated_at"]))
    except (KeyError, ValueError, TypeError):
        return True


def _check_payouts(repo, day, entry, report):
    """Ficheiro de pagamentos do dia contra o manifesto e contra as regras do arquivo."""
    rel = repo.payouts_rel(day)
    data = repo.read(rel)
    count = entry.get("dividend_payouts")
    if count is None:
        if data is not None:
            report.errors.append(f"{rel}: o manifesto não indica pagamentos para este dia")
        elif covers(day) and _generated_in_retention(day, entry):
            report.warnings.append(f"manifest.json, {day}: sem registo de pagamentos de dividendos; regenera o dia")
        return
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        report.errors.append(f"manifest.json, {day}: dividend_payouts inválido")
        return
    if count == 0:
        if data is not None:
            report.errors.append(f"{rel}: existe mas o manifesto indica 0 pagamentos")
        return
    if data is None:
        report.errors.append(f"{rel}: o manifesto indica {count} pagamentos mas o ficheiro não existe")
        return
    if b"\r" in data:
        report.errors.append(f"{rel}: tem fins de linha CRLF")
    try:
        stored = repo.read_json(rel, exact=True)
        payouts = stored["payouts"]
    except (ValueError, KeyError, TypeError):
        report.errors.append(f"{rel}: JSON ilegível ou sem a lista payouts")
        return
    start, end = day_window(day)
    document, found, _, _ = build_payouts(day, payouts if isinstance(payouts, list) else [], start, end)
    if found:
        report.errors.extend(found)
    elif document is None or json_bytes(document) != data:
        report.errors.append(f"{rel}: não corresponde ao que as regras do arquivo geram a partir dos seus pagamentos")
    elif len(document["payouts"]) != count:
        report.errors.append(f"{rel}: tem {len(document['payouts'])} pagamentos mas o manifesto indica {count}")


def verify_repo(repo):
    report = VerifyReport()
    errors, warnings = report.errors, report.warnings
    manifest = repo.read_json(MANIFEST)
    if manifest is None:
        if repo.price_days():
            errors.append("manifest.json não existe mas há ficheiros de preços")
        return report
    days = {}
    for text, entry in manifest.get("days", {}).items():
        try:
            days[parse_date(text)] = entry
        except ValueError:
            errors.append(f"manifest.json: data inválida {text!r}")
    if set(days) != repo.price_days():
        extra = sorted(str(d) for d in repo.price_days() - set(days))
        missing = sorted(str(d) for d in set(days) - repo.price_days())
        errors.append(f"manifest.json e prices/ não coincidem (sem manifesto: {extra}; sem ficheiro: {missing})")
    all_rows, snapshots = [], set(repo.snapshot_days())
    for day in sorted(days):
        entry = days[day]
        if entry.get("source") not in ("daily", "backfill") or not isinstance(entry.get("partial"), bool):
            errors.append(f"manifest.json, {day}: source ou partial inválidos")
        ticks = _check_prices_file(repo, day, entry, errors)
        if ticks is not None:
            all_rows += compute_ohlc(day, ticks)
        _check_payouts(repo, day, entry, report)
        if (entry.get("source") == "daily") != (day in snapshots):
            errors.append(f"{day}: o snapshot só deve existir nos dias com source daily")
        summary = repo.read_json(repo.summary_rel(day))
        if summary is None:
            errors.append(f"{repo.summary_rel(day)}: em falta")
        elif summary.get("market_cap_available") != (day in snapshots):
            errors.append(f"{repo.summary_rel(day)}: market_cap_available não corresponde à existência do snapshot")
    for day in snapshots - set(days):
        errors.append(f"{repo.snapshot_rel(day)}: snapshot sem dia no manifesto")
    for day in repo.payout_days() - set(days):
        errors.append(f"{repo.payouts_rel(day)}: pagamentos sem dia no manifesto")

    ohlc = repo.read(OHLC)
    if all_rows or ohlc is not None:
        if ohlc != csv_bytes(OHLC_HEADER, all_rows):
            errors.append(f"{OHLC}: não corresponde aos ficheiros de preços")

    data = repo.read(EVENTS)
    events, events_ok = [], True
    if data is not None:
        events, found = ev.parse_events(data)
        errors += found
        events_ok = not found
    if events_ok and all_rows:
        expected = csv_bytes(OHLC_HEADER, ev.adjust_ohlc(all_rows, events, ev.generation_times(manifest)))
        if repo.read(OHLC_ADJUSTED) != expected:
            warnings.append(f"{OHLC_ADJUSTED}: desatualizado em relação ao events.csv; o workflow regenera-o")

    registry = repo.read_json(INSTRUMENTS)
    if registry is not None:
        slugs = [i.get("slug", "") for i in registry.get("instruments", [])]
        if len(set(slugs)) != len(slugs):
            errors.append(f"{INSTRUMENTS}: slugs repetidos")
        for slug in slugs:
            if not SLUG_RE.match(slug) or slug in RESERVED:
                errors.append(f"{INSTRUMENTS}: slug inseguro {slug!r}")

    exported = [DIVIDENDS, TAXES, INSTRUMENTS]
    exported += [repo.snapshot_rel(d) for d in sorted(snapshots)] + [repo.summary_rel(d) for d in sorted(days)]
    exported += [repo.payouts_rel(d) for d in sorted(repo.payout_days())]
    for rel in exported:
        try:
            content = repo.read_json(rel)
        except ValueError:
            continue  # já reportado acima
        if content is not None:
            _forbidden_keys(content, rel, errors)

    status = repo.read_json(STATUS)
    if days and status is not None:
        last = max(days)
        if status.get("last_date") != last.isoformat():
            errors.append(f"{STATUS}: last_date devia ser {last}")
        elif status.get("ticks") != days[last].get("rows"):
            errors.append(f"{STATUS}: ticks não corresponde ao último dia")
    elif days:
        errors.append(f"{STATUS}: em falta")

    sums = repo.read(SUMS)
    if sums is None:
        if days:
            errors.append(f"{SUMS}: em falta")
    else:
        if sums != sums_text(Transaction(repo)):
            errors.append(f"{SUMS}: não corresponde aos ficheiros gerados")
    return report
