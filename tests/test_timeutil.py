import unittest
from datetime import date, datetime, timedelta, timezone

from cnadump import timeutil as t


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class DayWindowTests(unittest.TestCase):
    def test_dia_de_inverno_tem_24_horas(self):
        start, end = t.day_window(date(2026, 10, 27))
        self.assertEqual(start, utc(2026, 10, 27, 0, 0))
        self.assertEqual(end, utc(2026, 10, 28, 0, 0))

    def test_dia_de_verao_comeca_uma_hora_antes_em_utc(self):
        start, end = t.day_window(date(2026, 7, 1))
        self.assertEqual(start, utc(2026, 6, 30, 23, 0))
        self.assertEqual(end - start, timedelta(hours=24))

    def test_mudanca_de_hora_de_outubro_tem_25_horas(self):
        start, end = t.day_window(date(2026, 10, 25))
        self.assertEqual(start, utc(2026, 10, 24, 23, 0))
        self.assertEqual(end, utc(2026, 10, 26, 0, 0))
        self.assertEqual(end - start, timedelta(hours=25))

    def test_mudanca_de_hora_de_marco_tem_23_horas(self):
        start, end = t.day_window(date(2026, 3, 29))
        self.assertEqual(start, utc(2026, 3, 29, 0, 0))
        self.assertEqual(end, utc(2026, 3, 29, 23, 0))
        self.assertEqual(end - start, timedelta(hours=23))

    def test_janelas_consecutivas_nao_deixam_buracos_nem_sobreposicoes(self):
        day = date(2026, 1, 1)
        for _ in range(400):
            self.assertEqual(t.day_window(day)[1], t.day_window(day + timedelta(days=1))[0])
            day += timedelta(days=1)

    def test_a_meia_noite_de_lisboa_pertence_ao_dia_novo(self):
        start, end = t.day_window(date(2026, 7, 1))
        self.assertTrue(start <= utc(2026, 6, 30, 23, 0) < end)
        self.assertFalse(start <= utc(2026, 7, 1, 23, 0) < end)


class LastClosedDayTests(unittest.TestCase):
    def test_antes_das_23_em_lisboa_conta_o_dia_anterior(self):
        self.assertEqual(t.last_closed_day(utc(2026, 10, 27, 22, 59, 59)), date(2026, 10, 26))

    def test_as_23_em_lisboa_o_dia_fecha(self):
        self.assertEqual(t.last_closed_day(utc(2026, 10, 27, 23, 0, 0)), date(2026, 10, 27))

    def test_no_verao_as_23_de_lisboa_sao_22_utc(self):
        self.assertEqual(t.last_closed_day(utc(2026, 7, 1, 21, 59, 59)), date(2026, 6, 30))
        self.assertEqual(t.last_closed_day(utc(2026, 7, 1, 22, 0, 0)), date(2026, 7, 1))

    def test_depois_da_meia_noite_ainda_conta_o_dia_que_fechou(self):
        self.assertEqual(t.last_closed_day(utc(2026, 10, 28, 3, 0, 0)), date(2026, 10, 27))

    def test_data_sem_fuso_e_rejeitada(self):
        with self.assertRaises(ValueError):
            t.last_closed_day(datetime(2026, 10, 27, 23, 0))


class TimestampTests(unittest.TestCase):
    def test_formatos_do_postgres(self):
        esperado = utc(2026, 10, 8, 16, 57, 59, 859173)
        self.assertEqual(t.parse_timestamp("2026-10-08T16:57:59.859173+00:00"), esperado)
        self.assertEqual(t.parse_timestamp("2026-10-27T22:35:12.57023+00:00"), utc(2026, 10, 27, 22, 35, 12, 570230))
        self.assertEqual(t.parse_timestamp("2026-10-27T22:35:12+00:00"), utc(2026, 10, 27, 22, 35, 12))
        self.assertEqual(t.parse_timestamp("2026-10-27T22:35:12Z"), utc(2026, 10, 27, 22, 35, 12))

    def test_converte_outros_fusos_para_utc(self):
        self.assertEqual(t.parse_timestamp("2026-07-01T23:00:00+01:00"), utc(2026, 7, 1, 22, 0, 0))
        self.assertEqual(t.parse_timestamp("2026-07-01T23:00:00+0100"), utc(2026, 7, 1, 22, 0, 0))
        self.assertEqual(t.parse_timestamp("2026-07-01 23:00:00-02"), utc(2026, 7, 2, 1, 0, 0))

    def test_sem_fuso_ou_lixo_falha(self):
        for texto in ("2026-10-27T22:35:12", "ontem", "", None, 5, "2026-13-01T00:00:00Z"):
            with self.assertRaises(ValueError, msg=repr(texto)):
                t.parse_timestamp(texto)

    def test_formato_canonico(self):
        self.assertEqual(t.format_utc(utc(2026, 10, 27, 22, 35, 12, 570230)), "2026-10-27T22:35:12.570230Z")
        self.assertEqual(t.format_utc(utc(2026, 10, 27, 22, 35, 12)), "2026-10-27T22:35:12.000000Z")
        self.assertEqual(t.format_utc_seconds(utc(2026, 10, 27, 22, 35, 12, 999999)), "2026-10-27T22:35:12Z")

    def test_a_ordem_do_texto_canonico_e_a_cronologica(self):
        a = t.format_utc(utc(2026, 10, 27, 22, 35, 12, 5))
        b = t.format_utc(utc(2026, 10, 27, 22, 35, 12, 500000))
        self.assertLess(a, b)


class DateTests(unittest.TestCase):
    def test_data_estrita(self):
        self.assertEqual(t.parse_date("2026-10-27"), date(2026, 10, 27))
        for texto in ("27/10/2026", "2026-1-5", "20261027", "", None):
            with self.assertRaises(ValueError, msg=repr(texto)):
                t.parse_date(texto)


class RetentionTests(unittest.TestCase):
    def test_primeiro_dia_pode_estar_cortado(self):
        gerado = utc(2026, 10, 27, 22, 40)
        self.assertTrue(t.may_be_cut_by_retention(date(2026, 9, 17), gerado))

    def test_dia_seguinte_esta_completo(self):
        gerado = utc(2026, 10, 27, 22, 40)
        self.assertFalse(t.may_be_cut_by_retention(date(2026, 9, 18), gerado))

    def test_dia_recente_nunca_e_parcial(self):
        gerado = utc(2026, 10, 27, 22, 40)
        self.assertFalse(t.may_be_cut_by_retention(date(2026, 10, 27), gerado))


if __name__ == "__main__":
    unittest.main()
