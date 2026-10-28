import io
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from cnadump import health
from cnadump.cli import main
from cnadump.errors import ValidationError
from cnadump.pages import build_pages
from cnadump.pipeline import RunResult
from cnadump.store import Repo
from cnadump.verify import protected_changes, verify_repo
from tests.builders import D26, NOW, StandardWorldCase, lisbon_now, local, write_web

HEADER = "date,code,asset_type,event,factor,shares_before,shares_after,document_id,notes\n"
ENV = {"SUPABASE_URL": "https://exemplo.supabase.co", "SUPABASE_ANON_KEY": "chave"}


class ArchivedCase(StandardWorldCase):
    def setUp(self):
        super().setUp()
        self.generator(NOW).run_day()

    def replace(self, rel, old, new):
        path = self.root / rel
        path.write_bytes(path.read_bytes().replace(old, new, 1))


class VerifyTests(ArchivedCase):
    def test_repositorio_acabado_de_gerar_esta_integro(self):
        report = verify_repo(self.repo)
        self.assertEqual((report.errors, report.warnings), ([], []))

    def test_repositorio_vazio_esta_integro(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(verify_repo(Repo(empty)).errors, [])

    def test_preco_adulterado(self):
        rel = "prices/2026/2026-10-26.csv"
        text = (self.root / rel).read_text(encoding="utf-8").splitlines()
        first = text[1].split(",")
        first[3] = "123456.78"
        text[1] = ",".join(first)
        (self.root / rel).write_bytes(("\n".join(text) + "\n").encode("utf-8"))
        errors = verify_repo(self.repo).errors
        self.assertTrue(any("sha256 não corresponde" in e for e in errors), errors)
        self.assertTrue(any("daily/ohlc.csv" in e for e in errors), errors)
        self.assertTrue(any("SHA256SUMS" in e for e in errors), errors)

    def test_ficheiro_de_precos_apagado(self):
        (self.root / "prices/2026/2026-10-26.csv").unlink()
        errors = verify_repo(self.repo).errors
        self.assertTrue(any("manifest.json e prices/ não coincidem" in e for e in errors), errors)

    def test_fins_de_linha_crlf(self):
        rel = "prices/2026/2026-10-26.csv"
        path = self.root / rel
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertTrue(any("CRLF" in e for e in verify_repo(self.repo).errors))

    def test_linhas_fora_de_ordem(self):
        rel = "prices/2026/2026-10-26.csv"
        path = self.root / rel
        lines = path.read_bytes().splitlines(keepends=True)
        lines[1], lines[2] = lines[2], lines[1]
        path.write_bytes(b"".join(lines))
        self.assertTrue(any("fora de ordem ou duplicadas" in e for e in verify_repo(self.repo).errors))

    def test_resumo_em_falta(self):
        (self.root / "summary/2026-10-25.json").unlink()
        self.assertTrue(any("summary/2026-10-25.json: em falta" in e for e in verify_repo(self.repo).errors))

    def test_snapshot_apagado_de_um_dia_daily(self):
        (self.root / "snapshots/2026-10-27.json").unlink()
        errors = verify_repo(self.repo).errors
        self.assertTrue(any("snapshot só deve existir nos dias com source daily" in e for e in errors), errors)

    def test_snapshot_num_dia_de_backfill(self):
        (self.root / "snapshots/2026-10-26.json").write_bytes(b"{}\n")
        errors = verify_repo(self.repo).errors
        self.assertTrue(any("2026-10-26" in e and "snapshot" in e for e in errors), errors)

    def test_chave_que_sugere_ids_de_contas(self):
        self.replace("dividends.json", b'"policies"', b'"account_id"')
        self.assertTrue(any("account_id" in e for e in verify_repo(self.repo).errors))

    def test_chave_suspeita_num_snapshot_e_num_resumo(self):
        self.replace("snapshots/2026-10-27.json", b'"shares_total"', b'"user_id"')
        self.replace("summary/2026-10-26.json", b'"indices"', b'"discord_ids"')
        errors = verify_repo(self.repo).errors
        self.assertTrue(any("snapshots/2026-10-27.json" in e and "user_id" in e for e in errors), errors)
        self.assertTrue(any("summary/2026-10-26.json" in e and "discord_ids" in e for e in errors), errors)

    def test_slug_inseguro(self):
        self.replace("instruments.json", b'"p-and-p10"', b'"P&P10/.."')
        self.assertTrue(any("slug inseguro" in e for e in verify_repo(self.repo).errors))

    def test_estado_incoerente(self):
        self.replace("status.json", b"2026-10-27", b"2026-10-26")
        self.assertTrue(any("last_date devia ser 2026-10-27" in e for e in verify_repo(self.repo).errors))

    def test_somas_adulteradas(self):
        self.replace("SHA256SUMS", b"a", b"b")
        self.assertTrue(any("SHA256SUMS" in e for e in verify_repo(self.repo).errors))

    def test_events_invalido_e_erro(self):
        (self.root / "events.csv").write_text("lixo\n", encoding="utf-8")
        self.assertTrue(any("events.csv" in e for e in verify_repo(self.repo).errors))

    def test_ajustado_desatualizado_e_so_um_aviso(self):
        (self.root / "events.csv").write_text(
            HEADER + "2026-10-28,NEWTE,company,split,4,300000,1200000,,\n", encoding="utf-8"
        )
        report = verify_repo(self.repo)
        self.assertEqual(report.errors, [])
        self.assertTrue(any("ohlc_adjusted.csv" in w and "desatualizado" in w for w in report.warnings))

    def test_ajustado_regenerado_deixa_de_avisar(self):
        (self.root / "events.csv").write_text(
            HEADER + "2026-10-28,NEWTE,company,split,4,300000,1200000,,\n", encoding="utf-8"
        )
        self.assertEqual(main(["adjust"], root=self.root, environ=ENV, now=NOW, out=lambda m: None), 0)
        report = verify_repo(self.repo)
        self.assertEqual((report.errors, report.warnings), ([], []))


class GuardTests(unittest.TestCase):
    def test_so_o_workflow_escreve_estes_ficheiros(self):
        blocked = protected_changes([
            "prices/2026/2026-10-26.csv", "summary/2026-10-26.json", "snapshots/2026-10-26.json",
            "daily/ohlc.csv", "daily/ohlc_adjusted.csv", "manifest.json", "SHA256SUMS", "status.json",
            "instruments.json", "dividends.json", "taxes.json",
        ])
        self.assertEqual(len(blocked), 11)

    def test_pull_requests_podem_mudar_isto(self):
        allowed = ["events.csv", "README.md", "docs/OPERATIONS.md", "cnadump/pipeline.py", "tests/test_x.py",
                   ".github/workflows/dump.yml", "requirements.txt", "LICENSE", ".gitignore", "price/x.csv"]
        self.assertEqual(protected_changes(allowed), [])

    def test_aceita_separadores_do_windows_e_linhas_vazias(self):
        self.assertEqual(protected_changes(["prices\\2026\\x.csv", "", "  "]), ["prices/2026/x.csv"])


class PagesTests(ArchivedCase):
    def setUp(self):
        super().setUp()
        write_web(self.root)

    def build(self, now=NOW, **kwargs):
        out = self.root / "_site"
        return out, build_pages(self.repo, out, now, **kwargs)

    def test_ficheiros_gerados(self):
        out, written = self.build()
        for rel in ("latest.json", "dates.json", "instruments.json", "badge.json", "api.html", "index.html",
                    "instruments/p-and-p10.json", "instruments/newte.json"):
            self.assertIn(rel, written)
            self.assertTrue((out / rel).is_file(), rel)

    def test_o_site_vem_de_web(self):
        out, written = self.build()
        for rel in ("index.html", "css/site.css", "js/main.js"):
            self.assertIn(rel, written)
            self.assertEqual((out / rel).read_bytes(), (self.root / "web" / rel).read_bytes(), rel)

    def test_dados_copiados_com_o_caminho_do_repositorio(self):
        (self.root / "events.csv").write_text(
            HEADER + "2026-08-24,NEWTE,company,split,4,8000,32000,69,teste\n", encoding="utf-8"
        )
        out, written = self.build()
        for rel in ("daily/ohlc.csv", "daily/ohlc_adjusted.csv", "events.csv", "manifest.json", "status.json",
                    "SHA256SUMS", "dividends.json", "taxes.json", "summary/2026-10-25.json", "summary/2026-10-27.json",
                    "snapshots/2026-10-27.json"):
            self.assertIn(rel, written, rel)
            self.assertEqual((out / rel).read_bytes(), (self.root / rel).read_bytes(), rel)

    def test_o_events_csv_e_opcional(self):
        out, written = self.build()
        self.assertFalse((self.root / "events.csv").exists())
        self.assertNotIn("events.csv", written)

    def test_os_ticks_nao_vao_para_o_site(self):
        out, written = self.build()
        self.assertFalse((out / "prices").exists())
        self.assertEqual([rel for rel in written if rel.startswith("prices/")], [])

    def test_so_os_dias_com_snapshot_levam_snapshot(self):
        out, _ = self.build()
        self.assertEqual(sorted(p.name for p in (out / "snapshots").iterdir()), ["2026-10-27.json"])

    def test_instruments_json_continua_a_ser_o_da_api(self):
        out, _ = self.build()
        site = json.loads((out / "instruments.json").read_text(encoding="utf-8"))
        self.assertEqual(set(site["instruments"][0]), {"code", "asset_type", "name", "slug"})
        self.assertNotEqual((out / "instruments.json").read_bytes(), (self.root / "instruments.json").read_bytes())

    def test_a_api_nao_depende_do_site(self):
        out, _ = self.build()
        api = ("latest.json", "dates.json", "instruments.json", "badge.json", "instruments/newte.json")
        before = {rel: (out / rel).read_bytes() for rel in api}
        write_web(self.root, {"js/outro.js": "export const x = 1;\n", "index.html": "<!doctype html>\n<title>B</title>\n"})
        out, _ = self.build()
        self.assertEqual({rel: (out / rel).read_bytes() for rel in api}, before)

    def test_o_site_nao_pode_ocupar_enderecos_da_api_nem_dos_dados(self):
        for rel in ("latest.json", "dates.json", "badge.json", "api.html", "instruments.json", "instruments/x.json",
                    "daily/ohlc.csv", "events.csv", "SHA256SUMS", "manifest.json", "summary/a.json", "snapshots/a.json",
                    "prices/a.csv"):
            with self.subTest(rel):
                write_web(self.root, {rel: "x\n"})
                with self.assertRaises(ValidationError) as caught:
                    self.build()
                self.assertIn("web/" + rel, "\n".join(caught.exception.messages))
                (self.root / "web" / rel).unlink()

    def test_sem_index_html_e_um_erro(self):
        (self.root / "web/index.html").unlink()
        with self.assertRaises(ValidationError) as caught:
            self.build()
        self.assertIn("web/index.html em falta", str(caught.exception))
        self.assertFalse((self.root / "_site").exists())

    def test_ficheiros_ocultos_nao_vao_para_o_site(self):
        write_web(self.root, {".DS_Store": "x\n", "js/__pycache__/x.pyc": "x\n", ".git/config": "x\n"})
        _, written = self.build()
        self.assertEqual([rel for rel in written if ".DS_Store" in rel or "__pycache__" in rel or ".git" in rel], [])

    def test_pasta_web_alternativa(self):
        write_web(self.root / "alternativa", {"index.html": "<!doctype html>\n<title>Outro</title>\n"})
        out, _ = self.build(web=self.root / "alternativa" / "web")
        self.assertIn("Outro", (out / "index.html").read_text(encoding="utf-8"))

    def test_gerar_duas_vezes_da_o_mesmo(self):
        out, first = self.build()
        before = {rel: (out / rel).read_bytes() for rel in first}
        _, second = self.build()
        self.assertEqual(first, second)
        self.assertEqual({rel: (out / rel).read_bytes() for rel in second}, before)

    def test_pagina_da_api_liga_ao_repositorio_so_com_um_nome_valido(self):
        out = self.root / "_site"
        build_pages(self.repo, out, NOW, "CNAinput/dailydumps")
        html = (out / "api.html").read_text(encoding="utf-8")
        self.assertIn('<a href="https://github.com/CNAinput/dailydumps">', html)
        self.assertIn('<a href="index.html">', html)
        for invalido in (None, "", "sem-barra", 'x/"><script>', "a/b/c"):
            build_pages(self.repo, out, NOW, invalido)
            html = (out / "api.html").read_text(encoding="utf-8")
            self.assertNotIn("github.com", html, invalido)
            self.assertNotIn("@@", html, invalido)

    def test_latest_e_dates(self):
        out, _ = self.build()
        latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual(latest["date"], "2026-10-27")
        self.assertEqual(latest["source"], "daily")
        self.assertEqual(latest["rows"], 36)
        self.assertEqual(latest["instruments"], 6)
        self.assertEqual(latest["files"]["snapshot"], "snapshots/2026-10-27.json")
        self.assertTrue(latest["summary"]["market_cap_available"])
        dates = json.loads((out / "dates.json").read_text(encoding="utf-8"))
        self.assertEqual((dates["first"], dates["last"], dates["count"]), ("2026-10-25", "2026-10-27", 3))
        self.assertEqual([d["source"] for d in dates["dates"]], ["backfill", "backfill", "daily"])

    def test_pagina_de_instrumento(self):
        (self.root / "events.csv").write_text(
            HEADER + "2026-08-24,NEWTE,company,split,4,8000,32000,69,teste\n", encoding="utf-8"
        )
        out, _ = self.build()
        page = json.loads((out / "instruments/newte.json").read_text(encoding="utf-8"))
        self.assertEqual((page["code"], page["asset_type"], page["slug"]), ("NEWTE", "company", "newte"))
        self.assertEqual(page["name"], "NovaTecnologia,S.A.")
        self.assertFalse(page["is_index"])
        self.assertEqual([d["date"] for d in page["daily"]], ["2026-10-25", "2026-10-26", "2026-10-27"])
        self.assertEqual(set(page["daily"][0]), {"date", "open", "high", "low", "close", "ticks"})
        self.assertIsInstance(page["daily"][0]["open"], (int, float))
        self.assertEqual(len(page["daily_adjusted"]), 3)
        self.assertEqual(page["events"][0]["event"], "split")
        self.assertEqual(page["events"][0]["factor"], 4)
        self.assertEqual(page["events"][0]["document_id"], 69)
        index = json.loads((out / "instruments/p-and-p10.json").read_text(encoding="utf-8"))
        self.assertTrue(index["is_index"])
        self.assertEqual(index["events"], [])

    def test_sem_registo_de_instrumentos_usa_so_o_ohlc(self):
        shutil.rmtree(self.root)
        self.root.mkdir()
        write_web(self.root)
        self.generator(NOW).run_backfill()
        self.assertFalse((self.root / "instruments.json").exists())
        out, written = self.build()
        self.assertIn("instruments/newte.json", written)
        page = json.loads((out / "instruments/newte.json").read_text(encoding="utf-8"))
        self.assertIsNone(page["name"])
        self.assertEqual(len(page["daily"]), 3)

    def test_selo(self):
        def color(now):
            out = self.root / "_site"
            build_pages(self.repo, out, now)
            return json.loads((out / "badge.json").read_text(encoding="utf-8"))

        badge = color(NOW)
        self.assertEqual(badge, {"schemaVersion": 1, "label": "último dia", "message": "2026-10-27", "color": "brightgreen"})
        self.assertEqual(color(lisbon_now(date(2026, 10, 28), 23, 30))["color"], "yellow")
        self.assertEqual(color(lisbon_now(date(2026, 10, 30), 23, 30))["color"], "red")

    def test_sem_dias_arquivados_e_um_erro(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(ValidationError):
                build_pages(Repo(empty), Path(empty) / "_site", NOW)


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.logs, self.sleeps = [], [], []

    def opener(self, url, timeout):
        self.calls.append((url, timeout))

    def ping(self, status, url, opener=None):
        return health.ping(status, url, opener or self.opener, self.sleeps.append, self.logs.append)

    def test_sem_url_nao_envia_nada(self):
        for url in ("", None):
            self.assertFalse(self.ping("ok", url))
        self.assertEqual(self.calls, [])
        self.assertIn("ignorado", self.logs[0])

    def test_sucesso_e_falha(self):
        self.assertTrue(self.ping("ok", "https://hc-ping.com/abc-123"))
        self.assertTrue(self.ping("fail", "https://hc-ping.com/abc-123/"))
        self.assertEqual([c[0] for c in self.calls], ["https://hc-ping.com/abc-123", "https://hc-ping.com/abc-123/fail"])

    def test_o_url_secreto_nunca_vai_para_o_log(self):
        self.ping("ok", "https://hc-ping.com/segredo-uuid")
        self.assertTrue(all("segredo-uuid" not in line for line in self.logs))
        self.assertIn("hc-ping.com", self.logs[0])

    def test_url_invalido(self):
        for url in ("ftp://x/y", "hc-ping.com/abc", "https://"):
            self.assertFalse(self.ping("ok", url))
        self.assertEqual(self.calls, [])

    def test_repete_e_acaba_por_ter_sucesso(self):
        tentativas = []

        def instavel(url, timeout):
            tentativas.append(url)
            if len(tentativas) < 3:
                raise OSError("sem rede")

        self.assertTrue(self.ping("ok", "https://hc.io/x", instavel))
        self.assertEqual(len(tentativas), 3)
        self.assertEqual(self.sleeps, [2, 4])

    def test_falha_persistente_nao_levanta_erro(self):
        def sempre_falha(url, timeout):
            raise OSError("sem rede")

        self.assertFalse(self.ping("fail", "https://hc.io/x", sempre_falha))
        self.assertIn("AVISO", self.logs[-1])

    def test_estado_desconhecido(self):
        with self.assertRaises(ValueError):
            self.ping("talvez", "https://hc.io/x")


class CliTests(StandardWorldCase):
    def run_cli(self, *argv, now=NOW, environ=None, stdin=None):
        self.fake = self.world.transport()
        lines = []
        env = dict(ENV) if environ is None else environ
        code = main(list(argv), root=self.root, environ=env, now=now, transport=self.fake, stdin=stdin, out=lines.append)
        return code, "\n".join(lines)

    def test_day_e_nada_a_fazer(self):
        code, out = self.run_cli("day")
        self.assertEqual(code, 0)
        self.assertIn("Dias gerados: 2026-10-25, 2026-10-26, 2026-10-27 (108 ticks).", out)
        self.assertIn("Snapshot de 2026-10-27 guardado.", out)
        code, out = self.run_cli("day")
        self.assertEqual(code, 0)
        self.assertIn("Nada a fazer", out)
        self.assertEqual(self.fake.calls, [])

    def test_dia_fechado_por_arquivar_e_um_erro(self):
        with mock.patch("cnadump.cli.Generator.run_day", return_value=RunResult()):
            code, out = self.run_cli("day")
        self.assertEqual(code, 1)
        self.assertIn("O último dia fechado não ficou arquivado", out)

    def test_erro_duro_devolve_2_e_nao_escreve(self):
        self.world.price_history[3]["price"] = -1.0
        code, out = self.run_cli("day")
        self.assertEqual(code, 2)
        self.assertIn("ERRO: 2026-10-25: 1 preços não finitos ou não positivos", out)
        self.assertEqual(self.tree(), {})

    def test_configuracao_em_falta(self):
        code, out = self.run_cli("day", environ={})
        self.assertEqual(code, 1)
        self.assertIn("ERRO: SUPABASE_URL em falta", out)

    def test_data_invalida(self):
        code, out = self.run_cli("regenerate", "ontem")
        self.assertEqual(code, 1)
        self.assertIn("data inválida", out)

    def test_backfill_e_regenerate(self):
        code, out = self.run_cli("backfill", "2026-10-26")
        self.assertEqual(code, 0)
        self.assertIn("Dias gerados: 2026-10-26, 2026-10-27", out)
        self.assertNotIn("Snapshot", out)
        self.world.tick(D26, 12, 30, "NEWTE", "company", 99.0)
        self.assertEqual(self.run_cli("day", "2026-10-26")[0], 2)
        code, out = self.run_cli("regenerate", "2026-10-26")
        self.assertEqual(code, 0)
        self.assertIn("Dias gerados: 2026-10-26", out)

    def test_verify(self):
        self.run_cli("day")
        code, out = self.run_cli("verify")
        self.assertEqual((code, out), (0, "Repositório íntegro."))
        path = self.root / "prices/2026/2026-10-26.csv"
        path.write_bytes(path.read_bytes().replace(b"NEWTE", b"NEWTX", 1))
        code, out = self.run_cli("verify")
        self.assertEqual(code, 3)
        self.assertIn("ERRO:", out)

    def test_guard(self):
        code, out = self.run_cli("guard", stdin=io.StringIO("events.csv\ndocs/x.md\n"))
        self.assertEqual(code, 0)
        code, out = self.run_cli("guard", stdin=io.StringIO("prices/2026/2026-10-26.csv\nREADME.md\n"))
        self.assertEqual(code, 3)
        self.assertIn("ERRO: prices/2026/2026-10-26.csv", out)
        self.assertNotIn("README.md", out)

    def test_ping_sem_url_nao_falha(self):
        code, out = self.run_cli("ping", "fail")
        self.assertEqual(code, 0)
        self.assertIn("ping ignorado", out)

    def test_pending_adjust_e_build_pages(self):
        self.run_cli("day")
        code, out = self.run_cli("pending")
        self.assertEqual((code, out), (0, "Não há eventos estruturais por registar."))
        code, out = self.run_cli("adjust")
        self.assertEqual(code, 0)
        self.assertIn("já está atualizado", out)
        write_web(self.root)
        code, out = self.run_cli("build-pages")
        self.assertEqual(code, 0)
        self.assertIn("Site e API estática gerados", out)
        self.assertTrue((self.root / "_site/latest.json").is_file())
        self.assertTrue((self.root / "_site/index.html").is_file())
        code, out = self.run_cli("build-pages", environ=dict(ENV, GITHUB_REPOSITORY="CNAinput/dailydumps"))
        self.assertEqual(code, 0)
        self.assertIn("github.com/CNAinput/dailydumps", (self.root / "_site/api.html").read_text(encoding="utf-8"))

    def test_build_pages_sem_site_devolve_2(self):
        self.run_cli("day")
        code, out = self.run_cli("build-pages")
        self.assertEqual(code, 2)
        self.assertIn("web/index.html em falta", out)
        self.assertFalse((self.root / "_site").exists())

    def test_relogio_pode_vir_do_ambiente(self):
        environ = dict(ENV, CNADUMP_NOW="2026-10-26T23:30:00+00:00")
        self.world.sync_prices(until=local(date(2026, 10, 27), 0))
        self.fake = self.world.transport()
        lines = []
        code = main(["day"], root=self.root, environ=environ, transport=self.fake, out=lines.append)
        self.assertEqual(code, 0)
        self.assertIn("Dias gerados: 2026-10-25, 2026-10-26", "\n".join(lines))

    def test_avisos_em_github_actions(self):
        self.world.price_history[:] = [r for r in self.world.price_history if r["code"] != "ACSCP"]
        self.world.sync_prices()
        code, out = self.run_cli("day", environ=dict(ENV, GITHUB_ACTIONS="true"))
        self.assertEqual(code, 0)
        self.assertIn("::warning::2026-10-25: ACSCP (asset) sem ticks neste dia", out)
        self.assertNotIn("AVISO:", out)


if __name__ == "__main__":
    unittest.main()
