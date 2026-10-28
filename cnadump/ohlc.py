"""OHLC diário a partir dos ticks."""

from .fmt import plain
from .timeutil import format_utc

PRICES_HEADER = ["ts_utc", "code", "asset_type", "price"]
OHLC_HEADER = ["date", "code", "asset_type", "open", "high", "low", "close", "ticks"]


def prices_rows(ticks):
    ordered = sorted(ticks, key=lambda t: (t.ts, t.code, t.asset_type))
    return [[format_utc(t.ts), t.code, t.asset_type, plain(t.price)] for t in ordered]


def compute_ohlc(day, ticks):
    """Uma linha por instrumento. Abertura é o primeiro tick do dia e fecho o último."""
    series = {}
    for tick in sorted(ticks, key=lambda t: (t.ts, t.code, t.asset_type)):
        series.setdefault(tick.key, []).append(tick.price)
    rows = []
    for (code, asset_type), prices in sorted(series.items()):
        rows.append([
            day.isoformat(), code, asset_type,
            plain(prices[0]), plain(max(prices)), plain(min(prices)), plain(prices[-1]), str(len(prices)),
        ])
    return rows


def merge_ohlc(existing, new_by_day):
    """Substitui as linhas dos dias novos e mantém as restantes em ordem (data, código, tipo)."""
    replaced = {day.isoformat() for day in new_by_day}
    rows = [list(row) for row in existing if row[0] not in replaced]
    for day_rows in new_by_day.values():
        rows.extend(list(row) for row in day_rows)
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return rows
