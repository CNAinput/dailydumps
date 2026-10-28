"""Regras de estilo do repositório: sem travessões e sem dois traços seguidos."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "__pycache__", "_site", "prices", "snapshots", "summary", "daily"}
TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".json", ".csv", ".txt", ".example", ".html", ".css", ".js", ".svg"}
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
# Propriedades personalizadas do CSS (declaração e var) são sintaxe da linguagem e só valem em .css.
CSS_VAR = re.compile(r"var\(\s*" + DOUBLE + r"[a-z0-9]+(?:-[a-z0-9]+)*")
CSS_PROPERTY = re.compile(r"(?<![\w-])" + DOUBLE + r"[a-z0-9]+(?:-[a-z0-9]+)*(?=\s*:)")


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
    elif path.suffix == ".css":
        line = CSS_PROPERTY.sub("", CSS_VAR.sub("var(", line))
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

    def test_o_site_esta_ao_alcance_dos_testes(self):
        names = {p.relative_to(ROOT).as_posix() for p in text_files()}
        self.assertTrue(any(n.startswith("web/") and n.endswith(".js") for n in names))
        self.assertTrue(any(n.startswith("web/") and n.endswith(".css") for n in names))
        escondidos = [
            p.relative_to(ROOT).as_posix() for p in (ROOT / "web").rglob("*") if SKIP_DIRS & set(p.relative_to(ROOT).parts)
        ]
        self.assertEqual(escondidos, [])


class DoubleDashRuleTests(unittest.TestCase):
    """A regra dos dois traços: só o CSS tem propriedades personalizadas."""

    @staticmethod
    def check(name, line):
        return has_double_dash(Path(name), line)

    def test_css_aceita_propriedades_personalizadas(self):
        self.assertFalse(self.check("a.css", ":root { " + DOUBLE + "bg: #fff; }"))
        self.assertFalse(self.check("a.css", "color: var(" + DOUBLE + "text-2);"))
        self.assertFalse(self.check("a.css", "margin: calc(var(" + DOUBLE + "gap) * 2);"))

    def test_css_recusa_os_outros_usos(self):
        self.assertTrue(self.check("a.css", ".cartao" + DOUBLE + "ativo { color: red; }"))
        self.assertTrue(self.check("a.css", "/* a " + DOUBLE + " b */"))
        self.assertTrue(self.check("a.css", "a { color: red; } /* " + DOUBLE + " */"))

    def test_js_e_html_nao_aceitam_propriedades_personalizadas(self):
        self.assertTrue(self.check("a.js", "i" + DOUBLE + ";"))
        self.assertTrue(self.check("a.js", 'el.style.setProperty("' + DOUBLE + 'x", 1);'))
        self.assertTrue(self.check("a.html", '<p style="color: var(' + DOUBLE + 'x)">'))
        self.assertTrue(self.check("a.svg", "a " + DOUBLE + " b"))

    def test_comentarios_html_continuam_aceites(self):
        self.assertFalse(self.check("a.html", "<!" + DOUBLE + " nota " + DOUBLE + ">"))
        self.assertTrue(self.check("a.js", "x = '<!" + DOUBLE + " nota " + DOUBLE + ">';"))


if __name__ == "__main__":
    unittest.main()
