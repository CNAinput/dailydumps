import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from cnadump.client import PostgrestClient, Response, content_range_total
from cnadump.errors import NetworkError, ValidationError
from tests.fakes import FakePostgrest

BASE = datetime(2026, 10, 26, 11, 0, 5, 123456, tzinfo=timezone.utc)
KEY = "chave-anonima-de-teste"


def linhas(n):
    return [
        {"id": i, "guild_id": 1, "code": "AAA", "asset_type": "company", "price": 1.5 + i / 100,
         "timestamp": BASE + timedelta(seconds=i)}
        for i in range(n)
    ]


def cliente(fake, **kwargs):
    kwargs.setdefault("sleep", lambda s: None)
    return PostgrestClient("https://exemplo.supabase.co", KEY, transport=fake, **kwargs)


PARAMS = [("select", "code,price,timestamp"), ("order", "timestamp.asc,id.asc")]


class PaginationTests(unittest.TestCase):
    def test_mais_de_1000_linhas_em_tres_paginas(self):
        fake = FakePostgrest({"price_history": linhas(2500)})
        rows = cliente(fake).select("price_history", PARAMS)
        self.assertEqual(len(rows), 2500)
        offsets = [dict(p)["offset"] for m, path, p in fake.calls if path.endswith("price_history")]
        self.assertEqual(offsets, ["0", "1000", "2000"])
        self.assertTrue(all(dict(p)["limit"] == "1000" for m, path, p in fake.calls))

    def test_ordem_deterministica_sem_repeticoes_nem_falhas(self):
        fake = FakePostgrest({"price_history": list(reversed(linhas(2300)))})
        rows = cliente(fake).select("price_history", PARAMS)
        tempos = [r["timestamp"] for r in rows]
        self.assertEqual(tempos, sorted(tempos))
        self.assertEqual(len(set(tempos)), 2300)

    def test_servidor_com_limite_menor_que_a_pagina(self):
        fake = FakePostgrest({"price_history": linhas(2500)}, max_rows=300)
        rows = cliente(fake).select("price_history", PARAMS)
        self.assertEqual(len(rows), 2500)
        self.assertEqual(len({r["timestamp"] for r in rows}), 2500)

    def test_estado_206_e_200_sao_aceites(self):
        fake = FakePostgrest({"price_history": linhas(5)})
        rows = cliente(fake).select("price_history", PARAMS)
        self.assertEqual(len(rows), 5)

    def test_tabela_vazia(self):
        fake = FakePostgrest({"price_history": []})
        self.assertEqual(cliente(fake).select("price_history", PARAMS), [])

    def test_precos_lidos_como_decimal_exato(self):
        fake = FakePostgrest({"price_history": [{"id": 1, "price": 74.44, "timestamp": BASE}]})
        rows = cliente(fake).select("price_history", [("select", "price,timestamp")])
        self.assertEqual(rows[0]["price"], Decimal("74.44"))
        self.assertIsInstance(rows[0]["price"], Decimal)

    def test_contagem_divergente_falha(self):
        fake = FakePostgrest({"price_history": linhas(1500)})

        def acrescenta_linha_a_mais(method, path, params, reply):
            if dict(params).get("offset") == "1000":
                page = json.loads(reply.body)
                return Response(reply.status, reply.headers, json.dumps(page + page[-1:]).encode("utf-8"))
            return reply

        fake.hooks.append(acrescenta_linha_a_mais)
        with self.assertRaises(ValidationError) as ctx:
            cliente(fake).select("price_history", PARAMS)
        self.assertIn("Contagem diferente", str(ctx.exception))

    def test_linha_omitida_a_meio_e_recuperada_no_pedido_seguinte(self):
        fake = FakePostgrest({"price_history": linhas(1500)})
        omitida = {"feita": False}

        def omite_uma_vez(method, path, params, reply):
            if dict(params).get("offset") == "1000" and not omitida["feita"]:
                omitida["feita"] = True
                page = json.loads(reply.body)
                return Response(reply.status, reply.headers, json.dumps(page[:-1]).encode("utf-8"))
            return reply

        fake.hooks.append(omite_uma_vez)
        rows = cliente(fake).select("price_history", PARAMS)
        self.assertEqual(len(rows), 1500)
        self.assertEqual(len({r["timestamp"] for r in rows}), 1500)

    def test_pagina_vazia_antes_do_fim_falha(self):
        fake = FakePostgrest({"price_history": linhas(1500)})

        def esvazia(method, path, params, reply):
            if dict(params).get("offset") == "1000":
                return Response(reply.status, reply.headers, b"[]")
            return reply

        fake.hooks.append(esvazia)
        with self.assertRaises(ValidationError):
            cliente(fake).select("price_history", PARAMS)

    def test_contagem_que_muda_a_meio_da_leitura_falha(self):
        fake = FakePostgrest({"price_history": linhas(1500)})

        def muda_total(method, path, params, reply):
            if dict(params).get("offset") == "1000":
                headers = dict(reply.headers, **{"content-range": "1000-1499/1501"})
                return Response(reply.status, headers, reply.body)
            return reply

        fake.hooks.append(muda_total)
        with self.assertRaises(ValidationError) as ctx:
            cliente(fake).select("price_history", PARAMS)
        self.assertIn("mudou", str(ctx.exception))

    def test_resposta_sem_content_range_falha(self):
        fake = FakePostgrest({"price_history": linhas(3)})
        fake.hooks.append(lambda m, p, q, r: Response(r.status, {}, r.body))
        with self.assertRaises(NetworkError) as ctx:
            cliente(fake).select("price_history", PARAMS)
        self.assertIn("contagem exata", str(ctx.exception))

    def test_leitura_de_filtro_por_intervalo(self):
        fake = FakePostgrest({"price_history": linhas(100)})
        inicio = "2026-10-26T11:00:30Z"
        fim = "2026-10-26T11:01:00Z"
        rows = cliente(fake).select(
            "price_history", [("select", "timestamp"), ("timestamp", f"gte.{inicio}"), ("timestamp", f"lt.{fim}")]
        )
        self.assertEqual(len(rows), 30)

    def test_content_range(self):
        self.assertEqual(content_range_total("0-999/70887"), 70887)
        self.assertEqual(content_range_total("*/0"), 0)
        self.assertIsNone(content_range_total("0-9/*"))
        self.assertIsNone(content_range_total(None))
        self.assertIsNone(content_range_total("lixo"))


