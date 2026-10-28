import unittest
from datetime import date
from decimal import Decimal

from cnadump import events as ev
from cnadump.model import Instrument, Tick
from cnadump.slugs import RESERVED, SLUG_RE, assign_slugs, base_slug
from cnadump.summary import build_summary
from cnadump.timeutil import parse_timestamp
from tests.builders import local

HEADER = "date,code,asset_type,event,factor,shares_before,shares_after,document_id,notes\n"


def parse(*lines):
    return ev.parse_events((HEADER + "".join(line + "\n" for line in lines)).encode("utf-8"))


class ParseEventsTests(unittest.TestCase):
    def test_eventos_validos(self):
        events, errors = parse(
            "2026-08-24,NEWTE,company,split,4,8000,32000,69,\"nota, com virgula\"",
            "2026-10-11,P&PNV,asset,issuance,,250000,750000,83,",
            "2026-10-12,NOVA,company,ipo,,,1000,,",
            "2026-10-13,VELHA,company,delisting,,500,,,",
        )
        self.assertEqual(errors, [])
        self.assertEqual([e.event for e in events], ["split", "issuance", "ipo", "delisting"])
        self.assertEqual(events[0].factor, Decimal("4"))
        self.assertEqual(events[0].notes, "nota, com virgula")
        self.assertEqual(events[1].document_id, 83)
        self.assertIsNone(events[2].shares_before)

    def test_ficheiro_so_com_cabecalho(self):
        self.assertEqual(parse(), ([], []))

    def test_cabecalho_errado(self):
        events, errors = ev.parse_events(b"a,b,c\n")
        self.assertEqual(events, [])
        self.assertIn("cabeçalho inválido", errors[0])

    def invalid(self, line, text):
        events, errors = parse(line)
        self.assertEqual(len(errors), 1, line)
        self.assertIn(text, errors[0], line)

    def test_linhas_invalidas(self):
        self.invalid("2026-08-24,NEWTE,company,split,4,8000", "colunas")
        self.invalid("24/08/2026,NEWTE,company,split,4,,,,", "data inválida")
        self.invalid("2026-08-24,NEWTE,bond,split,4,,,,", "asset_type")
        self.invalid("2026-08-24,NEWTE,company,fusao,4,,,,", "event tem de ser")
        self.invalid("2026-08-24,,company,split,4,,,,", "code vazio")
        self.invalid("2026-08-24,NEWTE,company,split,,,,,", "precisa de factor")
        self.invalid("2026-08-24,NEWTE,company,issuance,2,1,2,,", "só os splits têm factor")
        self.invalid("2026-08-24,NEWTE,company,split,1,,,,", "diferente de 1")
        self.invalid("2026-08-24,NEWTE,company,split,0,,,,", "positivo")
        self.invalid("2026-08-24,NEWTE,company,split,abc,,,,", "factor inválido")
        self.invalid("2026-08-24,NEWTE,company,split,4,8000,30000,,", "shares_before vezes o factor")
        self.invalid("2026-08-24,NEWTE,company,issuance,,500,500,,", "maior que shares_before")
        self.invalid("2026-08-24,NEWTE,company,issuance,,-5,10,,", "shares_before")
        self.invalid("2026-08-24,NEWTE,company,ipo,,,,0,", "document_id")

    def test_split_inverso_e_aceite(self):
        events, errors = parse("2026-08-24,NEWTE,company,split,0.5,1000,500,,")
        self.assertEqual((len(events), errors), (1, []))

    def test_datas_fora_de_ordem(self):
        _, errors = parse("2026-08-25,A,company,ipo,,,,,", "2026-08-24,B,company,ipo,,,,,")
        self.assertIn("fora de ordem", errors[0])

    def test_linha_repetida(self):
        _, errors = parse("2026-08-24,A,company,ipo,,,,,", "2026-08-24,A,company,ipo,,,,,")
        self.assertIn("repetida", errors[0])

    def test_varios_eventos_no_mesmo_dia_mantem_a_ordem(self):
        events, errors = parse(
            "2026-10-11,NEWTE,company,issuance,,32000,75000,84,",
            "2026-10-11,NEWTE,company,split,4,75000,300000,84,",
        )
        self.assertEqual(errors, [])
        self.assertEqual([e.event for e in events], ["issuance", "split"])


def split(day, code="NEWTE", factor="4", asset_type="company"):
    return ev.Event(day, code, asset_type, "split", Decimal(factor), None, None, None, "")


