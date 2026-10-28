"""Regras de estilo do repositório: sem travessões e sem dois traços seguidos."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "__pycache__", "_site", "prices", "snapshots", "summary", "daily"}
TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".json", ".csv", ".txt", ".example", ".html"}
TEXT_NAMES = {".gitignore", ".gitattributes", "CODEOWNERS", "LICENSE", "SHA256SUMS"}

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
DOUBLE = "-" * 2
TRIPLE = "-" * 3

# Opções de ferramentas externas, entre aspas, em listas de argumentos Python (por exemplo gh).
PY_FLAG = re.compile('"' + DOUBLE + "[a-z]+(?:-[a-z]+)*" + '"')
# Comandos de workflow cujas opções são impostas pela ferramenta.
YAML_TOOL = re.compile(r"\b(?:gh|git|pip)\b")
HTML_COMMENT = re.compile("<!" + DOUBLE + ".*?" + DOUBLE + ">")


def text_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or SKIP_DIRS & set(path.relative_to(ROOT).parts):
            continue
        if path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            yield path


def offending_lines(keep):
    """Linhas (ficheiro:número) em que `keep(path, linha)` devolve True."""
    found = []
    for path in text_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if keep(path, line):
                found.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    return found


def has_double_dash(path, line):
    if path.suffix == ".py":
        line = PY_FLAG.sub("", line)
    elif path.suffix in (".yml", ".yaml") and YAML_TOOL.search(line):
        return False
    elif path.suffix in (".md", ".html"):
        line = HTML_COMMENT.sub("", line)
    return DOUBLE in line


class StyleTests(unittest.TestCase):
    def test_ha_ficheiros_para_verificar(self):
        names = {p.name for p in text_files()}
        self.assertIn("pipeline.py", names)
        self.assertIn("SOURCES.md", names)

    def test_sem_travessoes_em_lado_nenhum(self):
        self.assertEqual(offending_lines(lambda p, line: EM_DASH in line or EN_DASH in line), [])

    def test_sem_dois_tracos_seguidos(self):
        self.assertEqual(offending_lines(has_double_dash), [])

    def test_sem_tres_tracos_em_markdown(self):
        self.assertEqual(offending_lines(lambda p, line: p.suffix == ".md" and TRIPLE in line), [])

    def test_fins_de_linha_lf(self):
        bad = [p.relative_to(ROOT).as_posix() for p in text_files() if b"\r" in p.read_bytes()]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
