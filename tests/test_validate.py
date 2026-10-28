import unittest
from datetime import date
from decimal import Decimal

from cnadump.model import Instrument, Tick
from cnadump.timeutil import day_window
from cnadump.validate import (
    build_ticks, check_current_prices, gap_warnings, missing_instrument_warnings,
)
from tests.builders import local

DAY = date(2026, 10, 26)
START, END = day_window(DAY)


def row(ts="2026-10-26T12:00:00.5+00:00", code="NEWTE", asset_type="company", price=1.5, guild=1):
    return {"timestamp": ts, "code": code, "asset_type": asset_type, "price": price, "guild_id": guild}


def tick(hour, minute, code="NEWTE", asset_type="company", price="1.5"):
    return Tick(local(DAY, hour, minute), code, asset_type, Decimal(price))


def instrument(code="NEWTE", asset_type="company", price="1.5", created=date(2026, 8, 1)):
    return Instrument(code, code, asset_type, False, None, Decimal(price), 1000, created)


class BuildTicksTests(unittest.TestCase):
    def build(self, rows):
        return build_ticks(rows, START, END, DAY)

    def test_linhas_validas_ficam_ordenadas(self):
        ticks, errors, guilds = self.build([row("2026-10-26T13:00:00+00:00", "B"), row("2026-10-26T12:00:00+00:00", "A")])
        self.assertEqual(errors, [])
        self.assertEqual([t.code for t in ticks], ["A", "B"])
        self.assertEqual(guilds, {1})

    def test_limites_da_janela(self):
        ticks, errors, _ = self.build([row("2026-10-26T00:00:00+00:00"), row("2026-10-27T00:00:00+00:00", "B")])
        self.assertEqual(len(ticks), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("timestamps fora da janela do dia", errors[0])

    def test_instante_antes_do_inicio_falha(self):
        _, errors, _ = self.build([row("2026-10-25T23:59:59.999999+00:00"), row()])
        self.assertIn("timestamps fora da janela do dia", errors[0])

    def test_precos_invalidos(self):
        for price in (-1.0, 0, 0.0, "NaN", "Infinity", "-Infinity"):
            ticks, errors, _ = self.build([row(price=price), row("2026-10-26T13:00:00+00:00")])
            self.assertEqual(len(ticks), 1, price)
            self.assertIn("preços não finitos ou não positivos", errors[0], price)

    def test_preco_ilegivel(self):
        _, errors, _ = self.build([row(price="abc"), row("2026-10-26T13:00:00+00:00")])
        self.assertIn("linhas ilegíveis", errors[0])

    def test_duplicados(self):
        ticks, errors, _ = self.build([row(), row(), row("2026-10-26T13:00:00+00:00")])
        self.assertEqual(len(ticks), 2)
        self.assertIn("ticks duplicados", errors[0])

    def test_mesmo_instante_em_instrumentos_diferentes_nao_e_duplicado(self):
        ticks, errors, _ = self.build([row(code="A"), row(code="B"), row(code="A", asset_type="asset")])
        self.assertEqual((len(ticks), errors), (3, []))

    def test_codigos_e_tipos_invalidos(self):
        _, errors, _ = self.build([row(code=""), row(code=" X"), row(asset_type="bond"), row("2026-10-26T14:00:00+00:00")])
        self.assertEqual(len(errors), 2)

    def test_campos_em_falta(self):
        _, errors, _ = self.build([{"code": "A"}, row("2026-10-26T14:00:00+00:00")])
        self.assertIn("linhas ilegíveis", errors[0])

    def test_dia_sem_nenhum_tick(self):
        ticks, errors, _ = self.build([])
        self.assertEqual(ticks, [])
        self.assertEqual(errors, ["2026-10-26: dia sem nenhum tick"])

    def test_erros_iguais_sao_agrupados_com_ate_tres_exemplos(self):
        rows = [row(f"2026-10-26T12:00:{n:02d}+00:00", price=-1) for n in range(10)] + [row("2026-10-26T13:00:00+00:00")]
        _, errors, _ = self.build(rows)
        self.assertEqual(len(errors), 1)
        self.assertIn("10 preços não finitos ou não positivos", errors[0])
        self.assertEqual(errors[0].count(";"), 2)

    def test_servidores_distintos_sao_reportados_ao_chamador(self):
        _, _, guilds = self.build([row(guild=1), row("2026-10-26T13:00:00+00:00", guild=2)])
        self.assertEqual(guilds, {1, 2})


class CurrentPriceTests(unittest.TestCase):
    def test_igual_nao_da_erro_mesmo_com_zeros_a_mais(self):
        self.assertEqual(check_current_prices(DAY, [tick(12, 0, price="64.4")], [instrument(price="64.40")]), [])

    def test_diferente_da_erro(self):
        errors = check_current_prices(DAY, [tick(12, 0, price="64.4")], [instrument(price="64.5")])
        self.assertEqual(len(errors), 1)
        self.assertIn("o último tick de NEWTE (company) é 64.4 mas o preço atual é 64.5", errors[0])

    def test_usa_o_ultimo_tick_do_dia(self):
        ticks = [tick(12, 0, price="9"), tick(20, 0, price="2")]
        self.assertEqual(check_current_prices(DAY, ticks, [instrument(price="2")]), [])
        self.assertEqual(len(check_current_prices(DAY, ticks, [instrument(price="9")])), 1)

    def test_instrumento_sem_ticks_nao_e_comparado(self):
        self.assertEqual(check_current_prices(DAY, [], [instrument()]), [])


class GapTests(unittest.TestCase):
    def hourly(self, start=11, end=22):
        return [tick(h, 0) for h in range(start, end + 1)]

    def test_ticks_de_hora_a_hora_nao_avisam(self):
        self.assertEqual(gap_warnings(DAY, self.hourly(), False), [])

    def test_lacuna_exatamente_de_2_horas_nao_avisa(self):
        ticks = [tick(h, 0) for h in (11, 13, 15, 17, 19, 21)]
        self.assertEqual(gap_warnings(DAY, ticks, False), [])

    def test_lacuna_de_2h30_ja_avisa(self):
        ticks = [tick(11, 0), tick(11, 30), tick(14, 0)] + [tick(h, 0) for h in range(15, 23)]
        warnings = gap_warnings(DAY, ticks, False)
        self.assertEqual(len(warnings), 1)
        self.assertIn("ficou 2h30 sem ticks, entre 11:30 e 14:00", warnings[0])

    def test_lacuna_maior_que_2_horas_avisa(self):
        ticks = [tick(h, 0) for h in (11, 12, 16, 17, 18, 19, 20, 21, 22)]
        warnings = gap_warnings(DAY, ticks, False)
        self.assertEqual(len(warnings), 1)
        self.assertIn("NEWTE (company) ficou 4h00 sem ticks, entre 12:00 e 16:00", warnings[0])

    def test_lacuna_no_inicio_do_dia(self):
        warnings = gap_warnings(DAY, [tick(h, 0) for h in range(15, 23)], False)
        self.assertIn("entre 11:00 e 15:00", warnings[0])

    def test_lacuna_no_fim_do_dia(self):
        warnings = gap_warnings(DAY, [tick(h, 0) for h in range(11, 18)], False)
        self.assertIn("entre 17:00 e 23:00", warnings[0])

    def test_dia_parcial_ignora_o_inicio(self):
        self.assertEqual(gap_warnings(DAY, [tick(h, 0) for h in range(15, 23)], True), [])

    def test_instrumento_criado_nesse_dia_ignora_o_inicio(self):
        ticks = [tick(h, 0) for h in range(15, 23)]
        self.assertEqual(gap_warnings(DAY, ticks, False, {("NEWTE", "company")}), [])
        self.assertEqual(len(gap_warnings(DAY, ticks, False, {("OUTRO", "company")})), 1)

    def test_instrumento_criado_nesse_dia_ainda_avisa_de_lacunas_a_seguir(self):
        ticks = [tick(15, 0), tick(16, 0), tick(21, 0), tick(22, 0)]
        warnings = gap_warnings(DAY, ticks, False, {("NEWTE", "company")})
        self.assertIn("entre 16:00 e 21:00", warnings[0])

    def test_tick_logo_a_seguir_as_23_nao_estraga_nada(self):
        ticks = self.hourly() + [Tick(local(DAY, 23, 0, 5), "NEWTE", "company", Decimal("1"))]
        self.assertEqual(gap_warnings(DAY, ticks, False), [])

    def test_um_aviso_por_instrumento(self):
        ticks = [tick(h, 0, code="A") for h in range(11, 23)] + [tick(11, 0, code="B")]
        warnings = gap_warnings(DAY, ticks, False)
        self.assertEqual(len(warnings), 1)
        self.assertIn("B (company)", warnings[0])


class MissingInstrumentTests(unittest.TestCase):
    def test_avisa_do_que_ja_existia_e_nao_tem_ticks(self):
        warnings = missing_instrument_warnings(DAY, [tick(12, 0)], [instrument(), instrument("OUTRA")])
        self.assertEqual(warnings, ["2026-10-26: OUTRA (company) sem ticks neste dia"])

    def test_nao_avisa_antes_da_criacao(self):
        novo = instrument("NOVA", created=date(2026, 10, 27))
        self.assertEqual(missing_instrument_warnings(DAY, [tick(12, 0)], [instrument(), novo]), [])

    def test_sem_data_de_criacao_avisa(self):
        sem_data = instrument("X", created=None)
        self.assertEqual(len(missing_instrument_warnings(DAY, [tick(12, 0)], [instrument(), sem_data])), 1)


if __name__ == "__main__":
    unittest.main()
