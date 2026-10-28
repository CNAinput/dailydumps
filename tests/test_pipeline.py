import json
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from cnadump.client import Response
from cnadump.errors import ImmutabilityError, ValidationError
from cnadump.fmt import read_csv, tidy, quantize
from cnadump.store import sha256_hex
from tests.builders import D25, D26, D27, NOW, PipelineCase, StandardWorldCase, lisbon_now, local


class FirstRunTests(StandardWorldCase):
    def test_primeira_execucao_gera_todos_os_dias_e_o_snapshot_so_do_ultimo(self):
        result = self.generator(NOW).run_day()
        self.assertEqual(result.days, [D25, D26, D27])
        self.assertEqual(result.snapshot_day, D27)
        files = self.tree()
        for day in (D25, D26, D27):
            self.assertIn(f"prices/2026/{day}.csv", files)
            self.assertIn(f"summary/{day}.json", files)
        self.assertEqual([k for k in files if k.startswith("snapshots/")], ["snapshots/2026-10-27.json"])
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(
            {k: v["source"] for k, v in manifest["days"].items()},
            {"2026-10-25": "backfill", "2026-10-26": "backfill", "2026-10-27": "daily"},
        )
        self.assertEqual({v["rows"] for v in manifest["days"].values()}, {36})
        self.assertEqual(manifest["days"]["2026-10-27"]["generated_at"], "2026-10-27T23:17:00Z")
        self.assertFalse(any(v["partial"] for v in manifest["days"].values()))

    def test_ohlc_estado_e_somas(self):
        self.generator(NOW).run_day()
        files = self.tree()
        header, rows = read_csv(files["daily/ohlc.csv"])
        self.assertEqual(header, ["date", "code", "asset_type", "open", "high", "low", "close", "ticks"])
        self.assertEqual(len(rows), 18)
        self.assertEqual(rows, sorted(rows, key=lambda r: (r[0], r[1], r[2])))
        self.assertEqual({r[7] for r in rows}, {"6"})
        status = json.loads(files["status.json"])
        self.assertEqual(
            status,
            {"schema_version": 1, "last_date": "2026-10-27", "generated_at": "2026-10-27T23:17:00Z",
             "ticks": 36, "instruments": 6, "ok": True},
        )
        listed = {}
        for line in files["SHA256SUMS"].decode().splitlines():
            digest, rel = line.split("  ", 1)
            listed[rel] = digest
        self.assertEqual(set(listed), {k for k in files if k != "SHA256SUMS"})
        for rel, digest in listed.items():
            self.assertEqual(sha256_hex(files[rel]), digest, rel)

    def test_o_ohlc_corresponde_aos_ticks_do_dia(self):
        self.world.tick(D27, 12, 0, "NEWTE", "company", 20.0)
        self.world.tick(D27, 14, 0, "NEWTE", "company", 5.5)
        self.world.tick(D27, 22, 59, "NEWTE", "company", 11.0)
        self.world.sync_prices()
        self.generator(NOW).run_day()
        _, rows = read_csv(self.tree()["daily/ohlc.csv"])
        newte = [r for r in rows if r[0] == "2026-10-27" and r[1] == "NEWTE"][0]
        self.assertEqual(Decimal(newte[4]), Decimal("20.0"))
        self.assertEqual(Decimal(newte[5]), Decimal("5.5"))
        self.assertEqual(Decimal(newte[6]), Decimal("11.0"))
        self.assertEqual(newte[7], "9")

    def test_primeiro_tick_e_o_open_e_o_ultimo_e_o_close(self):
        self.generator(NOW).run_day()
        ticks = sorted(
            (r for r in self.world.price_history
             if r["code"] == "ACHIP" and local(D26, 0) <= r["timestamp"] < local(D27, 0)),
            key=lambda r: r["timestamp"],
        )
        _, rows = read_csv(self.tree()["daily/ohlc.csv"])
        achip = [r for r in rows if r[0] == "2026-10-26" and r[1] == "ACHIP"][0]
        self.assertEqual(Decimal(achip[3]), Decimal(str(ticks[0]["price"])))
        self.assertEqual(Decimal(achip[6]), Decimal(str(ticks[-1]["price"])))


