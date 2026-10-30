import json
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from cnadump import payouts as po
from cnadump.errors import ImmutabilityError, ValidationError
from cnadump.pages import build_pages
from cnadump.store import Repo, sha256_hex
from cnadump.timeutil import day_window
from cnadump.verify import protected_changes, verify_repo
from tests.builders import PipelineCase, lisbon_now, local, pay, write_web

D29, D30, D31 = date(2026, 10, 29), date(2026, 10, 30), date(2026, 10, 31)
NOW31 = lisbon_now(D31, 23, 17)
FILE30 = "dividend_payouts/2026-10-30.json"

PNV = [pay("Chip_12", "pessoal", 100, 60.0), pay("2020T", "empresa", 300, 180.0), pay("Estado", "estado", 100, 60.0)]
ACHIP = [pay("KingBJ", "pessoal", 1, 0.07), pay("dani", "pessoal", 2, 0.14), pay("ssslav7", "pessoal", 1, 0.07)]


class PayoutsCase(PipelineCase):
    """Três dias (29 a 31 de outubro): o 29 é anterior ao registo de pagamentos, o 30 e o 31 não."""

    def setUp(self):
        super().setUp()
        self.world.standard()
        for day in (D29, D30, D31):
            self.world.fill_day(day)
        self.world.sync_prices()

    def two_payouts(self):
        self.world.add_payout("ACHIP", "company", local(D30, 14, 10, 48), ACHIP, pct=30, pool=0.3, total_shares=4)
        self.world.add_payout("P&PNV", "asset", local(D30, 9, 57, 50), PNV, origin="reconstruction")

    def manifest(self):
        return json.loads(self.tree()["manifest.json"])["days"]

    def document(self, rel=FILE30):
        return json.loads(self.tree()[rel])


