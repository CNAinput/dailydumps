"""Eventos estruturais (events.csv) e ajuste das séries OHLC."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from .fmt import quantize, read_csv, tidy, to_decimal
from .model import ASSET_TYPES
from .timeutil import lisbon_midnight, parse_date, parse_timestamp

EVENTS_HEADER = [
    "date", "code", "asset_type", "event", "factor", "shares_before", "shares_after", "document_id", "notes",
]
EVENT_TYPES = ("ipo", "split", "issuance", "delisting")
ADJUST_PLACES = 4


@dataclass(frozen=True)
class Event:
    date: date
    code: str
    asset_type: str
    event: str
    factor: Optional[Decimal]
    shares_before: Optional[int]
    shares_after: Optional[int]
    document_id: Optional[int]
    notes: str

    @property
    def key(self):
        return (self.code, self.asset_type)


def _optional_int(text, name, minimum):
    if text == "":
        return None
    if not text.isdigit() or int(text) < minimum:
        raise ValueError(f"{name} tem de ser um inteiro maior ou igual a {minimum}")
    return int(text)


def _parse_row(row):
    day = parse_date(row[0])
    code, asset_type, kind = row[1], row[2], row[3]
    if not code or code != code.strip():
        raise ValueError("code vazio ou com espaços nas pontas")
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"asset_type tem de ser company ou asset, não {asset_type!r}")
    if kind not in EVENT_TYPES:
        raise ValueError(f"event tem de ser um de {', '.join(EVENT_TYPES)}, não {kind!r}")
    factor = None
    if row[4] != "":
        try:
            factor = Decimal(row[4])
        except InvalidOperation as exc:
            raise ValueError(f"factor inválido: {row[4]!r}") from exc
        if not factor.is_finite() or factor <= 0 or factor == 1:
            raise ValueError("factor tem de ser positivo e diferente de 1")
    if kind == "split" and factor is None:
        raise ValueError("um split precisa de factor")
    if kind != "split" and factor is not None:
        raise ValueError("só os splits têm factor")
    before = _optional_int(row[5], "shares_before", 0)
    after = _optional_int(row[6], "shares_after", 0)
    if kind == "split" and before is not None and after is not None and Decimal(after) != Decimal(before) * factor:
        raise ValueError("shares_after tem de ser shares_before vezes o factor")
    if kind == "issuance" and before is not None and after is not None and after <= before:
        raise ValueError("numa emissão shares_after tem de ser maior que shares_before")
    return Event(day, code, asset_type, kind, factor, before, after, _optional_int(row[7], "document_id", 1), row[8])


def parse_events(data):
    """Devolve (eventos, erros). Com erros a lista de eventos não deve ser usada."""
    header, rows = read_csv(data)
    if header != EVENTS_HEADER:
        return [], [f"events.csv: cabeçalho inválido, esperado {','.join(EVENTS_HEADER)}"]
    events, errors, seen = [], [], set()
    for number, row in enumerate(rows, start=2):
        if len(row) != len(EVENTS_HEADER):
            errors.append(f"events.csv, linha {number}: {len(row)} colunas em vez de {len(EVENTS_HEADER)}")
            continue
        try:
            event = _parse_row(row)
        except ValueError as exc:
            errors.append(f"events.csv, linha {number}: {exc}")
            continue
        if events and event.date < events[-1].date:
            errors.append(f"events.csv, linha {number}: datas fora de ordem cronológica")
        if tuple(row) in seen:
            errors.append(f"events.csv, linha {number}: linha repetida")
        seen.add(tuple(row))
        events.append(event)
    return events, errors


def adjust_ohlc(rows, events, generated_at):
    """Séries ajustadas aos splits.

    Os preços de cada dia vêm da base de dados, que já reflete os splits anteriores à geração do
    ficheiro. Um split só ajusta os dias cujo `generated_at` é anterior ao início da data do evento.
    `generated_at` mapeia AAAA-MM-DD para um instante com fuso.
    """
    splits = defaultdict(list)
    for event in events:
        if event.event == "split":
            splits[event.key].append((lisbon_midnight(event.date), event.factor))
    adjusted = []
    for row in rows:
        stamp = generated_at.get(row[0])
        factor = Decimal(1)
        if stamp is not None:
            for start, value in splits.get((row[1], row[2]), ()):
                if stamp < start:
                    factor *= value
        if factor == 1:
            adjusted.append(list(row))
            continue
        prices = [tidy(quantize(to_decimal(value) / factor, ADJUST_PLACES)) for value in row[3:7]]
        adjusted.append(row[:3] + prices + row[7:])
    return adjusted


def generation_times(manifest):
    return {day: parse_timestamp(entry["generated_at"]) for day, entry in manifest.get("days", {}).items()}
