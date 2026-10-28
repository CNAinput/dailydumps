"""Cliente PostgREST: só leitura, com repetições, paginação e conferência da contagem."""

import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal

from . import __version__
from .errors import NetworkError, ValidationError

PAGE_SIZE = 1000
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

_RANGE_RE = re.compile(r"^(?:\d+-\d+|\*)/(\d+|\*)$")


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes


def urllib_transport(method, url, headers, data, timeout):
    """Transporte real. Os nomes dos cabeçalhos da resposta ficam em minúsculas."""
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return Response(reply.status, {k.lower(): v for k, v in reply.headers.items()}, reply.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read())


def _reject_constant(name):
    raise ValueError(f"constante JSON não permitida: {name}")


def parse_json(body):
    """Lê JSON com números decimais exatos e sem NaN nem Infinity."""
    try:
        return json.loads(body.decode("utf-8"), parse_float=Decimal, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise NetworkError(f"Resposta do servidor não é JSON válido ({exc}).") from exc


def content_range_total(value):
    """Total de linhas anunciado em `Content-Range`, ou None se não existir."""
    match = _RANGE_RE.match((value or "").strip())
    if not match or match.group(1) == "*":
        return None
    return int(match.group(1))


class PostgrestClient:
    def __init__(self, base_url, api_key, transport=None, retries=4, backoff=1.0,
                 sleep=time.sleep, page_size=PAGE_SIZE, timeout=60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.transport = transport or urllib_transport
        self.retries = retries
        self.backoff = backoff
        self.sleep = sleep
        self.page_size = page_size
        self.timeout = timeout

    def _headers(self, prefer, has_body):
        headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": f"cnadump/{__version__}",
        }
        if prefer:
            headers["Prefer"] = prefer
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def request(self, method, path, params=None, body=None, prefer=None):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = self._headers(prefer, data is not None)
        last = "sem resposta"
        for attempt in range(self.retries + 1):
            if attempt:
                self.sleep(self.backoff * 2 ** (attempt - 1))
            try:
                reply = self.transport(method, url, headers, data, self.timeout)
            except (OSError, http.client.HTTPException) as exc:
                last = f"falha de rede ({exc.__class__.__name__})"
                continue
            if reply.status in RETRY_STATUS:
                last = f"HTTP {reply.status}"
                continue
            if reply.status in (401, 403):
                raise NetworkError(
                    f"Acesso recusado pelo servidor (HTTP {reply.status}). Confirma SUPABASE_URL e SUPABASE_ANON_KEY."
                )
            if not 200 <= reply.status < 300:
                detail = reply.body[:200].decode("utf-8", "replace")
                raise NetworkError(f"Pedido recusado (HTTP {reply.status}): {detail}")
            return reply
        raise NetworkError(f"Falha ao contactar o servidor após {self.retries + 1} tentativas ({last}).")

    def select(self, table, params):
        """Todas as linhas de `params`, paginadas, conferidas com a contagem exata do servidor."""
        rows = []
        total = None
        offset = 0
        while True:
            page_params = list(params) + [("limit", str(self.page_size)), ("offset", str(offset))]
            reply = self.request("GET", f"/rest/v1/{table}", page_params, prefer="count=exact")
            page = parse_json(reply.body)
            if not isinstance(page, list):
                raise NetworkError(f"Resposta inesperada de {table}: era esperada uma lista.")
            page_total = content_range_total(reply.headers.get("content-range"))
            if page_total is None:
                raise NetworkError(f"O servidor não devolveu a contagem exata de {table}.")
            if total is None:
                total = page_total
            elif page_total != total:
                raise ValidationError(
                    f"A contagem de {table} mudou durante a leitura ({total} e depois {page_total})."
                )
            rows.extend(page)
            offset += len(page)
            if not page or offset >= total:
                break
        if len(rows) != total:
            raise ValidationError(f"Contagem diferente em {table}: o servidor tem {total} linhas e foram recebidas {len(rows)}.")
        return rows

    def rpc(self, name, args=None):
        """Chama uma função de leitura. É o único POST que o arquivo faz."""
        reply = self.request("POST", f"/rest/v1/rpc/{name}", body=args or {})
        return parse_json(reply.body)
