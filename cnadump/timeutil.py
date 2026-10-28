"""Tempo: dia civil de Lisboa, janelas em UTC e formatos de data e hora."""

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LISBON = ZoneInfo("Europe/Lisbon")
UTC = timezone.utc

OPEN_HOUR = 11
CLOSE_HOUR = 23
RETENTION_DAYS = 40

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}(?::?\d{2})?)$"
)


def _aware(dt):
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("data e hora sem fuso horário")
    return dt


def parse_date(text):
    """Lê uma data no formato estrito AAAA-MM-DD."""
    if not isinstance(text, str) or not _DATE_RE.match(text.strip()):
        raise ValueError(f"data inválida: {text!r}")
    return date.fromisoformat(text.strip())


def parse_timestamp(text):
    """Lê um timestamp ISO 8601 com fuso e devolve-o em UTC."""
    match = _TS_RE.match(text.strip()) if isinstance(text, str) else None
    if not match:
        raise ValueError(f"timestamp inválido: {text!r}")
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    micro = int((match.group(7) or "").ljust(6, "0"))
    zone = match.group(8)
    if zone == "Z":
        offset = timedelta(0)
    else:
        sign = -1 if zone[0] == "-" else 1
        digits = zone[1:].replace(":", "")
        offset = sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0))
    local = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone(offset))
    return local.astimezone(UTC)


def format_utc(dt):
    """Formato canónico dos ticks: sempre 6 dígitos de fração e sufixo Z."""
    return _aware(dt).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def format_utc_seconds(dt):
    """Formato canónico dos instantes de execução: segundos e sufixo Z."""
    return _aware(dt).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def lisbon_midnight(day):
    return datetime(day.year, day.month, day.day, tzinfo=LISBON)


def day_window(day):
    """Intervalo [início, fim) do dia civil de Lisboa, em UTC."""
    start = lisbon_midnight(day).astimezone(UTC)
    end = lisbon_midnight(day + timedelta(days=1)).astimezone(UTC)
    return start, end


def open_instant(day):
    return datetime(day.year, day.month, day.day, OPEN_HOUR, tzinfo=LISBON)


def close_instant(day):
    return datetime(day.year, day.month, day.day, CLOSE_HOUR, tzinfo=LISBON)


def lisbon_date(dt):
    return _aware(dt).astimezone(LISBON).date()


def last_closed_day(now):
    """Último dia cujo fecho (23:00 de Lisboa) já passou."""
    local = _aware(now).astimezone(LISBON)
    today = local.date()
    return today if local >= close_instant(today) else today - timedelta(days=1)


def may_be_cut_by_retention(day, generated_at):
    """True se a retenção do bot pode ter apagado os primeiros ticks do dia."""
    return open_instant(day) < _aware(generated_at) - timedelta(days=RETENTION_DAYS)