class DailyFileTests(PayoutsCase):
    def test_pagamentos_do_dia_ficam_no_ficheiro_desse_dia(self):
        self.two_payouts()
        result = self.generator(NOW31).run_day()
        self.assertEqual(result.payouts, 2)
        self.assertEqual(self.document(), {
            "schema_version": 1,
            "date": "2026-10-30",
            "payouts": [
                {
                    "code": "P&PNV", "asset_type": "asset", "paid_at": "2026-10-30T09:57:50Z", "percentage": 50,
                    "pool": 300, "total_paid": 300, "beneficiaries": 3, "average": 100, "total_shares": 500,
                    "origin": "reconstruction",
                    "payments": [
                        {"beneficiary": "2020T", "kind": "empresa", "shares": 300, "amount": 180},
                        {"beneficiary": "Chip_12", "kind": "pessoal", "shares": 100, "amount": 60},
                        {"beneficiary": "Estado", "kind": "estado", "shares": 100, "amount": 60},
                    ],
                },
                {
                    "code": "ACHIP", "asset_type": "company", "paid_at": "2026-10-30T14:10:48Z", "percentage": 30,
                    "pool": 0.3, "total_paid": 0.28, "beneficiaries": 3, "average": 0.09, "total_shares": 4,
                    "origin": "bot",
                    "payments": [
                        {"beneficiary": "dani", "kind": "pessoal", "shares": 2, "amount": 0.14},
                        {"beneficiary": "KingBJ", "kind": "pessoal", "shares": 1, "amount": 0.07},
                        {"beneficiary": "ssslav7", "kind": "pessoal", "shares": 1, "amount": 0.07},
                    ],
                },
            ],
        })

    def test_manifesto_conta_os_pagamentos_so_nos_dias_cobertos(self):
        self.two_payouts()
        self.generator(NOW31).run_day()
        days = self.manifest()
        self.assertNotIn("dividend_payouts", days["2026-10-29"])
        self.assertEqual(days["2026-10-30"]["dividend_payouts"], 2)
        self.assertEqual(days["2026-10-31"]["dividend_payouts"], 0)
        self.assertEqual(list(days["2026-10-30"])[-1], "dividend_payouts")

    def test_dia_sem_pagamentos_nao_cria_ficheiro(self):
        self.generator(NOW31).run_day()
        files = self.tree()
        self.assertEqual([k for k in files if k.startswith("dividend_payouts/")], [])
        self.assertEqual(self.manifest()["2026-10-30"]["dividend_payouts"], 0)

    def test_so_pede_a_tabela_nos_dias_cobertos(self):
        self.generator(NOW31).run_day()
        asked = [p for m, path, p in self.fake.calls if path.endswith("/dividend_payouts")]
        windows = {dict(p)["paid_at"] for p in asked}
        self.assertEqual(len(windows), 2)
        for _, path, _ in self.fake.calls:
            self.assertNotIn("2026-10-29", path)
        first = [dict(p) for p in asked][0]
        self.assertTrue(first["select"].startswith("code,asset_type,paid_at"))

    def test_fronteiras_do_dia_de_lisboa(self):
        self.world.add_payout("ACHIP", "company", local(D30, 23, 0, 5), PNV)
        self.world.add_payout("ACHIP", "company", local(D31, 0, 0, 1), ACHIP, pool=0.3)
        self.world.add_payout("ACHIP", "company", local(D30, 0, 0, 0), PNV)
        self.world.add_payout("ACHIP", "company", local(D31, 0, 0, 0), PNV)
        self.generator(NOW31).run_day()
        self.assertEqual(
            [p["paid_at"] for p in self.document(FILE30)["payouts"]],
            ["2026-10-30T00:00:00Z", "2026-10-30T23:00:05Z"],
        )
        self.assertEqual(
            [p["paid_at"] for p in self.document("dividend_payouts/2026-10-31.json")["payouts"]],
            ["2026-10-31T00:00:00Z", "2026-10-31T00:00:01Z"],
        )

    def test_backfill_tambem_arquiva_os_pagamentos(self):
        self.two_payouts()
        self.generator(NOW31).run_backfill()
        self.assertEqual(self.manifest()["2026-10-30"]["dividend_payouts"], 2)
        self.assertIn(FILE30, self.tree())

    def test_ficheiro_entra_nas_somas_e_o_repositorio_fica_integro(self):
        self.two_payouts()
        self.generator(NOW31).run_day()
        files = self.tree()
        listed = dict(line.split("  ", 1)[::-1] for line in files["SHA256SUMS"].decode().splitlines())
        self.assertEqual(listed[FILE30], sha256_hex(files[FILE30]))
        report = verify_repo(self.repo)
        self.assertEqual((report.errors, report.warnings), ([], []))

    def test_segunda_execucao_nao_altera_nada(self):
        self.two_payouts()
        self.generator(NOW31).run_day()
        before = self.tree()
        self.assertEqual(self.generator(NOW31).run_day().days, [])
        self.assertEqual(self.tree(), before)

    def test_so_get_na_tabela_de_pagamentos(self):
        self.two_payouts()
        self.generator(NOW31).run_day()
        for method, path, _ in self.fake.calls:
            if path.endswith("/dividend_payouts"):
                self.assertEqual(method, "GET")

    def test_ficheiros_sem_ids_nem_campos_extra(self):
        extra = dict(pay("KingBJ", "pessoal", 1, 1.0), account_id="SEGREDO-CONTA-9", user_id="SEGREDO-UTILIZADOR-9")
        self.world.add_payout("ACHIP", "company", local(D30, 14, 10, 48), [extra])
        self.world.dividend_payouts[0]["majority_owner"] = "SEGREDO-UTILIZADOR-9"
        self.generator(NOW31).run_day()
        data = self.tree()[FILE30]
        self.assertNotIn(b"SEGREDO", data)
        self.assertEqual(set(self.document()["payouts"][0]["payments"][0]), {"beneficiary", "kind", "shares", "amount"})


class AmountsTests(PayoutsCase):
    def test_media_arredonda_metade_para_cima(self):
        self.world.add_payout("ACHIP", "company", local(D30, 14, 0), [pay("A", "pessoal", 1, 0.03), pay("B", "pessoal", 1, 0.02)])
        self.generator(NOW31).run_day()
        self.assertEqual(self.document()["payouts"][0]["average"], 0.03)

    def test_somas_exatas_sem_ruido_de_virgula_flutuante(self):
        parts = [pay("A", "pessoal", 1, 0.1), pay("B", "pessoal", 1, 0.2)]
        self.world.add_payout("ACHIP", "company", local(D30, 14, 0), parts)
        self.generator(NOW31).run_day()
        payout = self.document()["payouts"][0]
        self.assertEqual(payout["total_paid"], 0.3)
        self.assertEqual(payout["average"], 0.15)

    def test_percentagem_fracionaria_e_pool_maior_que_o_pago(self):
        self.world.add_payout("ACHIP", "company", local(D30, 14, 0), PNV, pct=33.5, pool=300.01)
        self.generator(NOW31).run_day()
        payout = self.document()["payouts"][0]
        self.assertEqual((payout["percentage"], payout["pool"], payout["total_paid"]), (33.5, 300.01, 300))

    def test_valores_grandes(self):
        self.world.add_payout("ACHIP", "company", local(D30, 14, 0), [pay("A", "empresa", 5, 40565.51), pay("B", "pessoal", 1, 2830.74)])
        self.generator(NOW31).run_day()
        payout = self.document()["payouts"][0]
        self.assertEqual(payout["total_paid"], 43396.25)
        self.assertEqual([p["amount"] for p in payout["payments"]], [40565.51, 2830.74])


