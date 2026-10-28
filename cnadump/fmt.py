"""Formatos: números exatos, CSV e JSON deterministas."""

import csv
import io
import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def to_decimal(value):
    """Converte para Decimal sem passar por float binário quando possível."""
    if isinstance(value, bool):
        raise ValueError("um booleano não é um número")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError(f"número inválido: {value!r}") from exc
    raise ValueError(f"número inválido: {value!r}")


def plain(value):
    """Texto decimal sem expoente."""
    number = to_decimal(value)
    if not number.is_finite():
        raise ValueError("número não finito")
    text = format(number, "f")
    return text[1:] if text.startswith("-") and number == 0 else text


def quantize(value, places):
    """Arredonda a `places` casas decimais, metade para cima."""
    return to_decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def tidy(value, min_places=2):
    """Remove zeros finais mas mantém pelo menos `min_places` casas."""
    int_part, _, frac = plain(value).partition(".")
    frac = frac.rstrip("0").ljust(min_places, "0")
    return f"{int_part}.{frac}" if frac else int_part


def csv_bytes(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def read_csv(data):
    """Devolve (cabeçalho, linhas) de um CSV em bytes UTF-8."""
    text = data.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows:
        return [], []
    return rows[0], rows[1:]


def jsonable(value):
    """Prepara um valor para json.dumps: Decimal passa a int ou float exato."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("número não finito em JSON")
        if value == value.to_integral_value():
            return int(value)
        approx = float(value)
        if Decimal(repr(approx)) != value:
            raise ValueError(f"número sem representação exata em JSON: {value}")
        return approx
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def json_bytes(value):
    text = json.dumps(jsonable(value), ensure_ascii=False, indent=2)
    return (text + "\n").encode("utf-8")