class RetryTests(unittest.TestCase):
    def test_repete_em_503_com_espera_crescente(self):
        fake = FakePostgrest({"price_history": linhas(3)})
        falhas = {"n": 2}

        def indisponivel(method, path, params, reply):
            if falhas["n"] > 0:
                falhas["n"] -= 1
                return Response(503, {}, b"{}")
            return reply

        fake.hooks.append(indisponivel)
        esperas = []
        rows = cliente(fake, sleep=esperas.append, backoff=1.0).select("price_history", PARAMS)
        self.assertEqual(len(rows), 3)
        self.assertEqual(esperas, [1.0, 2.0])

    def test_nao_repete_em_401_e_nao_revela_a_chave(self):
        fake = FakePostgrest({"price_history": linhas(3)}, api_key="outra")
        with self.assertRaises(NetworkError) as ctx:
            cliente(fake).select("price_history", PARAMS)
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("HTTP 401", str(ctx.exception))
        self.assertNotIn(KEY, str(ctx.exception))

    def test_erro_de_cliente_nao_repete_e_mostra_o_motivo(self):
        fake = FakePostgrest({"price_history": linhas(3)})
        with self.assertRaises(NetworkError) as ctx:
            cliente(fake).select("price_history", [("select", "nao_existe")])
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("HTTP 400", str(ctx.exception))

    def test_falha_de_rede_esgota_as_tentativas(self):
        chamadas = []

        def sem_rede(*args):
            chamadas.append(args)
            raise OSError("sem rede")

        with self.assertRaises(NetworkError) as ctx:
            cliente(sem_rede, retries=3).select("price_history", PARAMS)
        self.assertEqual(len(chamadas), 4)
        self.assertIn("4 tentativas", str(ctx.exception))

    def test_a_chave_vai_nos_cabecalhos_e_nunca_no_url(self):
        vistos = {}

        def espia(method, url, headers, data, timeout):
            vistos.update(url=url, headers=headers)
            return Response(200, {"content-range": "*/0"}, b"[]")

        cliente(espia).select("price_history", PARAMS)
        self.assertNotIn(KEY, vistos["url"])
        self.assertEqual(vistos["headers"]["apikey"], KEY)
        self.assertEqual(vistos["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertEqual(vistos["headers"]["Prefer"], "count=exact")


class RpcTests(unittest.TestCase):
    def test_rpc_e_um_post_com_corpo_vazio(self):
        fake = FakePostgrest(rpcs={"rpc_get_market_aggregates": lambda: [{"code": "NEWTE", "asset_type": "company", "held_shares": 147299}]})
        dados = cliente(fake).rpc("rpc_get_market_aggregates")
        self.assertEqual(dados, [{"code": "NEWTE", "asset_type": "company", "held_shares": 147299}])
        self.assertEqual(fake.calls[0][0], "POST")

    def test_nan_no_json_e_rejeitado(self):
        def nan(*args):
            return Response(200, {"content-range": "0-0/1"}, b'[{"price": NaN}]')

        with self.assertRaises(NetworkError):
            cliente(nan).select("price_history", PARAMS)

    def test_corpo_que_nao_e_json_falha(self):
        def lixo(*args):
            return Response(200, {"content-range": "0-0/1"}, b"<html>")

        with self.assertRaises(NetworkError):
            cliente(lixo).select("price_history", PARAMS)


if __name__ == "__main__":
    unittest.main()