def row(day, code="NEWTE", asset_type="company", prices=("20", "24", "18", "22"), ticks="10"):
    return [day, code, asset_type, *prices, ticks]


class AdjustTests(unittest.TestCase):
    def generated(self, **days):
        return {day: parse_timestamp(stamp) for day, stamp in days.items()}

    def test_ajusta_so_o_que_foi_gerado_antes_do_evento(self):
        rows = [row("2026-10-21"), row("2026-10-22"), row("2026-10-23")]
        stamps = self.generated(**{
            "2026-10-21": "2026-10-21T22:17:00Z",
            "2026-10-22": "2026-10-22T22:17:00Z",
            "2026-10-23": "2026-10-23T22:17:00Z",
        })
        out = ev.adjust_ohlc(rows, [split(date(2026, 10, 23))], stamps)
        self.assertEqual(out[0][3:7], ["5.00", "6.00", "4.50", "5.50"])
        self.assertEqual(out[1][3:7], ["5.00", "6.00", "4.50", "5.50"])
        self.assertEqual(out[2], rows[2])

    def test_fronteira_exata_o_evento_comeca_a_meia_noite_de_lisboa(self):
        rows = [row("2026-10-22")]
        antes = self.generated(**{"2026-10-22": "2026-10-22T22:59:59Z"})
        igual = self.generated(**{"2026-10-22": "2026-10-22T23:00:00Z"})
        self.assertNotEqual(ev.adjust_ohlc(rows, [split(date(2026, 10, 23))], antes)[0], rows[0])
        self.assertEqual(ev.adjust_ohlc(rows, [split(date(2026, 10, 23))], igual)[0], rows[0])

    def test_dia_regenerado_depois_do_split_nao_e_ajustado_outra_vez(self):
        rows = [row("2026-10-22", prices=("5", "6", "4.5", "5.5"))]
        regenerado = self.generated(**{"2026-10-22": "2026-10-25T09:00:00Z"})
        self.assertEqual(ev.adjust_ohlc(rows, [split(date(2026, 10, 23))], regenerado), rows)

    def test_varios_splits_multiplicam(self):
        rows = [row("2026-10-01", prices=("24", "24", "24", "24"))]
        stamps = self.generated(**{"2026-10-01": "2026-10-01T22:00:00Z"})
        out = ev.adjust_ohlc(rows, [split(date(2026, 10, 5), factor="2"), split(date(2026, 10, 9), factor="3")], stamps)
        self.assertEqual(out[0][3], "4.00")

    def test_so_ajusta_o_instrumento_certo(self):
        rows = [row("2026-10-21"), row("2026-10-21", code="OUTRA"), row("2026-10-21", asset_type="asset")]
        stamps = self.generated(**{"2026-10-21": "2026-10-21T22:00:00Z"})
        out = ev.adjust_ohlc(rows, [split(date(2026, 10, 23))], stamps)
        self.assertEqual(out[0][3], "5.00")
        self.assertEqual(out[1], rows[1])
        self.assertEqual(out[2], rows[2])

    def test_split_inverso_multiplica_o_preco(self):
        rows = [row("2026-10-21", prices=("5", "5", "5", "5"))]
        stamps = self.generated(**{"2026-10-21": "2026-10-21T22:00:00Z"})
        out = ev.adjust_ohlc(rows, [split(date(2026, 10, 23), factor="0.5")], stamps)
        self.assertEqual(out[0][3], "10.00")

    def test_arredondamento_a_4_casas_sem_zeros_a_mais(self):
        rows = [row("2026-10-21", prices=("79.89", "80", "1", "10"))]
        stamps = self.generated(**{"2026-10-21": "2026-10-21T22:00:00Z"})
        out = ev.adjust_ohlc(rows, [split(date(2026, 10, 23))], stamps)
        self.assertEqual(out[0][3:7], ["19.9725", "20.00", "0.25", "2.50"])
        out = ev.adjust_ohlc(rows, [split(date(2026, 10, 23), factor="3")], stamps)
        self.assertEqual(out[0][3], "26.63")

    def test_dia_sem_registo_de_geracao_fica_como_esta(self):
        rows = [row("2026-10-21")]
        self.assertEqual(ev.adjust_ohlc(rows, [split(date(2026, 10, 23))], {}), rows)

    def test_emissoes_nao_ajustam_precos(self):
        emissao = ev.Event(date(2026, 10, 23), "NEWTE", "company", "issuance", None, 1, 2, None, "")
        rows = [row("2026-10-21")]
        stamps = self.generated(**{"2026-10-21": "2026-10-21T22:00:00Z"})
        self.assertEqual(ev.adjust_ohlc(rows, [emissao], stamps), rows)

    def test_sem_eventos_copia_tudo(self):
        rows = [row("2026-10-21")]
        out = ev.adjust_ohlc(rows, [], {})
        self.assertEqual(out, rows)
        self.assertIsNot(out[0], rows[0])


