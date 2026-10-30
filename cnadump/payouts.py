"""Pagamentos de dividendos de um dia: validação e documento do ficheiro diário."""

import re
from datetime import date, timedelta
from decimal import Decimal

from .fmt import quantize, to_decimal
from .store import SCHEMA_VERSION
from .timeutil import format_utc_seconds, lisbon_date, parse_timestamp

# Primeiro dia com pagamentos registados.
FIRST_DAY = date(2026, 10, 30)
# Dias que o bot guarda os pagamentos (igual no bot).
RETENTION_DAYS = 14
ASSET_TYPES = ("company", "asset")
KINDS = ("pessoal", "empresa", "estado")
ORIGINS = ("bot", "reconstruction")
UNKNOWN = "Desconhecido"
# Parece um id do Discord.
_ID_LIKE = re.compile(r"\d{15,}")


def covers(day):
    """Dias com pagamentos registados na base de dados."""
    return day >= FIRST_DAY


def within_retention(day, now):
    """Pagamentos do dia ainda não apagados pelo bot."""
    return lisbon_date(now) - day < timedelta(days=RETENTION_DAYS)


def tracked(day, now):
    """Dias cujos pagamentos o arquivo lê e regista."""
    return covers(day) and within_retention(day, now)


def _money(value, name):
    try:
        number = to_decimal(value)
    except ValueError:
        raise ValueError(f"{name} inválido ({value!r})") from None
    if not number.is_finite() or number < 0:
        raise ValueError(f"{name} inválido ({value!r})")
    if number != quantize(number, 2):
        raise ValueError(f"{name} com mais de 2 casas decimais ({value!r})")
    return quantize(number, 2)


def _whole(value, name, minimum):
    try:
        number = to_decimal(value)
    except ValueError:
        raise ValueError(f"{name} inválido ({value!r})") from None
    if not number.is_finite() or number != number.to_integral_value() or number < minimum:
        raise ValueError(f"{name} inválido ({value!r})")
    return int(number)


def _label(value, where, notes):
    """Rótulo público, sem ids."""
    text = value.strip() if isinstance(value, str) else ""
    if not text or _ID_LIKE.search(text):
        notes.append(f"{where}: rótulo de beneficiário vazio ou com aspeto de identificador, passa a {UNKNOWN!r}.")
        return UNKNOWN
    return text


def _payment(item, where, notes):
    if not isinstance(item, dict):
        raise ValueError("pagamento que não é um objeto")
    kind = item["kind"]
    if kind not in KINDS:
        raise ValueError(f"kind desconhecido ({kind!r})")
    amount = _money(item["amount"], "amount")
    if amount == 0:
        raise ValueError("amount nulo")
    return {
        "beneficiary": _label(item["beneficiary"], where, notes),
        "kind": kind,
        "shares": _whole(item["shares"], "shares", 1),
        "amount": amount,
    }


def _payout(row, where, start, end, notes):
    code = row["code"]
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code inválido")
    asset_type = row["asset_type"]
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"asset_type desconhecido ({asset_type!r})")
    origin = row["origin"]
    if origin not in ORIGINS:
        raise ValueError(f"origin desconhecido ({origin!r})")
    paid_at = parse_timestamp(row["paid_at"])
    if not start <= paid_at < end:
        raise ValueError("paid_at fora da janela do dia")
    percentage = to_decimal(row["percentage"])
    if not percentage.is_finite() or percentage < 0:
        raise ValueError(f"percentage inválido ({row['percentage']!r})")
    pool = _money(row["pool"], "pool")
    total_paid = _money(row["total_paid"], "total_paid")
    total_shares = _whole(row["total_shares"], "total_shares", 1)
    raw = row["payments"]
    if not isinstance(raw, list) or not raw:
        raise ValueError("payments vazio ou inválido")
    payments = [_payment(item, where, notes) for item in raw]
    payments.sort(key=lambda p: (-p["amount"], p["beneficiary"], p["kind"], p["shares"]))
    paid_sum = sum((p["amount"] for p in payments), Decimal(0))
    if paid_sum != total_paid:
        raise ValueError(f"a soma dos pagamentos ({paid_sum}) difere de total_paid ({total_paid})")
    if sum(p["shares"] for p in payments) > total_shares:
        raise ValueError("as shares dos beneficiários excedem total_shares")
    return paid_at, {
        "code": code,
        "asset_type": asset_type,
        "paid_at": format_utc_seconds(paid_at),
        "percentage": percentage,
        "pool": pool,
        "total_paid": total_paid,
        "beneficiaries": len(payments),
        "average": quantize(total_paid / len(payments), 2),
        "total_shares": total_shares,
        "origin": origin,
        "payments": payments,
    }


def build_payouts(day, rows, start, end):
    """Documento do dia (ou None) e erros, avisos e servidores."""
    errors, notes, guilds, found = [], [], set(), []
    for number, row in enumerate(rows, start=1):
        where = f"{day}: dividend_payouts, linha {number}"
        try:
            if "guild_id" in row:
                guilds.add(row["guild_id"])
            found.append(_payout(row, where, start, end, notes))
        except KeyError as exc:
            errors.append(f"{where}: falta o campo {exc.args[0]}")
        except (ValueError, TypeError, ArithmeticError) as exc:
            errors.append(f"{where}: {exc}")
    if errors or not found:
        return None, errors, notes, guilds
    found.sort(key=lambda item: (item[0], item[1]["code"], item[1]["asset_type"]))
    document = {"schema_version": SCHEMA_VERSION, "date": day.isoformat(), "payouts": [p for _, p in found]}
    return document, errors, notes, guilds