class HardErrorTests(PayoutsCase):
    def reject(self, expected):
        with self.assertRaises(ValidationError) as ctx:
            self.generator(NOW31).run_day()
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertIn(expected, str(ctx.exception))
        self.assertEqual(self.tree(), {})

    def row(self):
        return self.world.add_payout("ACHIP", "company", local(D30, 14, 0), list(PNV))

    def test_soma_diferente_do_total_pago(self):
        self.row()["total_paid"] = 300.01
        self.reject("difere de total_paid")

    def test_tipo_de_ativo_desconhecido(self):
        self.row()["asset_type"] = "obrigacao"
        self.reject("asset_type desconhecido")

    def test_origem_desconhecida(self):
        self.row()["origin"] = "manual"
        self.reject("origin desconhecido")

    def test_tipo_de_beneficiario_desconhecido(self):
        self.row()["payments"][0] = pay("X", "robot", 1, 60.0)
        self.reject("kind desconhecido")

    def test_valor_com_mais_de_duas_casas(self):
        row = self.row()
        row["payments"][0] = pay("Chip_12", "pessoal", 100, 60.001)
        self.reject("mais de 2 casas decimais")

    def test_valor_negativo_ou_nulo(self):
        row = self.row()
        row["payments"][0] = pay("Chip_12", "pessoal", 100, -1.0)
        self.reject("amount inválido")
        row["payments"][0] = pay("Chip_12", "pessoal", 100, 0.0)
        self.reject("amount nulo")

    def test_pagamentos_vazios(self):
        self.row()["payments"] = []
        self.reject("payments vazio ou inválido")

    def test_shares_dos_beneficiarios_acima_do_total(self):
        self.row()["total_shares"] = 499
        self.reject("excedem total_shares")

    def test_campo_em_falta(self):
        start, end = day_window(D30)
        row = self.row() | {"paid_at": "2026-10-30T14:00:00+00:00"}
        del row["pool"]
        document, errors, _, _ = po.build_payouts(D30, [row], start, end)
        self.assertIsNone(document)
        self.assertTrue(any("falta o campo pool" in e for e in errors), errors)

    def test_total_de_shares_zero(self):
        self.row()["total_shares"] = 0
        self.reject("total_shares inválido")

    def test_mais_de_um_servidor(self):
        self.row()["guild_id"] = 123
        self.reject("mais de um servidor")

    def test_varios_erros_sao_todos_reportados(self):
        self.row()["origin"] = "manual"
        self.row()["asset_type"] = "x"
        with self.assertRaises(ValidationError) as ctx:
            self.generator(NOW31).run_day()
        self.assertEqual(len(ctx.exception.messages), 2)

    def test_um_erro_nos_pagamentos_nao_deixa_gravar_os_precos(self):
        self.row()["origin"] = "manual"
        self.reject("origin desconhecido")
        self.assertEqual(self.repo.price_days(), set())

    def test_fora_da_janela_do_dia(self):
        start, end = day_window(D30)
        rows = [self.row() | {"paid_at": end.isoformat()}]
        document, errors, _, _ = po.build_payouts(D30, rows, start, end)
        self.assertIsNone(document)
        self.assertTrue(any("paid_at fora da janela do dia" in e for e in errors), errors)
        rows[0]["paid_at"] = (start - timedelta(seconds=1)).isoformat()
        self.assertTrue(po.build_payouts(D30, rows, start, end)[1])


