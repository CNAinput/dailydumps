"""Mundo falso coerente: instrumentos, ticks por hora local de Lisboa e agregados."""

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from cnadump.client import PostgrestClient
from cnadump.pipeline import Generator
from cnadump.source import Source
from cnadump.store import Repo
from cnadump.timeutil import LISBON, UTC
from tests.fakes import FakePostgrest

GUILD = 962482316872151100
D25, D26, D27 = date(2026, 10, 25), date(2026, 10, 26), date(2026, 10, 27)


def local(day, hour, minute=0, second=0, micro=0):
    """Instante UTC de uma hora local de Lisboa."""
    return datetime(day.year, day.month, day.day, hour, minute, second, micro, tzinfo=LISBON).astimezone(UTC)


def lisbon_now(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=LISBON)


class World:
    def __init__(self):
        self.price_history = []
        self.companies = []
        self.assets = []
        self.dividends = []
        self.server_taxes = [{
            "id": 1, "guild_id": GUILD, "juros": 1, "income": 12, "iva": 7,
            "last_changed": datetime(2026, 8, 25, 9, 59, 51, tzinfo=timezone.utc),
        }]
        self.held = {}
        self.base = {}
        self._id = 0

    def add_company(self, code, name, price, shares_total=100000, created=date(2026, 8, 1)):
        self.companies.append({
            "code": code, "guild_id": GUILD, "name": name, "account_id": "SEGREDO-CONTA-1",
            "shares_total": shares_total, "current_price": price, "creation_date": local(created, 12),
            "majority_owner": "SEGREDO-UTILIZADOR-1",
        })
        self.base[(code, "company")] = price

    def add_asset(self, code, name, price, owner="P&PEP", is_index=False, shares_total=100000, created=date(2026, 8, 1)):
        self.assets.append({
            "code": code, "guild_id": GUILD, "name": name, "account_id": "SEGREDO-CONTA-2",
            "shares_total": shares_total, "current_price": price, "creation_date": local(created, 12),
            "owner_company_code": owner, "is_index": is_index, "majority_owner": None,
        })
        self.base[(code, "asset")] = price

    def add_dividend(self, code, asset_type, percentage, days, last, nxt):
        self.dividends.append({
            "id": len(self.dividends) + 1, "guild_id": GUILD, "account_id": "SEGREDO-CONTA-3",
            "percentage": percentage, "distribution_days": days, "last_distribution": last,
            "next_distribution": nxt, "code": code, "asset_type": asset_type,
        })

    def standard(self):
        self.add_company("NEWTE", "NovaTecnologia,S.A.", 11.32, shares_total=300000)
        self.add_company("ACHIP", "AtivosDoChip,S.A.", 5.29, shares_total=125000)
        self.add_company("P&PEP", "Padrões&Pobres,E.P.", 11.27, shares_total=1000)
        self.add_asset("ACSCP", "Sporting", 2.78)
        self.add_asset("P&P10", "Índice P&P10", 64.4, is_index=True, shares_total=100000000)
        self.add_asset("PPA10", "Índice P&P Ativos 10", 204.42, is_index=True, shares_total=100000000)
        self.held = {
            ("NEWTE", "company"): 147299, ("ACHIP", "company"): 34119, ("P&PEP", "company"): 1000,
            ("ACSCP", "asset"): 49511, ("P&P10", "asset"): 2638, ("PPA10", "asset"): 81,
        }
        return self

    def instruments(self):
        return [(r["code"], "company") for r in self.companies] + [(r["code"], "asset") for r in self.assets]

    def tick_utc(self, ts, code, asset_type, price):
        self._id += 1
        self.price_history.append({
            "id": self._id, "guild_id": GUILD, "code": code, "asset_type": asset_type,
            "price": price, "timestamp": ts,
        })

    def tick(self, day, hour, minute, code, asset_type, price, second=5):
        self.tick_utc(local(day, hour, minute, second), code, asset_type, price)

    def fill_day(self, day, step=120, skip=()):
        for index, (code, asset_type) in enumerate(self.instruments()):
            if (code, asset_type) in skip:
                continue
            base = self.base[(code, asset_type)]
            for k, minute in enumerate(range(11 * 60, 23 * 60, step)):
                price = round(base + ((k * 7 + index + day.toordinal()) % 11) * 0.01, 2)
                self.tick(day, minute // 60, minute % 60, code, asset_type, price)

    def sync_prices(self, until=None):
        """O preço atual passa a ser o do último tick (anterior a `until`) de cada instrumento."""
        last = {}
        for row in sorted(self.price_history, key=lambda r: (r["timestamp"], r["id"])):
            if until is None or row["timestamp"] < until:
                last[(row["code"], row["asset_type"])] = row["price"]
        for row in self.companies:
            row["current_price"] = last.get((row["code"], "company"), row["current_price"])
        for row in self.assets:
            row["current_price"] = last.get((row["code"], "asset"), row["current_price"])

    def apply_split(self, code, asset_type, factor):
        """Como o bot: reescreve todo o histórico, o preço atual e as shares."""
        for row in self.price_history:
            if (row["code"], row["asset_type"]) == (code, asset_type):
                row["price"] = round(row["price"] / factor, 2)
        for row in (self.companies if asset_type == "company" else self.assets):
            if row["code"] == code:
                row["current_price"] = round(row["current_price"] / factor, 2)
                row["shares_total"] *= factor
        if (code, asset_type) in self.held:
            self.held[(code, asset_type)] *= factor

    def transport(self):
        return FakePostgrest(
            tables={
                "price_history": self.price_history, "companies": self.companies, "assets": self.assets,
                "dividends": self.dividends, "server_taxes": self.server_taxes,
            },
            rpcs={"rpc_get_market_aggregates": lambda: [
                {"code": c, "asset_type": t, "held_shares": n} for (c, t), n in self.held.items()
            ]},
        )


class PipelineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = Repo(self.root)
        self.world = World()
        self.logs = []
        self.fake = None

    def generator(self, now):
        self.fake = self.world.transport()
        client = PostgrestClient("https://exemplo.supabase.co", "chave", transport=self.fake, sleep=lambda s: None)
        return Generator(self.repo, Source(client), now, log=self.logs.append)

    def tree(self):
        return {
            p.relative_to(self.root).as_posix(): p.read_bytes()
            for p in sorted(self.root.rglob("*")) if p.is_file()
        }


WEB_STUB = {
    "index.html": "<!doctype html>\n<title>Site</title>\n",
    "css/site.css": "body { margin: 0; }\n",
    "js/main.js": "export {};\n",
}


def write_web(root, extra=None):
    """Escreve um site mínimo em `root/web` e devolve os caminhos relativos escritos."""
    files = {**WEB_STUB, **(extra or {})}
    for rel, text in files.items():
        path = Path(root) / "web" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return sorted(files)


NOW = lisbon_now(D27, 23, 17)


class StandardWorldCase(PipelineCase):
    """Três dias (25 a 27 de outubro) com seis instrumentos, prontos a arquivar às 23:17 de 27."""

    def setUp(self):
        super().setUp()
        self.world.standard()
        for day in (D25, D26, D27):
            self.world.fill_day(day)
        self.world.sync_prices()
