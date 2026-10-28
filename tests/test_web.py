"""Verificações estáticas do site em web/: nada de HTML nem código a partir dos dados, nada externo, módulos completos."""

import re
import unittest
from pathlib import Path

from cnadump.pages import build_pages
from tests.builders import NOW, StandardWorldCase

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
ALLOWED_HOSTS = {"github.com", "raw.githubusercontent.com", "creativecommons.org", "www.w3.org"}

# Os nomes das empresas são escritos por utilizadores do Discord: nada pode interpretá-los como HTML ou código.
FORBIDDEN_JS = {
    "innerHTML": re.compile(r"\binnerHTML\b"),
    "outerHTML": re.compile(r"\bouterHTML\b"),
    "insertAdjacentHTML": re.compile(r"\binsertAdjacentHTML\b"),
    "document.write": re.compile(r"\bdocument\s*\.\s*write(?:ln)?\s*\("),
    "eval": re.compile(r"\beval\s*\("),
    "new Function": re.compile(r"\bnew\s+Function\b"),
    "setTimeout ou setInterval com texto": re.compile(r"\bset(?:Timeout|Interval)\s*\(\s*[\"'`]"),
    "srcdoc": re.compile(r"\bsrcdoc\b"),
    "DOMParser": re.compile(r"\bDOMParser\b"),
    "createContextualFragment": re.compile(r"\bcreateContextualFragment\b"),
    "URL javascript:": re.compile(r"javascript\s*:", re.IGNORECASE),
    "console.log": re.compile(r"\bconsole\s*\.\s*log\b"),
    "debugger": re.compile(r"\bdebugger\b"),
}
HOST = re.compile(r"https?://([^/\s\"'<>)`\\;,]+)")
MODULE_REFERENCE = re.compile(r"""(?:from\s+|import\s*\(\s*|import\s+)["'](\.{1,2}/[^"']+)["']""")
CSP = re.compile(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"')


def forbidden_apis(text):
    return sorted(name for name, pattern in FORBIDDEN_JS.items() if pattern.search(text))


def external_hosts(text):
    return {host.split(":")[0] for host in HOST.findall(text)}


def module_references(path, text):
    return {(path.parent / rel).resolve() for rel in MODULE_REFERENCE.findall(text)}


def files(pattern):
    return sorted(WEB.rglob(pattern))


class CheckerTests(unittest.TestCase):
    """Os verificadores apanham mesmo o que dizem apanhar."""

    def test_apis_proibidas(self):
        for code, name in (
            ("el.innerHTML = x;", "innerHTML"),
            ("el.outerHTML = x;", "outerHTML"),
            ("el.insertAdjacentHTML('beforeend', x);", "insertAdjacentHTML"),
            ("document.write(x);", "document.write"),
            ("eval(texto);", "eval"),
            ("const f = new Function('return 1');", "new Function"),
            ("setTimeout('alert(1)', 10);", "setTimeout ou setInterval com texto"),
            ("iframe.srcdoc = x;", "srcdoc"),
            ("new DOMParser().parseFromString(x, 'text/html');", "DOMParser"),
            ("range.createContextualFragment(x);", "createContextualFragment"),
            ("a.href = 'javascript:alert(1)';", "URL javascript:"),
            ("console.log(x);", "console.log"),
            ("debugger;", "debugger"),
        ):
            with self.subTest(name):
                self.assertEqual(forbidden_apis(code), [name])

    def test_codigo_legitimo_passa(self):
        legitimo = "el.textContent = x; setTimeout(() => ok(), 10); console.error(e); document.createElement('p');"
        self.assertEqual(forbidden_apis(legitimo), [])

    def test_hosts_externos(self):
        self.assertEqual(external_hosts('fetch("https://mau.exemplo/x"); a("http://outro.pt:8080/y");'), {"mau.exemplo", "outro.pt"})
        self.assertEqual(external_hosts("sem ligacoes"), set())

    def test_referencias_a_modulos(self):
        path = ROOT / "web" / "js" / "a.js"
        text = 'import { x } from "./b.js"; import "../c.js"; const m = await import("./pages/d.js");'
        self.assertEqual(
            module_references(path, text),
            {(ROOT / "web/js/b.js").resolve(), (ROOT / "web/c.js").resolve(), (ROOT / "web/js/pages/d.js").resolve()},
        )


class SiteTests(unittest.TestCase):
    def test_tem_o_essencial(self):
        for rel in ("index.html", "favicon.svg", "favicon.ico", "css/site.css", "js/main.js"):
            self.assertTrue((WEB / rel).is_file(), rel)

    def test_sem_apis_que_interpretam_texto_como_html_ou_codigo(self):
        for path in files("*.js") + files("*.html"):
            with self.subTest(path.relative_to(ROOT).as_posix()):
                self.assertEqual(forbidden_apis(path.read_text(encoding="utf-8")), [])

    def test_so_ha_ligacoes_externas_conhecidas(self):
        for path in files("*"):
            if path.is_file() and path.suffix in {".html", ".css", ".js", ".svg", ".json", ".txt"}:
                with self.subTest(path.relative_to(ROOT).as_posix()):
                    hosts = external_hosts(path.read_text(encoding="utf-8"))
                    self.assertEqual(hosts - ALLOWED_HOSTS, set())

    def test_css_sem_recursos_externos(self):
        for path in files("*.css"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("@import", text, path.name)
            self.assertNotIn("url(", text, path.name)

    def test_pagina_inicial(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="pt-PT">', html)
        self.assertIn('name="viewport"', html)
        self.assertIn('id="conteudo"', html)
        self.assertIn('class="skip-link"', html)
        self.assertIn('<nav class="site-nav" aria-label="Principal">', html)
        scripts = re.findall(r"<script\b([^>]*)>", html)
        self.assertEqual(len(scripts), 1)
        self.assertIn('type="module"', scripts[0])
        self.assertIn('src="js/main.js"', scripts[0])
        self.assertNotRegex(html, r"\son[a-z]+\s*=")
        self.assertNotRegex(html, r"\sstyle\s*=")
        self.assertNotIn("<style", html)
        for reference in re.findall(r'(?:src|href)="([^"]+)"', html):
            if not reference.startswith(("#", "https://", "api.html")):
                self.assertTrue((WEB / reference).is_file(), reference)

    def test_politica_de_seguranca_de_conteudo(self):
        found = CSP.search((WEB / "index.html").read_text(encoding="utf-8"))
        self.assertIsNotNone(found)
        directives = {item.split()[0]: item.split()[1:] for item in found.group(1).split(";") if item.strip()}
        self.assertEqual(directives["default-src"], ["'self'"])
        self.assertEqual(directives["script-src"], ["'self'"])
        self.assertEqual(directives["style-src"], ["'self'"])
        self.assertEqual(directives["object-src"], ["'none'"])
        self.assertEqual(directives["base-uri"], ["'none'"])
        self.assertEqual(directives["connect-src"], ["'self'", "https://raw.githubusercontent.com"])
        self.assertNotIn("unsafe", found.group(1))

    def test_modulos_existem_e_nenhum_fica_orfao(self):
        todos = {path.resolve() for path in files("*.js")}
        alcancados, por_ver = set(), [(WEB / "js/main.js").resolve()]
        while por_ver:
            atual = por_ver.pop()
            if atual in alcancados:
                continue
            self.assertTrue(atual.is_file(), f"módulo em falta: {atual}")
            alcancados.add(atual)
            por_ver.extend(module_references(atual, atual.read_text(encoding="utf-8")))
        self.assertEqual(sorted(p.name for p in todos - alcancados), [])

class PublishTests(StandardWorldCase):
    def test_o_site_do_repositorio_passa_pelo_build_pages(self):
        # O build-pages recusa colisões com a API e com os dados e exige o index.html.
        self.generator(NOW).run_day()
        out = self.root / "_site"
        written = build_pages(self.repo, out, NOW, web=WEB)
        self.assertIn("index.html", written)
        self.assertIn("js/main.js", written)
        self.assertEqual((out / "index.html").read_bytes(), (WEB / "index.html").read_bytes())


if __name__ == "__main__":
    unittest.main()
