import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from cnadump import config, fmt
from cnadump.errors import ConfigError


class DecimalTests(unittest.TestCase):
    def test_conversoes(self):
        self.assertEqual(fmt.to_decimal(5), Decimal("5"))
        self.assertEqual(fmt.to_decimal(74.44), Decimal("74.44"))
        self.assertEqual(fmt.to_decimal(" 1.50 "), Decimal("1.50"))
        for lixo in (True, None, "abc", [1]):
            with self.assertRaises(ValueError, msg=repr(lixo)):
                fmt.to_decimal(lixo)

    def test_texto_sem_expoente(self):
        self.assertEqual(fmt.plain(Decimal("1E-7")), "0.0000001")
        self.assertEqual(fmt.plain(Decimal("64.40")), "64.40")
        self.assertEqual(fmt.plain(Decimal("-0.00")), "0.00")
        with self.assertRaises(ValueError):
            fmt.plain(Decimal("NaN"))
        with self.assertRaises(ValueError):
            fmt.plain(Decimal("Infinity"))

    def test_arredondamento_metade_para_cima(self):
        self.assertEqual(fmt.quantize("0.125", 2), Decimal("0.13"))
        self.assertEqual(fmt.quantize("2.5", 0), Decimal("3"))
        self.assertEqual(fmt.quantize("1914320.505", 2), Decimal("1914320.51"))

    def test_zeros_finais(self):
        self.assertEqual(fmt.tidy(Decimal("19.9725")), "19.9725")
        self.assertEqual(fmt.tidy(Decimal("12.5000")), "12.50")
        self.assertEqual(fmt.tidy(Decimal("20")), "20.00")
        self.assertEqual(fmt.tidy(Decimal("3.1000"), min_places=0), "3.1")


class CsvTests(unittest.TestCase):
    def test_fim_de_linha_lf_e_citacao_minima(self):
        data = fmt.csv_bytes(["a", "b"], [["P&P10", "x,y"], ["1", 'diz "oi"']])
        self.assertEqual(data, b'a,b\nP&P10,"x,y"\n1,"diz ""oi"""\n')
        self.assertNotIn(b"\r", data)

    def test_ida_e_volta(self):
        linhas = [["2026-10-27", "P&P10", "asset", "64.4"], ["2026-10-27", "x,y", "company", "1"]]
        header, rows = fmt.read_csv(fmt.csv_bytes(["date", "code", "asset_type", "price"], linhas))
        self.assertEqual(header, ["date", "code", "asset_type", "price"])
        self.assertEqual(rows, linhas)

    def test_ficheiro_vazio(self):
        self.assertEqual(fmt.read_csv(b""), ([], []))


class JsonTests(unittest.TestCase):
    def test_decimais_passam_a_numeros_exatos(self):
        data = fmt.json_bytes({"preco": Decimal("64.4"), "acoes": Decimal("100000"), "cap": Decimal("12.50")})
        self.assertEqual(data, b'{\n  "preco": 64.4,\n  "acoes": 100000,\n  "cap": 12.5\n}\n')

    def test_acentos_sem_escape_e_ordem_mantida(self):
        data = fmt.json_bytes({"z": "Índice", "a": [Decimal("1.5")]})
        self.assertIn("Índice".encode("utf-8"), data)
        self.assertLess(data.index(b'"z"'), data.index(b'"a"'))

    def test_numero_sem_representacao_exata_falha(self):
        with self.assertRaises(ValueError):
            fmt.json_bytes({"x": Decimal("0.1234567890123456789")})

    def test_nao_finito_falha(self):
        with self.assertRaises(ValueError):
            fmt.json_bytes({"x": Decimal("NaN")})


class ConfigTests(unittest.TestCase):
    def test_ficheiro_env(self):
        valores = config.parse_env_file(
            '# comentario\nSUPABASE_URL="https://x.supabase.co"\nexport SUPABASE_ANON_KEY=abc\n\nlixo\nHEALTHCHECK_URL=\n'
        )
        self.assertEqual(valores["SUPABASE_URL"], "https://x.supabase.co")
        self.assertEqual(valores["SUPABASE_ANON_KEY"], "abc")
        self.assertEqual(valores["HEALTHCHECK_URL"], "")

    def test_ambiente_tem_prioridade_sobre_o_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text("SUPABASE_URL=https://a.co\nSUPABASE_ANON_KEY=velha\n", encoding="utf-8")
            definicoes = config.load_settings(tmp, {"SUPABASE_ANON_KEY": "nova"})
        self.assertEqual(definicoes.url, "https://a.co")
        self.assertEqual(definicoes.key, "nova")

    def test_variavel_vazia_nao_apaga_o_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text("SUPABASE_URL=https://a.co\nSUPABASE_ANON_KEY=k\n", encoding="utf-8")
            definicoes = config.load_settings(tmp, {"SUPABASE_ANON_KEY": ""})
        self.assertEqual(definicoes.key, "k")

    def test_barra_final_do_url_e_removida(self):
        with tempfile.TemporaryDirectory() as tmp:
            definicoes = config.load_settings(tmp, {"SUPABASE_URL": "https://a.co/", "SUPABASE_ANON_KEY": "k"})
        self.assertEqual(definicoes.url, "https://a.co")

    def test_em_falta_da_erro_em_portugues(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError) as ctx:
                config.load_settings(tmp, {})
            self.assertIn("SUPABASE_URL", str(ctx.exception))
            with self.assertRaises(ConfigError) as ctx:
                config.load_settings(tmp, {"SUPABASE_URL": "https://a.co"})
            self.assertIn("SUPABASE_ANON_KEY", str(ctx.exception))

    def test_url_de_ping_pode_faltar(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(config.healthcheck_url(tmp, {}), "")
            self.assertEqual(config.healthcheck_url(tmp, {"HEALTHCHECK_URL": " https://hc.io/x "}), "https://hc.io/x")


if __name__ == "__main__":
    unittest.main()
