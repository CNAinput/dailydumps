"""Repositório de dados: caminhos, escrita atómica, manifesto, somas e estado."""

import hashlib
import json
import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from .fmt import json_bytes, read_csv
from .ohlc import OHLC_HEADER

SCHEMA_VERSION = 1

OHLC = "daily/ohlc.csv"
OHLC_ADJUSTED = "daily/ohlc_adjusted.csv"
MANIFEST = "manifest.json"
SUMS = "SHA256SUMS"
STATUS = "status.json"
INSTRUMENTS = "instruments.json"
DIVIDENDS = "dividends.json"
TAXES = "taxes.json"
EVENTS = "events.csv"

# Ficheiros gerados que entram no SHA256SUMS (o events.csv é mantido à mão e fica de fora).
SINGLE_FILES = (OHLC, OHLC_ADJUSTED, MANIFEST, STATUS, INSTRUMENTS, DIVIDENDS, TAXES)
DAY_DIRS = ("prices", "snapshots", "summary")

_PRICE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.csv$")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def empty_manifest():
    return {"schema_version": SCHEMA_VERSION, "days": {}}


class Repo:
    def __init__(self, root):
        self.root = Path(root)

    @staticmethod
    def prices_rel(day):
        return f"prices/{day.year}/{day.isoformat()}.csv"

    @staticmethod
    def snapshot_rel(day):
        return f"snapshots/{day.isoformat()}.json"

    @staticmethod
    def summary_rel(day):
        return f"summary/{day.isoformat()}.json"

    def read(self, rel):
        path = self.root / rel
        return path.read_bytes() if path.is_file() else None

    def read_json(self, rel, exact=False):
        """Lê um JSON. Com `exact` os números decimais vêm como Decimal."""
        data = self.read(rel)
        if data is None:
            return None
        return json.loads(data.decode("utf-8"), parse_float=Decimal if exact else float)

    def price_days(self):
        days = set()
        base = self.root / "prices"
        if base.is_dir():
            for path in base.glob("*/*.csv"):
                match = _PRICE_FILE_RE.match(path.name)
                if match:
                    days.add(date.fromisoformat(match.group(1)))
        return days

    def snapshot_days(self):
        base = self.root / "snapshots"
        return sorted(date.fromisoformat(p.stem) for p in base.glob("*.json")) if base.is_dir() else []

    def load_manifest(self):
        manifest = self.read_json(MANIFEST)
        return manifest if manifest is not None else empty_manifest()

    def load_ohlc_rows(self):
        data = self.read(OHLC)
        if data is None:
            return []
        header, rows = read_csv(data)
        if header != OHLC_HEADER:
            raise ValueError("daily/ohlc.csv tem um cabeçalho inesperado")
        return rows

    def tracked_files(self):
        """Caminhos (com barras) dos ficheiros gerados que existem em disco."""
        found = [rel for rel in SINGLE_FILES if (self.root / rel).is_file()]
        for folder in DAY_DIRS:
            base = self.root / folder
            if base.is_dir():
                found.extend(p.relative_to(self.root).as_posix() for p in base.rglob("*") if p.is_file())
        return sorted(found)


class Transaction:
    """Acumula ficheiros em memória e escreve-os todos ou nenhum."""

    def __init__(self, repo):
        self.repo = repo
        self.staged = {}

    def put(self, rel, data):
        self.staged[rel] = data

    def get(self, rel):
        return self.staged[rel] if rel in self.staged else self.repo.read(rel)

    def commit(self):
        backups = {}
        try:
            for rel, data in self.staged.items():
                path = self.repo.root / rel
                old = path.read_bytes() if path.is_file() else None
                if old == data:
                    continue
                backups[rel] = old
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_name(path.name + ".tmp")
                try:
                    temp.write_bytes(data)
                    os.replace(temp, path)
                finally:
                    temp.unlink(missing_ok=True)
        except BaseException:
            for rel, old in backups.items():
                path = self.repo.root / rel
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(old)
            raise
        return sorted(backups)


def sums_text(tx):
    """Conteúdo do SHA256SUMS com todos os ficheiros gerados, tendo em conta o que está em staging."""
    paths = set(tx.repo.tracked_files()) | {rel for rel in tx.staged if _is_tracked(rel)}
    paths.discard(SUMS)
    lines = []
    for rel in sorted(paths):
        data = tx.get(rel)
        if data is not None:
            lines.append(f"{sha256_hex(data)}  {rel}\n")
    return "".join(lines).encode("utf-8")


def _is_tracked(rel):
    return rel in SINGLE_FILES or rel.split("/", 1)[0] in DAY_DIRS


def status_bytes(manifest, ohlc_rows, generated_at, last_closed):
    last = max(manifest["days"])
    rows = [r for r in ohlc_rows if r[0] == last]
    return json_bytes({
        "schema_version": SCHEMA_VERSION,
        "last_date": last,
        "generated_at": generated_at,
        "ticks": sum(int(r[7]) for r in rows),
        "instruments": len(rows),
        "ok": last == last_closed.isoformat(),
    })