class LabelTests(PayoutsCase):
    def test_rotulo_com_aspeto_de_id_ou_vazio_passa_a_desconhecido_com_aviso(self):
        parts = [
            pay("Conta 962494501979578418", "pessoal", 1, 1.0), pay("  ", "pessoal", 1, 2.0),
            pay("KingBJ", "pessoal", 1, 3.0), pay(" dani ", "pessoal", 1, 4.0),
        ]
        self.world.add_payout("ACHIP", "company", local(D30, 14, 0), parts)
        result = self.generator(NOW31).run_day()
        labels = [p["beneficiary"] for p in self.document()["payouts"][0]["payments"]]
        self.assertEqual(labels, ["dani", "KingBJ", "Desconhecido", "Desconhecido"])
        self.assertEqual(sum("rótulo de beneficiário" in w for w in result.warnings), 2)
        self.assertNotIn(b"962494501979578418", self.tree()[FILE30])

    def test_digitos_curtos_nao_sao_ids(self):
        self.world.add_payout("ACHIP", "company", local(D30, 14, 0), [pay("Equipa 2020", "pessoal", 1, 1.0)])
        result = self.generator(NOW31).run_day()
        self.assertEqual(self.document()["payouts"][0]["payments"][0]["beneficiary"], "Equipa 2020")
        self.assertFalse(any("rótulo" in w for w in result.warnings))

    def test_acentos_e_simbolos_ficam_como_estao(self):
        self.world.add_payout("P&PNV", "asset", local(D30, 14, 0), [pay("Créditos & Fácil", "empresa", 1, 1.0)])
        self.generator(NOW31).run_day()
        self.assertIn("Créditos & Fácil".encode("utf-8"), self.tree()[FILE30])


class ImmutabilityTests(PayoutsCase):
    def late_payout(self):
        self.world.add_payout("P&PNV", "asset", local(D30, 23, 30), PNV)

    def test_pagamento_tardio_de_um_dia_arquivado_falha_sem_escrever(self):
        self.two_payouts_before()
        self.generator(NOW31).run_day()
        before = self.tree()
        self.late_payout()
        with self.assertRaises(ImmutabilityError) as ctx:
            self.generator(NOW31).run_day(only=D30)
        self.assertIn("pagamentos de dividendos", str(ctx.exception))
        self.assertIn("regenerate", str(ctx.exception))
        self.assertEqual(self.tree(), before)

    def two_payouts_before(self):
        self.world.add_payout("ACHIP", "company", local(D30, 14, 10, 48), ACHIP, pool=0.3, total_shares=4)

    def test_regenerar_acrescenta_o_pagamento_e_regista_no_manifesto(self):
        self.two_payouts_before()
        self.generator(NOW31).run_day()
        self.late_payout()
        later = NOW31 + timedelta(minutes=5)
        result = self.generator(later).run_regenerate(D30)
        self.assertEqual((result.days, result.payouts), ([D30], 2))
        entry = self.manifest()["2026-10-30"]
        self.assertEqual(entry["dividend_payouts"], 2)
        self.assertEqual(len(entry["regenerations"]), 1)
        self.assertEqual(len(self.document()["payouts"]), 2)
        self.assertEqual(verify_repo(self.repo).errors, [])

    def test_regenerar_um_dia_sem_pagamentos_antes_cobertos_pelo_codigo_antigo(self):
        self.generator(NOW31).run_day()
        entry = self.manifest()["2026-10-30"]
        self.assertEqual(entry["dividend_payouts"], 0)
        self.late_payout()
        self.generator(NOW31).run_regenerate(D30)
        self.assertEqual(self.manifest()["2026-10-30"]["dividend_payouts"], 1)

    def test_regenerar_nao_apaga_um_ficheiro_cujos_pagamentos_desapareceram(self):
        self.two_payouts_before()
        self.generator(NOW31).run_day()
        before = self.tree()
        self.world.dividend_payouts.clear()
        with self.assertRaises(ValidationError) as ctx:
            self.generator(NOW31).run_regenerate(D30)
        self.assertIn("já não tem pagamentos", str(ctx.exception))
        self.assertEqual(self.tree(), before)

    def test_regenerar_com_pagamentos_iguais_nao_faz_nada(self):
        self.two_payouts_before()
        self.generator(NOW31).run_day()
        before = self.tree()
        self.assertEqual(self.generator(NOW31).run_regenerate(D30).days, [])
        self.assertEqual(self.tree(), before)

    def test_dia_anterior_ao_registo_nunca_pede_nem_exige_pagamentos(self):
        self.world.add_payout("ACHIP", "company", local(D29, 14, 0), PNV)
        self.generator(NOW31).run_day()
        self.assertNotIn("dividend_payouts/2026-10-29.json", self.tree())
        self.assertNotIn("dividend_payouts", self.manifest()["2026-10-29"])