class SlugTests(unittest.TestCase):
    def test_slugs_base(self):
        self.assertEqual(base_slug("P&P10"), "p-and-p10")
        self.assertEqual(base_slug("P&PNV"), "p-and-pnv")
        self.assertEqual(base_slug("2020T"), "2020t")
        self.assertEqual(base_slug("CréditoFácil"), "creditofacil")
        self.assertEqual(base_slug("a  b/c"), "a-b-c")

    def test_codigo_sem_caracteres_utilizaveis_usa_hash_estavel(self):
        slug = base_slug("???")
        self.assertTrue(slug.startswith("i-"))
        self.assertEqual(slug, base_slug("???"))
        self.assertNotEqual(slug, base_slug("!!!"))

    def test_sem_colisoes_e_todos_seguros(self):
        keys = [
            ("A&B", "company"), ("A-AND-B", "company"), ("a&b", "asset"), ("A&B", "asset"),
            ("P&P10", "asset"), ("P&PNV", "asset"), ("NEWTE", "company"), ("NEWTE", "asset"),
        ]
        slugs = assign_slugs(keys)
        self.assertEqual(set(slugs), set(keys))
        self.assertEqual(len(set(slugs.values())), len(keys))
        for slug in slugs.values():
            self.assertRegex(slug, SLUG_RE)

    def test_o_slug_simples_fica_para_o_primeiro_e_os_outros_ganham_o_tipo(self):
        slugs = assign_slugs([("NEWTE", "company"), ("NEWTE", "asset")])
        self.assertEqual(slugs[("NEWTE", "asset")], "newte")
        self.assertEqual(slugs[("NEWTE", "company")], "newte-company")

    def test_slugs_ja_atribuidos_nao_mudam_quando_aparece_um_colidente(self):
        antes = assign_slugs([("A-AND-B", "company")])
        depois = assign_slugs([("A&B", "company"), ("A-AND-B", "company")], antes)
        self.assertEqual(depois[("A-AND-B", "company")], antes[("A-AND-B", "company")])
        self.assertNotEqual(depois[("A&B", "company")], depois[("A-AND-B", "company")])

    def test_nomes_reservados_do_windows(self):
        slugs = assign_slugs([("CON", "company"), ("COM1", "asset"), ("NUL", "company")])
        for slug in slugs.values():
            self.assertNotIn(slug, RESERVED)

    def test_determinismo(self):
        keys = [("B", "company"), ("A", "asset"), ("A", "company")]
        self.assertEqual(assign_slugs(keys), assign_slugs(list(reversed(keys))))

    def test_slug_anterior_invalido_e_ignorado(self):
        slugs = assign_slugs([("X", "company")], {("X", "company"): "Mau Slug/.."})
        self.assertEqual(slugs[("X", "company")], "x")


def meta(code, asset_type="company", is_index=False, name=None):
    return Instrument(code, name or code, asset_type, is_index, None, Decimal(1), 1000, None)


def ticks_of(code, prices, asset_type="company"):
    return [Tick(local(date(2026, 10, 26), 11 + i), code, asset_type, Decimal(str(p))) for i, p in enumerate(prices)]


def snapshot_of(items):
    return {"instruments": [
        {"code": c, "name": f"Nome {c}", "asset_type": t, "is_index": i, "market_cap": Decimal(str(cap))}
        for c, t, i, cap in items
    ]}


DAY = date(2026, 10, 26)