class IdempotencyAndRecoveryTests(StandardWorldCase):
    def test_segunda_execucao_nao_altera_nada_nem_chama_a_rede(self):
        self.generator(NOW).run_day()
        before = self.tree()
        result = self.generator(NOW).run_day()
        self.assertEqual(result.days, [])
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.fake.calls, [])

    def test_repetir_um_dia_ja_arquivado_nao_cria_um_snapshot_novo(self):
        self.generator(NOW).run_day()
        before = self.tree()
        result = self.generator(NOW + timedelta(minutes=20)).run_day(only=D27)
        self.assertEqual(result.days, [])
        self.assertEqual(self.tree(), before)

    def test_recupera_os_dias_em_falta(self):
        self.world.sync_prices(until=local(D26, 0))
        self.generator(lisbon_now(D25, 23, 17)).run_day()
        self.assertEqual(sorted(self.repo.price_days()), [D25])
        self.world.sync_prices()
        result = self.generator(NOW).run_day()
        self.assertEqual(result.days, [D26, D27])
        manifest = json.loads(self.tree()["manifest.json"])
        self.assertEqual(manifest["days"]["2026-10-25"]["source"], "daily")
        self.assertEqual(manifest["days"]["2026-10-26"]["source"], "backfill")
        self.assertEqual(manifest["days"]["2026-10-27"]["source"], "daily")

    def test_day_so_olha_para_a_frente_e_backfill_preenche_buracos(self):
        self.generator(NOW).run_day()
        (self.root / "prices/2026/2026-10-26.csv").unlink()
        self.assertEqual(self.generator(NOW).run_day().days, [])
        self.assertNotIn("prices/2026/2026-10-26.csv", self.tree())
        result = self.generator(NOW).run_backfill()
        self.assertEqual(result.days, [D26])
        self.assertIn("prices/2026/2026-10-26.csv", self.tree())

    def test_dia_vazio_bloqueia_o_day_e_o_backfill_a_seguir_desbloqueia(self):
        d28 = date(2026, 10, 28)
        self.world.sync_prices(until=local(D26, 0))
        self.generator(lisbon_now(D25, 23, 17)).run_day()
        self.world.price_history[:] = [
            r for r in self.world.price_history if not (local(D26, 0) <= r["timestamp"] < local(D27, 0))
        ]
        self.world.fill_day(d28)
        self.world.sync_prices(until=local(d28, 0))
        before = self.tree()
        with self.assertRaises(ValidationError) as ctx:
            self.generator(NOW).run_day()
        self.assertIn("2026-10-26: dia sem nenhum tick", str(ctx.exception))
        self.assertEqual(self.tree(), before)
        # Decisão explícita do dono: arquivar a partir do dia a seguir ao buraco.
        result = self.generator(NOW).run_backfill(start=D27)
        self.assertEqual(result.days, [D27])
        # O buraco fica para trás e o arquivo diário retoma normalmente.
        self.world.sync_prices()
        result = self.generator(lisbon_now(d28, 23, 17)).run_day()
        self.assertEqual(result.days, [d28])
        self.assertEqual(result.snapshot_day, d28)
        dates = json.loads(self.tree()["manifest.json"])["days"]
        self.assertEqual(sorted(dates), ["2026-10-25", "2026-10-27", "2026-10-28"])

    def test_snapshot_so_com_a_base_ainda_no_estado_do_fecho(self):
        result = self.generator(lisbon_now(date(2026, 10, 28), 11, 30)).run_day()
        self.assertEqual(result.days, [D25, D26, D27])
        self.assertIsNone(result.snapshot_day)
        self.assertEqual([k for k in self.tree() if k.startswith("snapshots/")], [])
        manifest = json.loads(self.tree()["manifest.json"])
        self.assertEqual({v["source"] for v in manifest["days"].values()}, {"backfill"})

    def test_dia_que_ainda_nao_fechou_nao_conta(self):
        result = self.generator(lisbon_now(D27, 22, 59)).run_day()
        self.assertEqual(result.days, [D25, D26])


