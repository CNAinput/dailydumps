"""PostgREST falso: filtros, ordem, paginação, contagem exata, estado 206 e limite de linhas."""

import json
import urllib.parse
from datetime import datetime
from decimal import Decimal

from cnadump.client import Response
from cnadump.timeutil import UTC, parse_timestamp


def pg_timestamp(dt):
    """Formato do Postgres: fração sem zeros finais e deslocamento +00:00."""
    dt = dt.astimezone(UTC)
    text = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        text += "." + f"{dt.microsecond:06d}".rstrip("0")
    return text + "+00:00"


def _plain(value):
    if isinstance(value, datetime):
        return pg_timestamp(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _convert(sample, text):
    if isinstance(sample, datetime):
        return parse_timestamp(text)
    if isinstance(sample, bool):
        return text == "true"
    if isinstance(sample, int):
        return int(text)
    if isinstance(sample, (float, Decimal)):
        return float(text)
    return text


class FakePostgrest:
    def __init__(self, tables=None, rpcs=None, max_rows=1000, api_key=None):
        self.tables = tables if tables is not None else {}
        self.rpcs = rpcs if rpcs is not None else {}
        self.max_rows = max_rows
        self.api_key = api_key
        self.calls = []
        self.hooks = []

    def __call__(self, method, url, headers, data, timeout):
        parsed = urllib.parse.urlsplit(url)
        params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        self.calls.append((method, parsed.path, params))
        if self.api_key is not None and headers.get("apikey") != self.api_key:
            return Response(401, {}, b'{"message":"Invalid API key"}')
        name = parsed.path.rsplit("/", 1)[1]
        if parsed.path.startswith("/rest/v1/rpc/"):
            reply = self._rpc(method, name)
        else:
            reply = self._select(method, name, params, headers)
        for hook in self.hooks:
            reply = hook(method, parsed.path, params, reply)
        return reply

    def _rpc(self, method, name):
        if method != "POST" or name not in self.rpcs:
            return Response(404, {}, b'{"message":"function not found"}')
        return Response(200, {}, json.dumps(self.rpcs[name](), default=_plain).encode("utf-8"))

    @staticmethod
    def _matches(row, column, expression):
        operator, _, text = expression.partition(".")
        if column not in row:
            return False
        left, right = row[column], _convert(row[column], text)
        return {
            "eq": left == right,
            "gt": left > right,
            "gte": left >= right,
            "lt": left < right,
            "lte": left <= right,
        }[operator]

    def _select(self, method, table, params, headers):
        if method != "GET":
            return Response(405, {}, b'{"message":"method not allowed"}')
        if table not in self.tables:
            return Response(404, {}, b'{"message":"relation does not exist"}')
        rows = list(self.tables[table])
        select, order, limit, offset = "*", [], None, 0
        for key, value in params:
            if key == "select":
                select = value
            elif key == "order":
                order = value.split(",")
            elif key == "limit":
                limit = int(value)
            elif key == "offset":
                offset = int(value)
            else:
                rows = [row for row in rows if self._matches(row, key, value)]
        for item in reversed(order):
            column, _, direction = item.partition(".")
            rows.sort(key=lambda row, c=column: row[c], reverse=(direction == "desc"))
        total = len(rows)
        size = min(limit if limit is not None else self.max_rows, self.max_rows)
        page = rows[offset:offset + size]
        columns = None if select == "*" else select.split(",")
        out = []
        for row in page:
            if columns:
                missing = [c for c in columns if c not in row]
                if missing:
                    body = json.dumps({"message": f"column {missing[0]} does not exist"})
                    return Response(400, {}, body.encode("utf-8"))
                row = {c: row[c] for c in columns}
            out.append({k: _plain(v) for k, v in row.items()})
        out_headers = {}
        if "count=exact" in headers.get("Prefer", ""):
            out_headers["content-range"] = f"{offset}-{offset + len(page) - 1}/{total}" if page else f"*/{total}"
        status = 206 if offset > 0 or offset + len(page) < total else 200
        return Response(status, out_headers, json.dumps(out).encode("utf-8"))
