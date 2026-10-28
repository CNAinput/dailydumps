"""Configuração: variáveis de ambiente e ficheiro .env local."""

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

NAMES = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "HEALTHCHECK_URL")


@dataclass(frozen=True)
class Settings:
    url: str
    key: str


def parse_env_file(text):
    """Lê linhas CHAVE=VALOR, ignorando comentários e linhas vazias."""
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_values(root, environ=None):
    """Junta o .env (se existir) com o ambiente. O ambiente tem prioridade."""
    environ = os.environ if environ is None else environ
    values = {}
    env_file = Path(root) / ".env"
    if env_file.is_file():
        values.update(parse_env_file(env_file.read_text(encoding="utf-8")))
    for name in NAMES:
        if environ.get(name):
            values[name] = environ[name]
    return values


def load_settings(root, environ=None):
    values = load_values(root, environ)
    url = values.get("SUPABASE_URL", "").strip().rstrip("/")
    key = values.get("SUPABASE_ANON_KEY", "").strip()
    if not url.startswith(("https://", "http://")):
        raise ConfigError("SUPABASE_URL em falta ou inválida (tem de começar por https://).")
    if not key:
        raise ConfigError("SUPABASE_ANON_KEY em falta.")
    return Settings(url=url, key=key)


def healthcheck_url(root, environ=None):
    """URL de ping do Healthchecks.io. Vazio quando não está definido."""
    return load_values(root, environ).get("HEALTHCHECK_URL", "").strip()
