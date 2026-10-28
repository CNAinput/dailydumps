import json
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from cnadump import events as ev
from cnadump.errors import DumpError, ValidationError
from cnadump.fmt import json_bytes
from cnadump.model import Instrument
from cnadump.pending import (
    diff_snapshots, is_covered, issue_for, open_pending_issues, pending_changes, pending_issues, suggestion,
)
from cnadump.snapshot import build_snapshot
from cnadump.store import Repo
from cnadump.timeutil import parse_date

HEADER = "date,code,asset_type,event,factor,shares_before,shares_after,document_id,notes\n"


def snapshot(day, *items):
    """Cada item é (código, tipo, preço, shares_total)."""
    instruments = [Instrument(c, c, t, False, None, Decimal(p), s, None) for c, t, p, s in items]
    stamp = datetime(day.year, day.month, day.day, 22, 17, tzinfo=timezone.utc)
    return build_snapshot(day, stamp, instruments, {})


class PendingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = Repo(self.root)

    def save(self, snap):
        path = self.root / self.repo.snapshot_rel(parse_date(snap["date"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json_bytes(snap))

    def events(self, *lines):
        (self.root / "events.csv").write_text(HEADER + "".join(line + "\n" for line in lines), encoding="utf-8")


D12, D13, D14 = date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)


class DiffTests(unittest.TestCase):
    def test_sem_alteracoes(self):
        a = snapshot(D12, ("A", "company", "5", 1000))
        b = snapshot(D13, ("A", "company", "6", 1000))
        self.assertEqual(diff_snapshots(a, b), [])

    def test_shares_total_mudou(self):
        a = snapshot(D12, ("ACHIP", "company", "5.29", 15000))
        b = snapshot(D13, ("ACHIP", "company", "5.29", 125000))
        (change,) = diff_snapshots(a, b)
        self.assertEqual((change.kind, change.code, change.date_from, change.date_to), ("shares", "ACHIP", D12, D13))

    def test_codigo_novo_e_codigo_desaparecido(self):
        a = snapshot(D12, ("VELHA", "company", "5", 100), ("IGUAL", "asset", "1", 10))
        b = snapshot(D13, ("NOVA", "company", "5", 200), ("IGUAL", "asset", "1", 10))
        kinds = {(c.kind, c.code) for c in diff_snapshots(a, b)}
        self.assertEqual(kinds, {("appeared", "NOVA"), ("disappeared", "VELHA")})

    def test_o_mesmo_codigo_com_outro_tipo_conta_como_instrumento_novo(self):
        a = snapshot(D12, ("X", "company", "5", 100))
        b = snapshot(D13, ("X", "asset", "5", 100))
        self.assertEqual({(c.kind, c.asset_type) for c in diff_snapshots(a, b)}, {("appeared", "asset"), ("disappeared", "company")})


class CoverageTests(PendingCase):
    def change(self):
        a = snapshot(D12, ("ACHIP", "company", "5.29", 15000))
        b = snapshot(D13, ("ACHIP", "company", "5.29", 125000))
        return diff_snapshots(a, b)[0]

    def covered(self, line):
        events, errors = ev.parse_events((HEADER + line + "\n").encode("utf-8"))
        self.assertEqual(errors, [])
        return is_covered(self.change(), events)

    def test_evento_do_tipo_certo_dentro_do_intervalo_cobre(self):
        self.assertTrue(self.covered("2026-10-13,ACHIP,company,issuance,,15000,125000,86,"))
        self.assertTrue(self.covered("2026-10-12,ACHIP,company,issuance,,15000,125000,86,"))

    def test_data_fora_do_intervalo_nao_cobre(self):
        self.assertFalse(self.covered("2026-10-14,ACHIP,company,issuance,,15000,125000,86,"))
        self.assertFalse(self.covered("2026-10-11,ACHIP,company,issuance,,15000,125000,86,"))

    def test_tipo_de_evento_errado_nao_cobre(self):
        self.assertFalse(self.covered("2026-10-13,ACHIP,company,ipo,,,125000,,"))

    def test_outro_instrumento_nao_cobre(self):
        self.assertFalse(self.covered("2026-10-13,NEWTE,company,issuance,,1,2,,"))
        self.assertFalse(self.covered("2026-10-13,ACHIP,asset,issuance,,15000,125000,,"))

    def test_split_tambem_cobre_uma_mudanca_de_shares(self):
        self.assertTrue(self.covered("2026-10-13,ACHIP,company,split,2,15000,30000,,"))


class SuggestionTests(unittest.TestCase):
    def sug(self, first, second):
        (change,) = diff_snapshots(snapshot(D12, first), snapshot(D13, second))
        return suggestion(change)

    def parses(self, line):
        events, errors = ev.parse_events((HEADER + line + "\n").encode("utf-8"))
        self.assertEqual(errors, [], line)
        return events[0]

    def test_emissao_quando_o_preco_nao_muda(self):
        line = self.sug(("ACHIP", "company", "5.29", 15000), ("ACHIP", "company", "5.29", 125000))
        self.assertEqual(line, "2026-10-13,ACHIP,company,issuance,,15000,125000,,")
        self.assertEqual(self.parses(line).event, "issuance")

    def test_split_quando_o_preco_cai_na_mesma_proporcao(self):
        line = self.sug(("NEWTE", "company", "80", 8000), ("NEWTE", "company", "20", 32000))
        self.assertEqual(line, "2026-10-13,NEWTE,company,split,4,8000,32000,,")
        self.assertEqual(self.parses(line).factor, Decimal(4))

    def test_split_inverso(self):
        line = self.sug(("X", "company", "10", 1000), ("X", "company", "20", 500))
        self.assertEqual(line, "2026-10-13,X,company,split,0.5,1000,500,,")
        self.parses(line)

    def test_ipo_e_delisting(self):
        a = snapshot(D12, ("VELHA", "company", "5", 100))
        b = snapshot(D13, ("NOVA", "asset", "5", 200))
        lines = sorted(suggestion(c) for c in diff_snapshots(a, b))
        self.assertEqual(lines, ["2026-10-13,NOVA,asset,ipo,,,200,,", "2026-10-13,VELHA,company,delisting,,100,,,"])
        for line in lines:
            self.parses(line)

    def test_codigo_com_virgula_fica_citado(self):
        a = snapshot(D12)
        b = snapshot(D13, ("A,B", "company", "5", 100))
        line = suggestion(diff_snapshots(a, b)[0])
        self.assertTrue(line.startswith('2026-10-13,"A,B",company'))
        self.assertEqual(self.parses(line).code, "A,B")


class PendingChangesTests(PendingCase):
    def test_menos_de_dois_snapshots(self):
        self.assertEqual(pending_changes(self.repo), [])
        self.save(snapshot(D12, ("A", "company", "5", 100)))
        self.assertEqual(pending_changes(self.repo), [])

    def test_so_aparecem_as_mudancas_nao_cobertas_em_todo_o_historico(self):
        self.save(snapshot(D12, ("A", "company", "5", 100), ("B", "company", "5", 100)))
        self.save(snapshot(D13, ("A", "company", "5", 200), ("B", "company", "5", 100)))
        self.save(snapshot(D14, ("A", "company", "5", 200), ("B", "company", "5", 300)))
        self.events("2026-10-13,A,company,issuance,,100,200,,")
        found = pending_changes(self.repo)
        self.assertEqual([(c.code, c.date_to) for c in found], [("B", D14)])

    def test_events_invalido_e_um_erro(self):
        self.save(snapshot(D12, ("A", "company", "5", 100)))
        self.save(snapshot(D13, ("A", "company", "5", 100)))
        (self.root / "events.csv").write_text("lixo\n", encoding="utf-8")
        with self.assertRaises(ValidationError):
            pending_changes(self.repo)


class IssueTests(PendingCase):
    def test_titulo_estavel_e_corpo_em_portugues_sem_travessoes(self):
        self.save(snapshot(D12, ("ACHIP", "company", "5.29", 15000)))
        self.save(snapshot(D13, ("ACHIP", "company", "5.29", 125000), ("NOVA", "asset", "1", 10)))
        (issue,) = pending_issues(self.repo)
        self.assertEqual(issue.title, "Eventos por registar em events.csv (2026-10-13)")
        self.assertEqual(pending_issues(self.repo)[0].title, issue.title)
        self.assertIn("`ACHIP` (company): `shares_total` passou de 15000 para 125000", issue.body)
        self.assertIn("`NOVA` (asset): apareceu", issue.body)
        self.assertIn("2026-10-13,ACHIP,company,issuance,,15000,125000,,", issue.body)
        for forbidden in (chr(0x2014), chr(0x2013), "-" * 2):
            self.assertNotIn(forbidden, issue.body)

    def test_uma_issue_por_dia(self):
        self.save(snapshot(D12, ("A", "company", "5", 100)))
        self.save(snapshot(D13, ("A", "company", "5", 200)))
        self.save(snapshot(D14, ("A", "company", "5", 300)))
        self.assertEqual([i.title[-11:-1] for i in pending_issues(self.repo)], ["2026-10-13", "2026-10-14"])

    def test_issue_for_junta_varias_mudancas(self):
        a = snapshot(D12, ("A", "company", "5", 100), ("B", "company", "5", 100))
        b = snapshot(D13, ("A", "company", "5", 200), ("B", "company", "5", 400))
        issue = issue_for("2026-10-13", diff_snapshots(a, b))
        self.assertIn("`A`", issue.body)
        self.assertIn("`B`", issue.body)


class FakeGh:
    def __init__(self, existing=(), list_rc=0, create_rc=0, missing=False):
        self.existing, self.list_rc, self.create_rc, self.missing = list(existing), list_rc, create_rc, missing
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if self.missing:
            raise FileNotFoundError("gh")
        if args[1:3] == ["issue", "list"]:
            return subprocess.CompletedProcess(args, self.list_rc, json.dumps([{"title": t} for t in self.existing]), "falhou")
        return subprocess.CompletedProcess(args, self.create_rc, "", "falhou")


class OpenIssuesTests(PendingCase):
    def setUp(self):
        super().setUp()
        self.save(snapshot(D12, ("ACHIP", "company", "5.29", 15000)))
        self.save(snapshot(D13, ("ACHIP", "company", "5.29", 125000)))
        self.title = "Eventos por registar em events.csv (2026-10-13)"
        self.logs = []

    def test_abre_a_issue_com_o_titulo_estavel(self):
        gh = FakeGh()
        created = open_pending_issues(self.repo, gh, self.logs.append)
        self.assertEqual(created, [self.title])
        create = [c for c in gh.calls if c[1:3] == ["issue", "create"]]
        self.assertEqual(len(create), 1)
        self.assertEqual(create[0][create[0].index("--title") + 1], self.title)

    def test_nao_duplica_uma_issue_que_ja_existe_aberta_ou_fechada(self):
        gh = FakeGh(existing=[self.title, "outra coisa"])
        self.assertEqual(open_pending_issues(self.repo, gh, self.logs.append), [])
        self.assertEqual([c[1:3] for c in gh.calls], [["issue", "list"]])
        self.assertIn("--state", gh.calls[0])
        self.assertEqual(gh.calls[0][gh.calls[0].index("--state") + 1], "all")

    def test_titulo_parecido_nao_conta_como_existente(self):
        gh = FakeGh(existing=["Eventos por registar em events.csv (2026-10-12)"])
        self.assertEqual(len(open_pending_issues(self.repo, gh, self.logs.append)), 1)

    def test_sem_nada_por_registar_nao_chama_o_gh(self):
        self.events("2026-10-13,ACHIP,company,issuance,,15000,125000,,")
        gh = FakeGh()
        self.assertEqual(open_pending_issues(self.repo, gh, self.logs.append), [])
        self.assertEqual(gh.calls, [])

    def test_gh_em_falta(self):
        with self.assertRaises(DumpError) as ctx:
            open_pending_issues(self.repo, FakeGh(missing=True), self.logs.append)
        self.assertIn("gh não está instalado", str(ctx.exception))

    def test_falhas_do_gh(self):
        with self.assertRaises(DumpError):
            open_pending_issues(self.repo, FakeGh(list_rc=1), self.logs.append)
        with self.assertRaises(DumpError):
            open_pending_issues(self.repo, FakeGh(create_rc=1), self.logs.append)


if __name__ == "__main__":
    unittest.main()