class RetentionTests(PipelineCase):
    """O bot apaga os pagamentos ao fim de 14 dias; o arquivo não pode afirmar que um dia não teve nenhum."""

    LAST = date(2026, 11, 20)
    NOW = lisbon_now(LAST, 23, 17)

    def setUp(self):
        super().setUp()
        self.world.standard()
        day = D30
        while day <= self.LAST:
            self.world.fill_day(day)
            day += timedelta(days=1)
        self.world.sync_prices()

    def manifest(self):
        return json.loads(self.tree()["manifest.json"])["days"]

    def test_dias_fora_da_retencao_ficam_sem_registo_e_com_aviso(self):
        self.world.add_payout("P&PNV", "asset", local(D30, 9, 57, 50), PNV)
        self.world.add_payout("P&PNV", "asset", local(date(2026, 11, 6), 12, 0), PNV)
        self.world.add_payout("P&PNV", "asset", local(date(2026, 11, 7), 12, 0), PNV)
        result = self.generator(self.NOW).run_backfill(start=D30)
        days = self.manifest()
        self.assertNotIn("dividend_payouts", days["2026-10-30"])
        self.assertNotIn("dividend_payouts", days["2026-11-06"])
        self.assertEqual(days["2026-11-07"]["dividend_payouts"], 1)
        self.assertEqual(days["2026-11-20"]["dividend_payouts"], 0)
        files = self.tree()
        self.assertNotIn(FILE30, files)
        self.assertIn("dividend_payouts/2026-11-07.json", files)
        self.assertNotIn("dividend_payouts/2026-11-06.json", files)
        self.assertTrue(any("2026-10-30: os pagamentos de dividendos já passaram a retenção" in w for w in result.warnings))
        self.assertFalse(any("2026-11-07: os pagamentos" in w for w in result.warnings))
        asked = {dict(p)["paid_at"] for m, path, p in self.fake.calls if path.endswith("/dividend_payouts")}
        self.assertEqual(len(asked), 14)

    def test_verify_nao_se_queixa_de_dias_gerados_depois_da_retencao(self):
        self.generator(self.NOW).run_backfill(start=D30)
        report = verify_repo(self.repo)
        self.assertEqual((report.errors, report.warnings), ([], []))

    def test_regenerar_um_dia_antigo_mantem_o_ficheiro_e_o_manifesto(self):
        self.world.dividend_payouts.clear()
        self.world.add_payout("P&PNV", "asset", local(D30, 9, 57, 50), PNV)
        self.world.sync_prices(until=local(date(2026, 11, 1), 0))
        self.generator(lisbon_now(D31, 23, 17)).run_backfill(start=D30)
        before = self.tree()
        self.world.dividend_payouts.clear()
        self.assertEqual(self.generator(self.NOW).run_day(only=D30).days, [])
        self.assertEqual(self.tree(), before)
        self.world.tick(D30, 12, 30, "NEWTE", "company", 99.0)
        result = self.generator(self.NOW).run_regenerate(D30)
        self.assertEqual(result.days, [D30])
        after = self.tree()
        self.assertEqual(after[FILE30], before[FILE30])
        entry = json.loads(after["manifest.json"])["days"]["2026-10-30"]
        self.assertEqual(entry["dividend_payouts"], 1)
        self.assertEqual(len(entry["regenerations"]), 1)
        self.assertEqual(verify_repo(self.repo).errors, [])


