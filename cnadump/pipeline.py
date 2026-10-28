"""Geração dos dias fechados: seleção, validação antes de escrever e escrita atómica."""

from dataclasses import dataclass, field
from datetime import timedelta

from . import events as ev
from .errors import ImmutabilityError, ValidationError
from .fmt import csv_bytes, json_bytes
from .ohlc import OHLC_HEADER, PRICES_HEADER, compute_ohlc, merge_ohlc, prices_rows
from .snapshot import build_registry, build_snapshot
from .store import (
    DIVIDENDS, EVENTS, INSTRUMENTS, MANIFEST, OHLC, OHLC_ADJUSTED, STATUS, SUMS, TAXES,
    SCHEMA_VERSION, Transaction, sha256_hex, status_bytes, sums_text,
)
from .summary import build_summary
from .timeutil import (
    RETENTION_DAYS, day_window, format_utc_seconds, last_closed_day, lisbon_date, may_be_cut_by_retention,
    open_instant,
)
from .validate import build_ticks, check_current_prices, gap_warnings, missing_instrument_warnings

EMPTY_DB = "A base de dados não devolveu nenhum tick (price_history vazio ou sem acesso)."


@dataclass
class RunResult:
    days: list = field(default_factory=list)
    ticks: int = 0
    warnings: list = field(default_factory=list)
    snapshot_day: object = None
    written: list = field(default_factory=list)


