"""Resumo do fecho do dia: índices, maior subida e descida e maiores empresas."""

from decimal import Decimal

from .fmt import quantize

SCHEMA_VERSION = 1
MOVE_THRESHOLD = Decimal("0.05")
TOP_COUNT = 3


def _percent(first, last):
    return (last - first) / first * 100


def _mover(key, name, first, last, change):
    return {
        "code": key[0],
        "asset_type": key[1],
        "name": name,
        "open": first,
        "close": last,
        "change_pct": quantize(change, 2),
    }


def build_summary(day, ticks, meta, snapshot):
    """`meta` mapeia (código, tipo) para o instrumento atual. `snapshot` é None sem capitalização."""
    first, last = {}, {}
    for tick in sorted(ticks, key=lambda t: (t.ts, t.code, t.asset_type)):
        first.setdefault(tick.key, tick.price)
        last[tick.key] = tick.price

    def name_of(key):
        inst = meta.get(key)
        return inst.name if inst else None

    indices, movers = [], []
    for key in sorted(first):
        change = _percent(first[key], last[key])
        inst = meta.get(key)
        if inst is not None and inst.is_index:
            indices.append({
                "code": key[0],
                "name": inst.name,
                "open": first[key],
                "close": last[key],
                "change_pct": quantize(change, 2),
            })
        else:
            movers.append((key, change))

    riser = faller = None
    if movers:
        top = min(movers, key=lambda m: (-m[1], m[0]))
        bottom = min(movers, key=lambda m: (m[1], m[0]))
        if top[1] > MOVE_THRESHOLD:
            riser = _mover(top[0], name_of(top[0]), first[top[0]], last[top[0]], top[1])
        if bottom[1] < -MOVE_THRESHOLD and bottom[0] != top[0]:
            faller = _mover(bottom[0], name_of(bottom[0]), first[bottom[0]], last[bottom[0]], bottom[1])

    summary = {
        "schema_version": SCHEMA_VERSION,
        "date": day.isoformat(),
        "market_cap_available": snapshot is not None,
        "indices": indices,
        "biggest_riser": riser,
        "biggest_faller": faller,
        "calm_day": riser is None and faller is None,
        "top_market_cap": None,
        "total_market_cap": None,
        "companies_count": None,
    }
    if snapshot is not None:
        companies = [i for i in snapshot["instruments"] if i["asset_type"] == "company" and not i["is_index"]]
        ranked = sorted((c for c in companies if c["market_cap"] > 0), key=lambda c: (-c["market_cap"], c["code"]))
        summary["top_market_cap"] = [
            {"rank": n, "code": c["code"], "name": c["name"], "market_cap": c["market_cap"]}
            for n, c in enumerate(ranked[:TOP_COUNT], start=1)
        ]
        summary["total_market_cap"] = quantize(sum((c["market_cap"] for c in companies), Decimal(0)), 2)
        summary["companies_count"] = len(companies)
    return summary
