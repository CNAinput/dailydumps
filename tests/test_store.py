import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from cnadump.store import Repo, Transaction, sha256_hex, sums_text


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = Repo(self.root)

    def write(self, rel, data):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def files(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in sorted(self.root.rglob("*")) if p.is_file()}


class TransactionTests(RepoCase):
    def test_escreve_ficheiros_e_cria_pastas(self):
        tx = Transaction(self.repo)
        tx.put("prices/2026/2026-10-26.csv", b"a\n")
        tx.put("manifest.json", b"{}\n")
        self.assertEqual(tx.commit(), ["manifest.json", "prices/2026/2026-10-26.csv"])
        self.assertEqual(self.files(), {"prices/2026/2026-10-26.csv": b"a\n", "manifest.json": b"{}\n"})

    def test_nao_reescreve_o_que_nao_mudou(self):
        self.write("manifest.json", b"{}\n")
        tx = Transaction(self.repo)
        tx.put("manifest.json", b"{}\n")
        tx.put("status.json", b"{}\n")
        self.assertEqual(tx.commit(), ["status.json"])

    def test_os_bytes_sao_escritos_sem_alterar_fins_de_linha(self):
        tx = Transaction(self.repo)
        tx.put("manifest.json", b"a\nb\n")
        tx.commit()
        self.assertEqual((self.root / "manifest.json").read_bytes(), b"a\nb\n")

    def test_falha_a_meio_repoe_o_estado_anterior(self):
        self.write("manifest.json", b"velho")
        tx = Transaction(self.repo)
        tx.put("manifest.json", b"novo")
        tx.put("status.json", b"s")
        tx.put("taxes.json", b"t")
        real, calls = os.replace, {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disco cheio")
            return real(src, dst)

        with mock.patch("cnadump.store.os.replace", flaky):
            with self.assertRaises(OSError):
                tx.commit()
        self.assertEqual(self.files(), {"manifest.json": b"velho"})

    def test_get_prefere_o_que_esta_em_staging(self):
        self.write("manifest.json", b"velho")
        tx = Transaction(self.repo)
        self.assertEqual(tx.get("manifest.json"), b"velho")
        tx.put("manifest.json", b"novo")
        self.assertEqual(tx.get("manifest.json"), b"novo")
        self.assertIsNone(tx.get("nao-existe.json"))


class SumsTests(RepoCase):
    def test_lista_so_os_ficheiros_gerados_com_o_conteudo_em_staging(self):
        self.write("manifest.json", b"m\n")
        self.write("prices/2026/2026-10-26.csv", b"p\n")
        self.write("events.csv", b"e\n")
        self.write("docs/x.md", b"d\n")
        self.write("SHA256SUMS", b"antigo\n")
        tx = Transaction(self.repo)
        tx.put("status.json", b"s\n")
        tx.put("manifest.json", b"novo\n")
        lines = sums_text(tx).decode().splitlines()
        fim = b"\n"
        self.assertEqual(lines, [
            f"{sha256_hex(b'novo' + fim)}  manifest.json",
            f"{sha256_hex(b'p' + fim)}  prices/2026/2026-10-26.csv",
            f"{sha256_hex(b's' + fim)}  status.json",
        ])

    def test_formato_compativel_com_sha256sum(self):
        self.write("manifest.json", b"m\n")
        line = sums_text(Transaction(self.repo)).decode()
        digest, name = line.rstrip("\n").split("  ")
        self.assertEqual((len(digest), name), (64, "manifest.json"))


class RepoTests(RepoCase):
    def test_dias_com_ficheiro_ignoram_lixo(self):
        self.write("prices/2026/2026-10-26.csv", b"x")
        self.write("prices/2026/2026-10-27.csv", b"x")
        self.write("prices/2026/notas.txt", b"x")
        self.write("prices/2026/2026-1-5.csv", b"x")
        self.write("prices/2026/bad.csv", b"x")
        self.assertEqual(self.repo.price_days(), {date(2026, 10, 26), date(2026, 10, 27)})

    def test_repositorio_vazio(self):
        self.assertEqual(self.repo.price_days(), set())
        self.assertEqual(self.repo.snapshot_days(), [])
        self.assertEqual(self.repo.load_manifest(), {"schema_version": 1, "days": {}})
        self.assertEqual(self.repo.load_ohlc_rows(), [])

    def test_caminhos(self):
        day = date(2026, 3, 9)
        self.assertEqual(Repo.prices_rel(day), "prices/2026/2026-03-09.csv")
        self.assertEqual(Repo.snapshot_rel(day), "snapshots/2026-03-09.json")
        self.assertEqual(Repo.summary_rel(day), "summary/2026-03-09.json")


if __name__ == "__main__":
    unittest.main()