class HorizonTests(PipelineCase):
    def test_nunca_recua_mais_de_40_dias(self):
        self.world.standard()
        day = date(2026, 8, 29)
        while day <= D27:
            self.world.fill_day(day, step=360)
            day += timedelta(days=1)
        self.world.sync_prices()
        result = self.generator(NOW).run_day()
        self.assertEqual(result.days[0], date(2026, 9, 17))
        self.assertEqual(result.days[-1], D27)
        self.assertEqual(len(result.days), 41)

    def test_so_o_primeiro_dia_pode_estar_cortado_pela_retencao(self):
        self.world.standard()
        day = date(2026, 9, 17)
        while day <= D27:
            self.world.fill_day(day, step=360)
            day += timedelta(days=1)
        self.world.sync_prices()
        self.generator(NOW).run_backfill()
        manifest = json.loads(self.tree()["manifest.json"])
        partial = [d for d, v in manifest["days"].items() if v["partial"]]
        self.assertEqual(partial, ["2026-09-17"])


class HardErrorTests(StandardWorldCase):
    def assert_rejected(self, expected):
        with self.assertRaises(ValidationError) as ctx:
            self.generator(NOW).run_day()
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertIn(expected, str(ctx.exception))
        self.assertEqual(self.tree(), {})

    def test_preco_negativo(self):
        self.world.price_history[3]["price"] = -1.0
        self.assert_rejected("preços não finitos ou não positivos")

    def test_preco_zero(self):
        self.world.price_history[3]["price"] = 0.0
        self.assert_rejected("preços não finitos ou não positivos")

    def test_preco_nao_finito(self):
        self.world.price_history[3]["price"] = "NaN"
        self.assert_rejected("preços não finitos ou não positivos")

    def test_preco_infinito(self):
        self.world.price_history[3]["price"] = "Infinity"
        self.assert_rejected("preços não finitos ou não positivos")

    def test_tick_duplicado(self):
        copia = dict(self.world.price_history[5], id=10 ** 6)
        self.world.price_history.append(copia)
        self.assert_rejected("ticks duplicados")

    def test_tipo_de_ativo_desconhecido(self):
        self.world.price_history[2]["asset_type"] = "obrigacao"
        self.assert_rejected("tipos de ativo desconhecidos")

    def test_dia_sem_nenhum_tick(self):
        self.world.price_history[:] = [
            r for r in self.world.price_history if not (local(D26, 0) <= r["timestamp"] < local(D27, 0))
        ]
        self.assert_rejected("2026-10-26: dia sem nenhum tick")

    def test_mais_de_um_servidor(self):
        self.world.price_history[4]["guild_id"] = 123
        self.assert_rejected("mais de um servidor")

    def test_contagem_do_servidor_diferente_das_linhas_recebidas(self):
        def hook(method, path, params, reply):
            if path.endswith("price_history") and reply.status in (200, 206):
                page = json.loads(reply.body)
                if page:
                    return Response(reply.status, reply.headers, json.dumps(page + page[-1:]).encode("utf-8"))
            return reply

        original = self.world.transport

        def with_hook():
            fake = original()
            fake.hooks.append(hook)
            return fake

        self.world.transport = with_hook
        self.assert_rejected("Contagem diferente")

    def test_ultimo_tick_diferente_do_preco_atual(self):
        self.world.companies[0]["current_price"] = 999.99
        self.assert_rejected("o último tick de NEWTE (company) é")

    def test_varios_erros_sao_todos_reportados(self):
        self.world.price_history[3]["price"] = -1.0
        self.world.price_history[4]["asset_type"] = "x"
        with self.assertRaises(ValidationError) as ctx:
            self.generator(NOW).run_day()
        self.assertEqual(len(ctx.exception.messages), 2)

    def test_backfill_e_regenerar_tambem_verificam_o_preco_atual_na_janela_do_fecho(self):
        self.world.companies[0]["current_price"] = 999.99
        with self.assertRaises(ValidationError) as ctx:
            self.generator(NOW).run_backfill()
        self.assertIn("o último tick de NEWTE (company) é", str(ctx.exception))
        self.assertEqual(self.tree(), {})
        self.world.sync_prices()
        self.generator(NOW).run_backfill()
        self.world.companies[0]["current_price"] = 999.99
        self.world.tick(D27, 12, 30, "NEWTE", "company", 99.0)
        with self.assertRaises(ValidationError):
            self.generator(NOW).run_regenerate(D27)

    def test_atualizacao_atrasada_nao_verifica_o_preco_atual(self):
        self.world.companies[0]["current_price"] = 999.99
        result = self.generator(lisbon_now(date(2026, 10, 28), 12, 0)).run_day()
        self.assertEqual(result.days, [D25, D26, D27])


