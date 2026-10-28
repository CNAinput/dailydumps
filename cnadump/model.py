"""Tipos de dados partilhados."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

ASSET_TYPES = ("company", "asset")


@dataclass(frozen=True)
class Tick:
    ts: datetime
    code: str
    asset_type: str
    price: Decimal

    @property
    def key(self):
        return (self.code, self.asset_type)


@dataclass(frozen=True)
class Instrument:
    code: str
    name: str
    asset_type: str
    is_index: bool
    owner_company_code: Optional[str]
    price: Decimal
    shares_total: int
    created_on: Optional[date]

    @property
    def key(self):
        return (self.code, self.asset_type)
