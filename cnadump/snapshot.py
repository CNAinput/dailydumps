"""Estado do mercado no fecho e registo de instrumentos."""

from .fmt import quantize
from .slugs import assign_slugs
from .timeutil import format_utc_seconds

SCHEMA_VERSION = 1


def build_snapshot(day, snapshot_at, instruments, held):
    """Instantâneo no fecho. A capitalização usa as shares em circulação, nunca `shares_total`."""
    items = []
    for inst in sorted(instruments, key=lambda i: (i.code, i.asset_type)):
        circulating = held.get(inst.key, 0)
        items.append({
            "code": inst.code,
            "name": inst.name,
            "asset_type": inst.asset_type,
            "is_index": inst.is_index,
            "owner_company_code": inst.owner_company_code,
            "price": inst.price,
            "shares_total": inst.shares_total,
            "shares_in_circulation": circulating,
            "market_cap": quantize(inst.price * circulating, 2),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "date": day.isoformat(),
        "snapshot_at": format_utc_seconds(snapshot_at),
        "instruments": items,
    }


def build_registry(snapshot, previous=None):
    """Cópia do último instantâneo com o slug de cada instrumento."""
    old = {}
    if previous:
        old = {(i["code"], i["asset_type"]): i["slug"] for i in previous.get("instruments", []) if i.get("slug")}
    slugs = assign_slugs([(i["code"], i["asset_type"]) for i in snapshot["instruments"]], old)
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_date": snapshot["date"],
        "snapshot_at": snapshot["snapshot_at"],
        "instruments": [dict(i, slug=slugs[(i["code"], i["asset_type"])]) for i in snapshot["instruments"]],
    }