class ImmutabilityTests(StandardWorldCase):
    def test_recalculado_diferente_falha_sem_escrever(self):
        self.generator(NOW).run_day()
        before = self.tree()
        self.world.tick(D26, 12, 30, "NEWTE", "company", 99.0)
        with self.assertRaises(ImmutabilityError) as ctx:
            self.generator(NOW).run_day(only=D26)
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertIn("imutáveis", str(ctx.exception))
        self.assertEqual(self.tree(), before)

    def test_regenerar_substitui_e_regista_no_manifesto(self):
        self.generator(NOW).run_day()
        before = self.tree()
        old_sha = json.loads(before["manifest.json"])["days"]["2026-10-26"]["sha256"]
        self.world.tick(D26, 12, 30, "NEWTE", "company", 99.0)
        later = NOW + timedelta(minutes=5)
        result = self.generator(later).run_regenerate(D26)
        self.assertEqual(result.days, [D26])
        after = self.tree()
        entry = json.loads(after["manifest.json"])["days"]["2026-10-26"]
        self.assertEqual(entry["rows"], 37)
        self.assertEqual(entry["generated_at"], "2026-10-27T23:22:00Z")
        self.assertEqual(entry["regenerations"], [{
            "at": "2026-10-27T23:22:00Z", "previous_generated_at": "2026-10-27T23:17:00Z",
            "previous_sha256": old_sha, "previous_rows": 36,
        }])
        for rel in ("prices/2026/2026-10-25.csv", "prices/2026/2026-10-27.csv", "snapshots/2026-10-27.json"):
            self.assertEqual(after[rel], before[rel], rel)
        self.assertNotEqual(after["prices/2026/2026-10-26.csv"], before["prices/2026/2026-10-26.csv"])

    def test_regenerar_com_dados_iguais_nao_faz_nada(self):
        self.generator(NOW).run_day()
        before = self.tree()
        result = self.generator(NOW + timedelta(minutes=5)).run_regenerate(D26)
        self.assertEqual(result.days, [])
        self.assertEqual(self.tree(), before)

    def test_regenerar_mantem_o_snapshot_e_a_capitalizacao_do_dia(self):
        self.generator(NOW).run_day()
        self.world.tick(D27, 12, 30, "NEWTE", "company", 99.0)
        self.generator(NOW + timedelta(minutes=5)).run_regenerate(D27)
        summary = json.loads(self.tree()["summary/2026-10-27.json"])
        self.assertTrue(summary["market_cap_available"])
        self.assertEqual(json.loads(self.tree()["manifest.json"])["days"]["2026-10-27"]["source"], "daily")

    def test_pedidos_invalidos(self):
        gen = self.generator(NOW)
        with self.assertRaises(ValidationError) as ctx:
            gen.run_regenerate(date(2026, 10, 28))
        self.assertIn("ainda não fechou", str(ctx.exception))
        with self.assertRaises(ValidationError) as ctx:
            gen.run_regenerate(D26)
        self.assertIn("não tem ficheiro", str(ctx.exception))
        with self.assertRaises(ValidationError):
            gen.run_day(only=date(2026, 10, 28))


