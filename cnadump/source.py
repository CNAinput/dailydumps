"""Leitura dos dados públicos: só GET e a RPC de agregados."""

from .client import parse_json
from .errors import ValidationError
from .fmt import to_decimal
from .model import Instrument
from .timeutil import format_utc, format_utc_seconds, lisbon_date, parse_timestamp

PRICE_COLUMNS = "code,asset_type,price,timestamp,guild_id"
COMPANY_COLUMNS = "code,name,current_price,shares_total,creation_date"
ASSET_COLUMNS = "code,name,current_price,shares_total,is_index,owner_company_code,creation_date"
DIVIDEND_COLUMNS = "code,asset_type,percentage,distribution_days,next_distribution,last_distribution"
TAX_COLUMNS = "juros,income,iva,last_changed"
PAYOUT_COLUMNS = "code,asset_type,paid_at,percentage,pool,total_paid,total_shares,origin,payments,guild_id"


def _instrument(row, asset_type):
    try:
        price = to_decimal(row["current_price"])
        if not price.is_finite():
            raise ValueError("preço atual não finito")
        created = row.get("creation_date")
        return Instrument(
            code=str(row["code"]),
            name=str(row["name"]),
            asset_type=asset_type,
            is_index=bool(row.get("is_index", False)),
            owner_company_code=row.get("owner_company_code"),
            price=price,
            shares_total=int(row["shares_total"]),
            created_on=lisbon_date(parse_timestamp(created)) if created else None,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationError(f"Instrumento ilegível em {asset_type}: {exc}") from exc


def _stamp(value):
    return format_utc(parse_timestamp(value)) if value else None


class Source:
    def __init__(self, client):
        self.client = client

    def first_day(self):
        """Primeiro dia civil de Lisboa com ticks, ou None se a tabela estiver vazia."""
        reply = self.client.request(
            "GET", "/rest/v1/price_history", [("select", "timestamp"), ("order", "timestamp.asc"), ("limit", "1")]
        )
        rows = parse_json(reply.body)
        if not rows:
            return None
        return lisbon_date(parse_timestamp(rows[0]["timestamp"]))

    def price_rows(self, start, end):
        """Linhas brutas de [start, end), em ordem determinística e com a contagem conferida."""
        params = [
            ("select", PRICE_COLUMNS),
            ("timestamp", f"gte.{format_utc_seconds(start)}"),
            ("timestamp", f"lt.{format_utc_seconds(end)}"),
            ("order", "timestamp.asc,id.asc"),
        ]
        return self.client.select("price_history", params)

    def instruments(self):
        companies = self.client.select("companies", [("select", COMPANY_COLUMNS), ("order", "code.asc")])
        assets = self.client.select("assets", [("select", ASSET_COLUMNS), ("order", "code.asc")])
        return [_instrument(r, "company") for r in companies] + [_instrument(r, "asset") for r in assets]

    def held_shares(self):
        """Shares detidas por instrumento. Os que não aparecem têm zero."""
        held = {}
        for row in self.client.rpc("rpc_get_market_aggregates"):
            try:
                shares = int(row["held_shares"])
                if shares < 0:
                    raise ValueError("shares negativas")
                held[(str(row["code"]), str(row["asset_type"]))] = shares
            except (KeyError, ValueError, TypeError) as exc:
                raise ValidationError(f"Agregado de shares ilegível: {exc}") from exc
        return held

    def dividend_policies(self):
        rows = self.client.select("dividends", [("select", DIVIDEND_COLUMNS), ("order", "code.asc,asset_type.asc")])
        policies = []
        try:
            for row in rows:
                policies.append({
                    "code": str(row["code"]),
                    "asset_type": str(row["asset_type"]),
                    "percentage": to_decimal(row["percentage"]),
                    "distribution_days": int(row["distribution_days"]),
                    "next_distribution": _stamp(row.get("next_distribution")),
                    "last_distribution": _stamp(row.get("last_distribution")),
                })
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationError(f"Política de dividendos ilegível: {exc}") from exc
        return policies

    def dividend_payouts(self, start, end):
        """Pagamentos de dividendos pagos em [start, end), em ordem determinística."""
        params = [
            ("select", PAYOUT_COLUMNS),
            ("paid_at", f"gte.{format_utc_seconds(start)}"),
            ("paid_at", f"lt.{format_utc_seconds(end)}"),
            ("order", "paid_at.asc,id.asc"),
        ]
        return self.client.select("dividend_payouts", params)

    def taxes(self):
        rows = self.client.select("server_taxes", [("select", TAX_COLUMNS)])
        if not rows:
            return None
        if len(rows) > 1:
            raise ValidationError("server_taxes devolveu mais de uma linha: os impostos em vigor são ambíguos.")
        row = rows[0]
        try:
            return {
                "loan_interest_pct": None if row["juros"] is None else to_decimal(row["juros"]),
                "income_tax_pct": None if row["income"] is None else to_decimal(row["income"]),
                "vat_pct": None if row["iva"] is None else to_decimal(row["iva"]),
                "last_changed": _stamp(row.get("last_changed")),
            }
        except (KeyError, ValueError) as exc:
            raise ValidationError(f"Impostos ilegíveis: {exc}") from exc
