"""Ping ao Healthchecks.io (dead man's switch): só envia se houver URL."""

import time
import urllib.parse
import urllib.request

ATTEMPTS = 3


def _open(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as reply:
        reply.read()


def ping(status, url, opener=_open, sleep=time.sleep, log=print):
    """Envia o ping de sucesso (`ok`) ou de falha (`fail`). Devolve True se foi enviado."""
    if status not in ("ok", "fail"):
        raise ValueError(f"estado de ping desconhecido: {status!r}")
    if not url:
        log("HEALTHCHECK_URL não definido: ping ignorado.")
        return False
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        log("HEALTHCHECK_URL inválido: ping ignorado.")
        return False
    target = url.rstrip("/") + ("/fail" if status == "fail" else "")
    last = "sem resposta"
    for attempt in range(ATTEMPTS):
        if attempt:
            sleep(2 * attempt)
        try:
            opener(target, 10)
        except Exception as exc:
            last = exc.__class__.__name__
            continue
        log(f"Ping '{status}' enviado para {parts.netloc}.")
        return True
    log(f"AVISO: o ping '{status}' falhou ({last}); o dead man's switch alerta se isto persistir.")
    return False