class BackfillTests(StandardWorldCase):
    def test_backfill_nao_tem_snapshots_nem_capitalizacao(self):
        result = self.generator(NOW).run_backfill()
        self.assertEqual(result.days, [D25, D26, D27])
        self.assertIsNone(result.snapshot_day)
        files = self.tree()
        self.assertEqual([k for k in files if k.startswith("snapshots/")], [])
        self.assertNotIn("instruments.json", files)
        self.assertIn("dividends.json", files)
        self.assertIn("taxes.json", files)
        for day in ("2026-10-25", "2026-10-26", "2026-10-27"):
            summary = json.loads(files[f"summary/{day}.json"])
            self.assertFalse(summary["market_cap_available"])
            self.assertIsNone(summary["top_market_cap"])
            self.assertIsNone(summary["total_market_cap"])
            self.assertIsNone(summary["companies_count"])
        manifest = json.loads(files["manifest.json"])
        self.assertEqual({v["source"] for v in manifest["days"].values()}, {"backfill"})

    def test_inicio_explicito(self):
        result = self.generator(NOW).run_backfill(start=D26)
        self.assertEqual(result.days, [D26, D27])

    def test_inicio_anterior_aos_dados_passa_para_o_primeiro_dia(self):
        result = self.generator(NOW).run_backfill(start=date(2026, 1, 1))
        self.assertEqual(result.days, [D25, D26, D27])
        self.assertTrue(any("só tem ticks desde 2026-10-25" in line for line in self.logs))

    def test_base_vazia_e_um_erro(self):
        self.world.price_history.clear()
        with self.assertRaises(ValidationError) as ctx:
            self.generator(NOW).run_backfill()
        self.assertIn("nenhum tick", str(ctx.exception))
        self.assertEqual(self.tree(), {})


class DailyFilesTests(StandardWorldCase):
    def test_snapshot_do_dia(self):
        self.generator(NOW).run_day()
        snapshot = json.loads(self.tree()["snapshots/2026-10-27.json"])
        self.assertEqual(snapshot["date"], "2026-10-27")
        self.assertEqual(snapshot["snapshot_at"], "2026-10-27T23:17:00Z")
        by_code = {i["code"]: i for i in snapshot["instruments"]}
        newte = by_code["NEWTE"]
        self.assertEqual(
            set(newte),
            {"code", "name", "asset_type", "is_index", "owner_company_code", "price", "shares_total",
             "shares_in_circulation", "market_cap"},
        )
        self.assertEqual(newte["shares_in_circulation"], 147299)
        self.assertEqual(Decimal(str(newte["market_cap"])), quantize(Decimal(str(newte["price"])) * 147299, 2))
        self.assertTrue(by_code["P&P10"]["is_index"])
        self.assertEqual(by_code["P&P10"]["owner_company_code"], "P&PEP")

    def test_shares_sem_detentores_valem_zero(self):
        del self.world.held[("ACSCP", "asset")]
        self.generator(NOW).run_day()
        snapshot = json.loads(self.tree()["snapshots/2026-10-27.json"])
        acscp = [i for i in snapshot["instruments"] if i["code"] == "ACSCP"][0]
        self.assertEqual(acscp["shares_in_circulation"], 0)
        self.assertEqual(acscp["market_cap"], 0)

    def test_registo_de_instrumentos_tem_slugs(self):
        self.generator(NOW).run_day()
        registry = json.loads(self.tree()["instruments.json"])
        slugs = {i["code"]: i["slug"] for i in registry["instruments"]}
        self.assertEqual(slugs["P&P10"], "p-and-p10")
        self.assertEqual(slugs["NEWTE"], "newte")
        self.assertEqual(len(set(slugs.values())), len(slugs))

    def test_dividendos_e_impostos_sem_ids(self):
        self.world.add_dividend(
            "ACHIP", "company", 30, 14,
            datetime(2026, 10, 16, 14, 9, 47, 42652, tzinfo=timezone.utc),
            datetime(2026, 10, 30, 14, 9, 47, 42652, tzinfo=timezone.utc),
        )
        self.generator(NOW).run_day()
        files = self.tree()
        self.assertEqual(json.loads(files["dividends.json"]), {
            "schema_version": 1,
            "policies": [{
                "code": "ACHIP", "asset_type": "company", "percentage": 30, "distribution_days": 14,
                "next_distribution": "2026-10-30T14:09:47.042652Z", "last_distribution": "2026-10-16T14:09:47.042652Z",
            }],
        })
        self.assertEqual(json.loads(files["taxes.json"]), {
            "schema_version": 1, "loan_interest_pct": 1, "income_tax_pct": 12, "vat_pct": 7,
            "last_changed": "2026-08-25T09:59:51.000000Z",
        })

    def test_nenhum_ficheiro_exporta_ids_de_contas_ou_utilizadores(self):
        self.world.add_dividend("ACHIP", "company", 30, 14, None, None)
        self.generator(NOW).run_day()
        for rel, data in self.tree().items():
            self.assertNotIn(b"SEGREDO", data, rel)
            self.assertNotIn(b"account", data.lower(), rel)

    def test_resumo_com_capitalizacao(self):
        self.generator(NOW).run_day()
        summary = json.loads(self.tree()["summary/2026-10-27.json"])
        self.assertTrue(summary["market_cap_available"])
        self.assertEqual([t["rank"] for t in summary["top_market_cap"]], [1, 2, 3])
        self.assertEqual(summary["companies_count"], 3)
        self.assertEqual({i["code"] for i in summary["indices"]}, {"P&P10", "PPA10"})