class Generator:
    def __init__(self, repo, source, now, log=print):
        self.repo = repo
        self.source = source
        self.now = now
        self.log = log

    def missing_days(self, existing, lower=None, use_horizon=True, forward_only=False):
        """Dias fechados sem ficheiro. Com `forward_only` começa no dia a seguir ao último arquivado."""
        last_closed = last_closed_day(self.now)
        if lower is not None:
            low = lower
            first = self.source.first_day()
            if first is None:
                raise ValidationError(EMPTY_DB)
            if first > low:
                self.log(f"A base de dados só tem ticks desde {first}; o início passa de {low} para {first}.")
                low = first
        elif existing:
            low = max(existing) + timedelta(days=1) if forward_only else min(existing)
        else:
            low = self.source.first_day()
            if low is None:
                raise ValidationError(EMPTY_DB)
        if use_horizon:
            low = max(low, lisbon_date(self.now) - timedelta(days=RETENTION_DAYS))
        days = []
        day = low
        while day <= last_closed:
            if day not in existing:
                days.append(day)
            day += timedelta(days=1)
        return days

    def run_day(self, only=None):
        last_closed = last_closed_day(self.now)
        existing = self.repo.price_days()
        if only is not None:
            if only > last_closed:
                raise ValidationError(f"O dia {only} ainda não fechou (o mercado fecha às 23:00 de Lisboa).")
            days = [only]
        else:
            days = self.missing_days(existing, forward_only=True)
        if not days:
            return self._nothing_to_do(last_closed)
        return self._generate(days, allow_snapshot=True, regenerate=False)

    def run_backfill(self, start=None):
        existing = self.repo.price_days()
        days = self.missing_days(existing, lower=start, use_horizon=False)
        if not days:
            return self._nothing_to_do(last_closed_day(self.now))
        return self._generate(days, allow_snapshot=False, regenerate=False)

    def run_regenerate(self, day):
        if day > last_closed_day(self.now):
            raise ValidationError(f"O dia {day} ainda não fechou (o mercado fecha às 23:00 de Lisboa).")
        if day not in self.repo.price_days():
            raise ValidationError(f"O dia {day} não tem ficheiro para regenerar. Usa day ou backfill para o criar.")
        return self._generate([day], allow_snapshot=False, regenerate=True)

    def _nothing_to_do(self, last_closed):
        self.log(f"Nada a fazer: os dias fechados até {last_closed} já estão arquivados.")
        return RunResult()

    def _generate(self, days, allow_snapshot, regenerate):
        repo, now = self.repo, self.now
        last_closed = last_closed_day(now)
        instruments = self.source.instruments()
        meta = {i.key: i for i in instruments}
        errors, warnings, guilds, data = [], [], set(), {}
        for day in days:
            start, end = day_window(day)
            ticks, found, found_guilds = build_ticks(self.source.price_rows(start, end), start, end, day)
            errors += found
            guilds |= found_guilds
            partial = may_be_cut_by_retention(day, now)
            born = {i.key for i in instruments if i.created_on == day}
            warnings += gap_warnings(day, ticks, partial, born) + missing_instrument_warnings(day, ticks, instruments)
            data[day] = (ticks, partial)
        if len(guilds) > 1:
            errors.append("price_history devolveu mais de um servidor (guild_id).")
        if errors:
            raise ValidationError(errors)

        todo, conflicts, files = [], [], {}
        for day in days:
            payload = csv_bytes(PRICES_HEADER, prices_rows(data[day][0]))
            old = repo.read(repo.prices_rel(day))
            files[day] = payload
            if old == payload:
                self.log(f"{day}: já arquivado e idêntico, nada a fazer.")
            elif old is not None and not regenerate:
                archived = old.count(b"\n") - 1
                conflicts.append(
                    f"{day}: {repo.prices_rel(day)} já existe com {archived} ticks e o recalculado tem "
                    f"{len(data[day][0])}. Os ficheiros de dias passados são imutáveis; "
                    "usa o subcomando regenerate para os substituir de forma explícita."
                )
            else:
                todo.append(day)
        if conflicts:
            raise ImmutabilityError(conflicts)
        result = RunResult(warnings=warnings)
        if not todo:
            return result

        at_close = last_closed in todo and now < open_instant(last_closed + timedelta(days=1))
        if at_close:
            problems = check_current_prices(last_closed, data[last_closed][0], instruments)
            if problems:
                raise ValidationError(problems)
        snapshot_day = last_closed if allow_snapshot and at_close else None
        snapshot = None
        if snapshot_day is not None:
            snapshot = build_snapshot(snapshot_day, now, instruments, self.source.held_shares())

        policies = self.source.dividend_policies()
        taxes = self.source.taxes()

        tx = Transaction(repo)
        manifest = repo.load_manifest()
        stamp = format_utc_seconds(now)
        new_rows = {}
        for day in todo:
            ticks, partial = data[day]
            old_entry = manifest["days"].get(day.isoformat())
            replaced = repo.read(repo.prices_rel(day)) is not None
            if replaced and old_entry:
                label = old_entry["source"]
            else:
                label = "daily" if day == snapshot_day else "backfill"
            entry = {
                "generated_at": stamp, "rows": len(ticks), "sha256": sha256_hex(files[day]),
                "source": label, "partial": partial,
            }
            if replaced and old_entry:
                entry["regenerations"] = list(old_entry.get("regenerations", [])) + [{
                    "at": stamp,
                    "previous_generated_at": old_entry["generated_at"],
                    "previous_sha256": old_entry["sha256"],
                    "previous_rows": old_entry["rows"],
                }]
            manifest["days"][day.isoformat()] = entry
            tx.put(repo.prices_rel(day), files[day])
            new_rows[day] = compute_ohlc(day, ticks)
            if day == snapshot_day:
                day_snapshot = snapshot
            else:
                day_snapshot = repo.read_json(repo.snapshot_rel(day), exact=True) if regenerate else None
            tx.put(repo.summary_rel(day), json_bytes(build_summary(day, ticks, meta, day_snapshot)))
            result.ticks += len(ticks)

        if snapshot is not None:
            tx.put(repo.snapshot_rel(snapshot_day), json_bytes(snapshot))
            tx.put(INSTRUMENTS, json_bytes(build_registry(snapshot, repo.read_json(INSTRUMENTS))))
        tx.put(DIVIDENDS, json_bytes({"schema_version": SCHEMA_VERSION, "policies": policies}))
        if taxes is not None:
            tx.put(TAXES, json_bytes(dict({"schema_version": SCHEMA_VERSION}, **taxes)))

        rows = merge_ohlc(repo.load_ohlc_rows(), new_rows)
        tx.put(OHLC, csv_bytes(OHLC_HEADER, rows))
        manifest["days"] = dict(sorted(manifest["days"].items()))
        adjusted = adjusted_bytes(repo, rows, manifest, result.warnings)
        if adjusted is not None:
            tx.put(OHLC_ADJUSTED, adjusted)
        tx.put(MANIFEST, json_bytes(manifest))
        tx.put(STATUS, status_bytes(manifest, rows, stamp, last_closed))
        tx.put(SUMS, sums_text(tx))

        result.written = tx.commit()
        result.days = todo
        result.snapshot_day = snapshot_day
        return result


def adjusted_bytes(repo, rows, manifest, warnings):
    """Conteúdo de daily/ohlc_adjusted.csv, ou None se o events.csv for inválido."""
    data = repo.read(EVENTS)
    events = []
    if data is not None:
        events, errors = ev.parse_events(data)
        if errors:
            warnings.append("events.csv inválido: daily/ohlc_adjusted.csv não foi atualizado.")
            warnings.extend(errors)
            return None
    adjusted = ev.adjust_ohlc(rows, events, ev.generation_times(manifest))
    return csv_bytes(OHLC_HEADER, adjusted)


def run_adjust(repo, log=print):
    """Regenera daily/ohlc_adjusted.csv a partir do events.csv. Devolve True se algo mudou."""
    rows = repo.load_ohlc_rows()
    if not rows:
        log("Nada a ajustar: ainda não há dados diários.")
        return False
    messages = []
    data = adjusted_bytes(repo, rows, repo.load_manifest(), messages)
    if data is None:
        raise ValidationError(messages)
    tx = Transaction(repo)
    tx.put(OHLC_ADJUSTED, data)
    tx.put(SUMS, sums_text(tx))
    changed = tx.commit()
    log("daily/ohlc_adjusted.csv atualizado." if changed else "daily/ohlc_adjusted.csv já está atualizado.")
    return bool(changed)