class SummaryTests(unittest.TestCase):
    def test_indices_subida_e_descida(self):
        ticks = (ticks_of("P&P10", [100, 101], "asset") + ticks_of("UP", [10, 11]) + ticks_of("DOWN", [10, 9])
                 + ticks_of("FLAT", [10, 10.02]))
        metas = {("P&P10", "asset"): meta("P&P10", "asset", True, "Índice P&P10")}
        summary = build_summary(DAY, ticks, metas, None)
        self.assertEqual(summary["indices"], [{
            "code": "P&P10", "name": "Índice P&P10", "open": Decimal("100"), "close": Decimal("101"),
            "change_pct": Decimal("1.00"),
        }])
        self.assertEqual(summary["biggest_riser"]["code"], "UP")
        self.assertEqual(summary["biggest_riser"]["change_pct"], Decimal("10.00"))
        self.assertEqual(summary["biggest_faller"]["code"], "DOWN")
        self.assertEqual(summary["biggest_faller"]["change_pct"], Decimal("-10.00"))
        self.assertFalse(summary["calm_day"])

    def test_indices_nao_entram_nos_destaques(self):
        ticks = ticks_of("P&P10", [100, 150], "asset") + ticks_of("A", [10, 10.1])
        summary = build_summary(DAY, ticks, {("P&P10", "asset"): meta("P&P10", "asset", True)}, None)
        self.assertEqual(summary["biggest_riser"]["code"], "A")

    def test_limiar_de_0_05_por_cento(self):
        ticks = ticks_of("A", [10000, 10005]) + ticks_of("B", [10000, 9995])
        summary = build_summary(DAY, ticks, {}, None)
        self.assertIsNone(summary["biggest_riser"])
        self.assertIsNone(summary["biggest_faller"])
        self.assertTrue(summary["calm_day"])
        ticks = ticks_of("A", [10000, 10006]) + ticks_of("B", [10000, 9994])
        summary = build_summary(DAY, ticks, {}, None)
        self.assertEqual(summary["biggest_riser"]["code"], "A")
        self.assertEqual(summary["biggest_faller"]["code"], "B")

    def test_com_um_so_instrumento_nao_ha_descida(self):
        summary = build_summary(DAY, ticks_of("A", [10, 9]), {}, None)
        self.assertIsNone(summary["biggest_riser"])
        self.assertIsNone(summary["biggest_faller"])
        summary = build_summary(DAY, ticks_of("A", [10, 11]), {}, None)
        self.assertEqual(summary["biggest_riser"]["code"], "A")
        self.assertIsNone(summary["biggest_faller"])

    def test_desempate_por_codigo(self):
        ticks = ticks_of("B", [10, 11]) + ticks_of("A", [10, 11]) + ticks_of("D", [10, 9]) + ticks_of("C", [10, 9])
        summary = build_summary(DAY, ticks, {}, None)
        self.assertEqual(summary["biggest_riser"]["code"], "A")
        self.assertEqual(summary["biggest_faller"]["code"], "C")

    def test_variacao_e_face_ao_primeiro_tick_do_dia(self):
        summary = build_summary(DAY, ticks_of("A", [10, 50, 5, 12]), {}, None)
        self.assertEqual(summary["biggest_riser"]["open"], Decimal("10"))
        self.assertEqual(summary["biggest_riser"]["close"], Decimal("12"))
        self.assertEqual(summary["biggest_riser"]["change_pct"], Decimal("20.00"))

    def test_sem_snapshot_nao_ha_capitalizacao(self):
        summary = build_summary(DAY, ticks_of("A", [10, 11]), {}, None)
        self.assertFalse(summary["market_cap_available"])
        self.assertIsNone(summary["top_market_cap"])
        self.assertIsNone(summary["total_market_cap"])
        self.assertIsNone(summary["companies_count"])

    def test_top_3_so_com_empresas_com_capitalizacao(self):
        snap = snapshot_of([
            ("A", "company", False, 100), ("B", "company", False, 300), ("C", "company", False, 200),
            ("D", "company", False, 50), ("E", "company", False, 0), ("F", "asset", False, 9999),
            ("G", "asset", True, 99999),
        ])
        summary = build_summary(DAY, ticks_of("A", [1, 1]), {}, snap)
        self.assertTrue(summary["market_cap_available"])
        self.assertEqual([(t["rank"], t["code"]) for t in summary["top_market_cap"]], [(1, "B"), (2, "C"), (3, "A")])
        self.assertEqual(summary["total_market_cap"], Decimal("650.00"))
        self.assertEqual(summary["companies_count"], 5)

    def test_empate_na_capitalizacao_desempata_por_codigo(self):
        snap = snapshot_of([("B", "company", False, 100), ("A", "company", False, 100)])
        summary = build_summary(DAY, ticks_of("A", [1, 1]), {}, snap)
        self.assertEqual([t["code"] for t in summary["top_market_cap"]], ["A", "B"])

    def test_instrumento_sem_metadados_conta_como_normal(self):
        summary = build_summary(DAY, ticks_of("VELHO", [10, 12]), {}, None)
        self.assertEqual(summary["biggest_riser"]["code"], "VELHO")
        self.assertIsNone(summary["biggest_riser"]["name"])


if __name__ == "__main__":
    unittest.main()
