"""Slugs estáveis e seguros para nomes de ficheiro e URL."""

import hashlib
import re
import unicodedata

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Nomes de dispositivo do Windows não podem ser nomes de ficheiro, com qualquer extensão.
RESERVED = frozenset({"con", "prn", "aux", "nul"} | {f"com{n}" for n in range(1, 10)} | {f"lpt{n}" for n in range(1, 10)})


def base_slug(code):
    text = unicodedata.normalize("NFKD", code)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = text.replace("&", "-and-")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if not text:
        text = "i-" + hashlib.sha1(code.encode("utf-8")).hexdigest()[:8]
    return text


def assign_slugs(keys, previous=None):
    """Atribui um slug único a cada (código, tipo). Os slugs já existentes mantêm-se."""
    previous = previous or {}
    keys = sorted(set(keys))
    taken = {}
    result = {}
    for key in keys:
        slug = previous.get(key)
        if slug and SLUG_RE.match(slug) and slug not in RESERVED and slug not in taken:
            taken[slug] = key
            result[key] = slug
    for key in keys:
        if key in result:
            continue
        base = base_slug(key[0])
        candidates = [base, f"{base}-{key[1]}"] + [f"{base}-{key[1]}-{n}" for n in range(2, 1000)]
        for slug in candidates:
            if slug not in taken and slug not in RESERVED:
                taken[slug] = key
                result[key] = slug
                break
    return result