class ReadOnlyTests(StandardWorldCase):
    def test_so_faz_get_e_o_post_da_rpc_de_leitura(self):
        self.generator(NOW).run_day()
        for method, path, params in self.fake.calls:
            if method == "POST":
                self.assertEqual(path, "/rest/v1/rpc/rpc_get_market_aggregates")
            else:
                self.assertEqual(method, "GET")
                self.assertTrue(path.startswith("/rest/v1/"))


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class DstDayTests(PipelineCase):
    def make_world(self):
        self.world.add_company("AAA", "Empresa A", 1.0)

    def test_dia_de_25_horas(self):
        self.make_world()
        for ts in (utc(2026, 10, 24, 22, 59, 59), utc(2026, 10, 24, 23, 0, 0), utc(2026, 10, 24, 23, 30, 0),
                   utc(2026, 10, 25, 12, 0, 0), utc(2026, 10, 25, 23, 59, 59), utc(2026, 10, 26, 0, 0, 0)):
            self.world.tick_utc(ts, "AAA", "company", 1.5)
        self.world.sync_prices()
        self.generator(lisbon_now(D26, 23, 17)).run_day()
        manifest = json.loads(self.tree()["manifest.json"])
        self.assertEqual({d: v["rows"] for d, v in manifest["days"].items()},
                         {"2026-10-24": 1, "2026-10-25": 4, "2026-10-26": 1})

    def test_dia_de_23_horas(self):
        self.make_world()
        for ts in (utc(2026, 3, 28, 23, 59, 59), utc(2026, 3, 29, 0, 0, 0), utc(2026, 3, 29, 12, 0, 0),
                   utc(2026, 3, 29, 22, 59, 59), utc(2026, 3, 29, 23, 0, 0)):
            self.world.tick_utc(ts, "AAA", "company", 1.5)
        self.world.sync_prices()
        self.generator(lisbon_now(date(2026, 3, 30), 23, 17)).run_day()
        manifest = json.loads(self.tree()["manifest.json"])
        self.assertEqual({d: v["rows"] for d, v in manifest["days"].items()},
                         {"2026-03-28": 1, "2026-03-29": 3, "2026-03-30": 1})