class VerifyTests(PayoutsCase):
    def setUp(self):
        super().setUp()
        self.world.add_payout("P&PNV", "asset", local(D30, 9, 57, 50), PNV)
        self.generator(NOW31).run_day()

    def edit(self, rel, old, new):
        path = self.root / rel
        data = path.read_bytes()
        self.assertIn(old, data)
        path.write_bytes(data.replace(old, new, 1))

    def errors(self):
        return verify_repo(self.repo).errors

    def test_integro(self):
        self.assertEqual(self.errors(), [])

    def test_media_adulterada(self):
        self.edit(FILE30, b'"average": 100', b'"average": 101')
        self.assertTrue(any("não corresponde ao que as regras" in e for e in self.errors()), self.errors())

    def test_valor_adulterado_quebra_a_soma(self):
        self.edit(FILE30, b'"amount": 180', b'"amount": 181')
        errors = self.errors()
        self.assertTrue(any("difere de total_paid" in e for e in errors), errors)
        self.assertTrue(any("sha256" in e or "SHA256SUMS" in e for e in errors), errors)

    def test_pagamentos_do_dia_fora_de_ordem(self):
        self.world.add_payout("ACHIP", "company", local(D30, 14, 10, 48), ACHIP, pool=0.3, total_shares=4)
        self.generator(NOW31 + timedelta(minutes=1)).run_regenerate(D30)
        document = self.document()
        document["payouts"].reverse()
        (self.root / FILE30).write_bytes((json.dumps(document, indent=2) + "\n").encode("utf-8"))
        self.assertTrue(any("não corresponde ao que as regras" in e for e in self.errors()), self.errors())

    def test_ordem_trocada(self):
        document = self.document()
        document["payouts"][0]["payments"].reverse()
        (self.root / FILE30).write_bytes((json.dumps(document, indent=2) + "\n").encode("utf-8"))
        self.assertTrue(any("não corresponde ao que as regras" in e for e in self.errors()), self.errors())

    def test_chave_que_sugere_conta(self):
        self.edit(FILE30, b'"beneficiary": "Estado"', b'"account_id": "Estado"')
        self.assertTrue(any("account_id" in e for e in self.errors()), self.errors())

    def test_ficheiro_em_falta(self):
        (self.root / FILE30).unlink()
        self.assertTrue(any("o ficheiro não existe" in e for e in self.errors()), self.errors())

    def test_ficheiro_com_o_manifesto_a_zero(self):
        (self.root / "dividend_payouts/2026-10-31.json").write_bytes(b"{}\n")
        self.assertTrue(any("manifesto indica 0 pagamentos" in e for e in self.errors()), self.errors())

    def test_ficheiro_sem_dia_no_manifesto(self):
        (self.root / "dividend_payouts/2026-11-05.json").write_bytes(b"{}\n")
        self.assertTrue(any("pagamentos sem dia no manifesto" in e for e in self.errors()), self.errors())

    def test_ficheiro_num_dia_sem_chave_no_manifesto(self):
        (self.root / "dividend_payouts/2026-10-29.json").write_bytes(b"{}\n")
        self.assertTrue(any("o manifesto não indica pagamentos" in e for e in self.errors()), self.errors())

    def test_contagem_do_manifesto_errada(self):
        manifest = json.loads(self.tree()["manifest.json"])
        manifest["days"]["2026-10-30"]["dividend_payouts"] = 2
        (self.root / "manifest.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
        self.assertTrue(any("tem 1 pagamentos mas o manifesto indica 2" in e for e in self.errors()), self.errors())

    def test_json_ilegivel(self):
        (self.root / FILE30).write_bytes(b"isto nao e json\n")
        self.assertTrue(any("JSON ilegível" in e for e in self.errors()), self.errors())

    def test_contagem_invalida_no_manifesto(self):
        manifest = json.loads(self.tree()["manifest.json"])
        manifest["days"]["2026-10-31"]["dividend_payouts"] = -1
        (self.root / "manifest.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
        self.assertTrue(any("dividend_payouts inválido" in e for e in self.errors()), self.errors())

    def test_dia_coberto_sem_chave_so_avisa(self):
        manifest = json.loads(self.tree()["manifest.json"])
        del manifest["days"]["2026-10-31"]["dividend_payouts"]
        (self.root / "manifest.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
        warnings = verify_repo(self.repo).warnings
        self.assertTrue(any("2026-10-31: sem registo de pagamentos" in w for w in warnings), warnings)
        self.assertFalse(any("2026-10-29" in w for w in warnings))


class PagesAndGuardTests(PayoutsCase):
    def build(self):
        self.world.add_payout("P&PNV", "asset", local(D30, 9, 57, 50), PNV)
        self.generator(NOW31).run_day()
        out = Path(self.tmp.name) / "_site"
        write_web(self.root)
        written = build_pages(self.repo, out, NOW31, "CNAinput/dailydumps")
        return out, written

    def test_o_site_serve_os_pagamentos_e_a_api_aponta_para_o_ultimo_dia(self):
        out, written = self.build()
        self.assertIn(FILE30, written)
        self.assertEqual((out / FILE30).read_bytes(), self.tree()[FILE30])
        self.assertNotIn("dividend_payouts/2026-10-31.json", written)
        latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
        self.assertIsNone(latest["files"]["dividend_payouts"])

    def test_latest_aponta_para_o_ficheiro_quando_o_ultimo_dia_teve_pagamentos(self):
        self.world.add_payout("P&PNV", "asset", local(D31, 12, 0), PNV)
        self.generator(NOW31).run_day()
        write_web(self.root)
        out = Path(self.tmp.name) / "_site"
        build_pages(self.repo, out, NOW31)
        latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual(latest["files"]["dividend_payouts"], "dividend_payouts/2026-10-31.json")

    def test_o_site_web_nao_pode_ocupar_a_pasta(self):
        self.generator(NOW31).run_day()
        write_web(self.root, {"dividend_payouts/x.html": "<!doctype html>\n"})
        with self.assertRaises(ValidationError) as ctx:
            build_pages(self.repo, Path(self.tmp.name) / "_site", NOW31)
        self.assertIn("dividend_payouts/x.html", str(ctx.exception))

    def test_pull_requests_nao_podem_mexer_nos_pagamentos(self):
        self.assertEqual(protected_changes(["dividend_payouts/2026-10-30.json", "docs/SCHEMA.md"]), [FILE30])


class RepoTests(unittest.TestCase):
    def test_caminho_e_dias(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Repo(folder)
            self.assertEqual(repo.payouts_rel(D30), FILE30)
            self.assertEqual(repo.payout_days(), set())
            (Path(folder) / "dividend_payouts").mkdir()
            (Path(folder) / FILE30).write_bytes(b"{}\n")
            (Path(folder) / "dividend_payouts" / "notas.json").write_bytes(b"{}\n")
            self.assertEqual(repo.payout_days(), {D30})
            self.assertEqual(repo.tracked_files(), [FILE30, "dividend_payouts/notas.json"])

    def test_dias_cobertos(self):
        self.assertFalse(po.covers(D29))
        self.assertTrue(po.covers(D30))
        self.assertTrue(po.covers(date(2027, 1, 1)))

    def test_pagamentos_do_dia_ordenados_por_instante_e_depois_por_codigo(self):
        start, end = day_window(D30)

        def row(code, asset_type, hour):
            return {
                "code": code, "asset_type": asset_type, "paid_at": f"2026-10-30T{hour}:00:00+00:00", "percentage": 10,
                "pool": 1, "total_paid": 1, "total_shares": 1, "origin": "bot", "payments": [pay("A", "pessoal", 1, 1)],
            }

        rows = [row("ZZZ", "asset", "12"), row("BBB", "company", "12"), row("AAA", "company", "13"), row("BBB", "asset", "12")]
        document, errors, _, _ = po.build_payouts(D30, rows, start, end)
        self.assertEqual(errors, [])
        self.assertEqual(
            [(p["paid_at"][11:13], p["code"], p["asset_type"]) for p in document["payouts"]],
            [("12", "BBB", "asset"), ("12", "BBB", "company"), ("12", "ZZZ", "asset"), ("13", "AAA", "company")],
        )

    def test_decimais_exatos_no_documento(self):
        start, end = day_window(D30)
        row = {
            "code": "ACHIP", "asset_type": "company", "paid_at": "2026-10-30T14:00:00+00:00", "percentage": Decimal("30"),
            "pool": Decimal("0.30"), "total_paid": Decimal("0.3"), "total_shares": 3, "origin": "bot",
            "payments": [pay("A", "pessoal", 1, Decimal("0.1")), pay("B", "pessoal", 2, Decimal("0.2"))],
        }
        document, errors, _, guilds = po.build_payouts(D30, [row], start, end)
        self.assertEqual((errors, guilds), ([], set()))
        self.assertEqual(document["payouts"][0]["average"], Decimal("0.15"))
        self.assertEqual(document["payouts"][0]["total_paid"], Decimal("0.30"))


if __name__ == "__main__":
    unittest.main()
