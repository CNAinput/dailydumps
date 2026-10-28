"""Validação dos ticks de um dia: erros duros e avisos."""

from collections import defaultdict
from datetime import timedelta

from .fmt import to_decimal
from .model import ASSET_TYPES, Tick
from .timeutil import LISBON, UTC, close_instant, open_instant, parse_timestamp

GAP_LIMIT = timedelta(hours=2)


class Findings:
    """Agrupa problemas iguais: guarda a contagem e alguns exemplos."""

    def __init__(self, label):
        self.label = label
        self.groups = {}

    def add(self, text, example):
        count, examples = self.groups.get(text, (0, []))
        if len(examples) < 3:
            examples.append(example)
        self.groups[text] = (count + 1, examples)

    def messages(self):
        return [
            f"{self.label}: {count} {text} (exemplos: {'; '.join(examples)})"
            for text, (count, examples) in self.groups.items()
        ]


def build_ticks(rows, start, end, day):
    """Converte as linhas em ticks e devolve (ticks ordenados, erros duros, guild_ids vistos)."""
    findings = Findings(str(day))
    ticks, guilds, seen = [], set(), set()
    for number, row in enumerate(rows, start=1):
        try:
            ts = parse_timestamp(row["timestamp"])
            code = row["code"]
            asset_type = row["asset_type"]
            price = to_decimal(row["price"])
        except (KeyError, ValueError, TypeError) as exc:
            findings.add("linhas ilegíveis", f"linha {number} ({exc})")
            continue
        if not isinstance(code, str) or not code.strip() or code != code.strip():
            findings.add("códigos inválidos", f"linha {number}")
            continue
        if asset_type not in ASSET_TYPES:
            findings.add("tipos de ativo desconhecidos", f"{code} tipo {asset_type!r}")
            continue
        label = f"{code} {row['timestamp']}"
        if not start <= ts < end:
            findings.add("timestamps fora da janela do dia", label)
            continue
        if not price.is_finite() or price <= 0:
            findings.add("preços não finitos ou não positivos", f"{label} preço {price}")
            continue
        key = (ts, code, asset_type)
        if key in seen:
            findings.add("ticks duplicados", label)
            continue
        seen.add(key)
        if "guild_id" in row:
            guilds.add(row["guild_id"])
        ticks.append(Tick(ts=ts, code=code, asset_type=asset_type, price=price))
    errors = findings.messages()
    if not ticks:
        errors.append(f"{day}: dia sem nenhum tick")
    ticks.sort(key=lambda t: (t.ts, t.code, t.asset_type))
    return ticks, errors, guilds


def check_current_prices(day, ticks, instruments):
    """O último tick de cada instrumento tem de igualar o preço atual (só com o mercado fechado)."""
    last = {}
    for tick in ticks:
        last[tick.key] = tick.price
    errors = []
    for inst in sorted(instruments, key=lambda i: (i.code, i.asset_type)):
        price = last.get(inst.key)
        if price is not None and price != inst.price:
            errors.append(
                f"{day}: o último tick de {inst.code} ({inst.asset_type}) é {price} mas o preço atual é {inst.price}"
            )
    return errors


def gap_warnings(day, ticks, partial, born=frozenset()):
    """Avisa quando um instrumento fica mais de 2 horas sem ticks entre as 11:00 e as 23:00.

    Nos dias parciais e nos instrumentos criados nesse dia (`born`) o início não conta.
    """
    open_ts = open_instant(day).astimezone(UTC)
    close_ts = close_instant(day).astimezone(UTC)
    series = defaultdict(list)
    for tick in ticks:
        series[tick.key].append(min(max(tick.ts, open_ts), close_ts))
    warnings = []
    for (code, asset_type), times in sorted(series.items()):
        starts_late = partial or (code, asset_type) in born
        points = ([] if starts_late else [open_ts]) + sorted(times) + [close_ts]
        gap, begin, finish = max((b - a, a, b) for a, b in zip(points, points[1:]))
        if gap > GAP_LIMIT:
            hours, rest = divmod(int(gap.total_seconds()) // 60, 60)
            warnings.append(
                f"{day}: {code} ({asset_type}) ficou {hours}h{rest:02d} sem ticks, "
                f"entre {begin.astimezone(LISBON):%H:%M} e {finish.astimezone(LISBON):%H:%M} (hora de Lisboa)"
            )
    return warnings


def missing_instrument_warnings(day, ticks, instruments):
    """Avisa dos instrumentos que já existiam nesse dia e não têm nenhum tick."""
    seen = {t.key for t in ticks}
    return [
        f"{day}: {inst.code} ({inst.asset_type}) sem ticks neste dia"
        for inst in sorted(instruments, key=lambda i: (i.code, i.asset_type))
        if inst.key not in seen and (inst.created_on is None or inst.created_on <= day)
    ]