class AdjustmentTests(PipelineCase):
    D20, D21, D22, D23, D24 = (date(2026, 10, n) for n in (20, 21, 22, 23, 24))

    def rows(self, name):
        _, rows = read_csv(self.tree()[name])
        return {(r[0], r[1]): r for r in rows}

    def test_split_ajusta_so_os_dias_gerados_antes_do_evento_e_nunca_duas_vezes(self):
        self.world.standard()
        for day in (self.D20, self.D21, self.D22):
            self.world.fill_day(day, step=60)
        self.world.sync_prices()
        self.generator(lisbon_now(self.D22, 23, 17)).run_day()

        (self.root / "events.csv").write_text(
            "date,code,asset_type,event,factor,shares_before,shares_after,document_id,notes\n"
            "2026-10-23,NEWTE,company,split,4,300000,1200000,,teste\n", encoding="utf-8",
        )
        self.world.apply_split("NEWTE", "company", 4)
        self.world.base[("NEWTE", "company")] = round(11.32 / 4, 2)
        for day in (self.D23, self.D24):
            self.world.fill_day(day, step=60)
        self.world.sync_prices()
        self.generator(lisbon_now(self.D24, 23, 17)).run_day()

        raw, adjusted = self.rows("daily/ohlc.csv"), self.rows("daily/ohlc_adjusted.csv")
        self.assertEqual(set(raw), set(adjusted))
        for (day, code), row in raw.items():
            if code != "NEWTE" or day >= "2026-10-23":
                self.assertEqual(adjusted[(day, code)], row, (day, code))
        for day in ("2026-10-20", "2026-10-21", "2026-10-22"):
            for position in (3, 4, 5, 6):
                expected = tidy(quantize(Decimal(raw[(day, "NEWTE")][position]) / 4, 4))
                self.assertEqual(adjusted[(day, "NEWTE")][position], expected)
            self.assertEqual(adjusted[(day, "NEWTE")][7], raw[(day, "NEWTE")][7])

        # Regenerar um dia antigo depois do split: a base já reflete o split e o dia não é ajustado outra vez.
        before_adjusted = adjusted[("2026-10-22", "NEWTE")]
        self.generator(lisbon_now(date(2026, 10, 25), 9, 0)).run_regenerate(self.D22)
        raw, adjusted = self.rows("daily/ohlc.csv"), self.rows("daily/ohlc_adjusted.csv")
        self.assertEqual(adjusted[("2026-10-22", "NEWTE")], raw[("2026-10-22", "NEWTE")])
        for position in (3, 4, 5, 6):
            gap = abs(Decimal(adjusted[("2026-10-22", "NEWTE")][position]) - Decimal(before_adjusted[position]))
            self.assertLessEqual(gap, Decimal("0.01"))

    def test_events_invalido_nao_bloqueia_a_geracao(self):
        self.world.standard()
        for day in (self.D21, self.D22):
            self.world.fill_day(day, step=60)
        self.world.sync_prices()
        (self.root / "events.csv").write_text("lixo\n", encoding="utf-8")
        result = self.generator(lisbon_now(self.D22, 23, 17)).run_day()
        self.assertEqual(len(result.days), 2)
        self.assertTrue(any("events.csv inválido" in w for w in result.warnings))
        self.assertNotIn("daily/ohlc_adjusted.csv", self.tree())


class WarningTests(StandardWorldCase):
    def test_instrumento_sem_ticks_e_lacunas_geram_avisos_sem_bloquear(self):
        self.world.price_history[:] = [
            r for r in self.world.price_history
            if not (r["code"] == "ACSCP" and local(D26, 0) <= r["timestamp"] < local(D27, 0))
        ]
        self.world.price_history[:] = [
            r for r in self.world.price_history
            if not (r["code"] == "NEWTE" and local(D25, 13) <= r["timestamp"] <= local(D25, 16))
        ]
        self.world.sync_prices()
        result = self.generator(NOW).run_day()
        self.assertTrue(any("2026-10-26: ACSCP (asset) sem ticks neste dia" in w for w in result.warnings))
        self.assertTrue(any("2026-10-25: NEWTE (company) ficou 6h" in w for w in result.warnings))
        self.assertEqual(len(result.days), 3)


if __name__ == "__main__":
    unittest.main()
