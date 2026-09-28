"""Despesas da clínica e fluxo de caixa (ADR-083).

- `Ocorrencias` — a despesa mensal é uma linha e aparece em todo mês; a de um mês só, no mês dela.
- `Baixas` — marcar como paga, desfazer, encerrar e excluir; o valor pago fica no mês em que saiu.
- `FluxoDeCaixa` — os sete números que o usuário pediu, por competência.
- `Isolamento` e `NoBanco` — ADR-001.
- `Telas` — cadastrar, marcar como paga pela tela, as três abas, e a fronteira entre psicólogos.

Datas de 2026 fixas e anteriores ao dia em que o teste roda, como no resto do financeiro.
"""

from datetime import date, datetime, time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from atendimentos import servicos as agenda
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto, db
from financeiro import despesas, servicos
from financeiro.models import BaixaDeDespesa, Despesa, Pagamento
from pacientes.models import CondicaoCobranca, Paciente
from pacientes.servicos import cadastrar_paciente

SENHA = "senha-de-teste-123"
AGOSTO, SETEMBRO = date(2026, 8, 1), date(2026, 9, 1)


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


class BaseDespesas(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.despesa@exemplo.com", "11111111111", "919191")
        cls.bruno = criar_psicologo("bruno.despesa@exemplo.com", "22222222222", "929292")
        with contexto.como(cls.ana.pk):
            cls.aluguel = Despesa.objects.create(descricao="Aluguel da sala", valor=Decimal("1200"), mensal=True,
                                                 vencimento=date(2026, 1, 31))
            cls.curso = Despesa.objects.create(descricao="Curso", valor=Decimal("890"), vencimento=date(2026, 8, 12))
        with contexto.como(cls.bruno.pk):
            cls.do_bruno = Despesa.objects.create(descricao="Sala do Bruno", valor=Decimal("900"), mensal=True,
                                                  vencimento=date(2026, 1, 5))

    def do_mes(self, mes):
        with contexto.como(self.ana.pk):
            return despesas.despesas_do_mes(mes.year, mes.month)


class Ocorrencias(BaseDespesas):
    def test_mensal_aparece_em_todo_mes_e_avulsa_so_no_dela(self):
        self.assertEqual([o.despesa.descricao for o in self.do_mes(AGOSTO)], ["Curso", "Aluguel da sala"])
        self.assertEqual([o.despesa.descricao for o in self.do_mes(SETEMBRO)], ["Aluguel da sala"])
        self.assertEqual(self.do_mes(date(2025, 12, 1)), [])  # antes do primeiro vencimento

    def test_dia_31_cai_no_ultimo_dia_do_mes_mais_curto(self):
        self.assertEqual(self.do_mes(date(2026, 2, 1))[0].vencimento, date(2026, 2, 28))
        self.assertEqual(self.do_mes(date(2026, 3, 1))[0].vencimento, date(2026, 3, 31))

    def test_encerrada_para_de_aparecer_depois_do_ultimo_mes(self):
        with contexto.como(self.ana.pk):
            despesas.encerrar(self.aluguel, AGOSTO)
        self.assertEqual(len(self.do_mes(AGOSTO)), 2)
        self.assertEqual(self.do_mes(SETEMBRO), [])
        with contexto.como(self.ana.pk), self.assertRaises(ValidationError):
            despesas.encerrar(self.curso, AGOSTO)  # a de um mês só se exclui, não se encerra

    def test_atraso_e_vencida_e_nao_paga(self):
        aluguel = self.do_mes(AGOSTO)[1]
        self.assertTrue(aluguel.atrasada(date(2026, 9, 1)))
        self.assertFalse(aluguel.atrasada(date(2026, 8, 31)))  # vence hoje: ainda não atrasou


class Baixas(BaseDespesas):
    def test_pagar_marca_so_aquele_mes_e_guarda_o_valor_pago(self):
        with contexto.como(self.ana.pk):
            despesas.pagar(self.aluguel, AGOSTO, pago_em=date(2026, 8, 28))
            self.aluguel.valor = Decimal("1350")  # reajuste
            self.aluguel.save()
        agosto, setembro = self.do_mes(AGOSTO)[1], self.do_mes(SETEMBRO)[0]
        self.assertTrue(agosto.paga)
        self.assertEqual(agosto.valor, Decimal("1200"))  # o que saiu do caixa não muda com o reajuste
        self.assertFalse(setembro.paga)
        self.assertEqual(setembro.valor, Decimal("1350"))

    def test_nao_paga_duas_vezes_nem_no_futuro_nem_em_mes_que_nao_existe(self):
        with contexto.como(self.ana.pk):
            despesas.pagar(self.aluguel, AGOSTO, pago_em=date(2026, 8, 28))
            for despesa, mes, pago_em in [(self.aluguel, AGOSTO, date(2026, 8, 29)),
                                          (self.aluguel, SETEMBRO, date(2099, 1, 1)),
                                          (self.curso, SETEMBRO, date(2026, 9, 1))]:
                with self.subTest(despesa=despesa.descricao, mes=mes), self.assertRaises(ValidationError):
                    despesas.pagar(despesa, mes, pago_em=pago_em)

    def test_desfazer_volta_a_ficar_em_aberto(self):
        with contexto.como(self.ana.pk):
            despesas.pagar(self.curso, AGOSTO, pago_em=date(2026, 8, 12))
            despesas.desfazer_pagamento(self.curso, AGOSTO)
            with self.assertRaises(ValidationError):
                despesas.desfazer_pagamento(self.curso, AGOSTO)
        self.assertFalse(self.do_mes(AGOSTO)[0].paga)

    def test_despesa_com_mes_pago_nao_se_exclui(self):
        with contexto.como(self.ana.pk):
            despesas.pagar(self.aluguel, AGOSTO, pago_em=date(2026, 8, 28))
            with self.assertRaises(ValidationError):
                despesas.excluir(self.aluguel)
            despesas.excluir(self.curso)
            self.assertEqual([d.descricao for d in Despesa.objects.all()], ["Aluguel da sala"])

    def test_ultimo_mes_so_para_mensal(self):
        with contexto.como(self.ana.pk), self.assertRaises(ValidationError):
            Despesa.objects.create(descricao="Avulsa", valor=Decimal("10"), vencimento=date(2026, 8, 1),
                                   fim=date(2026, 9, 30))


class FluxoDeCaixa(BaseDespesas):
    def test_os_sete_numeros_do_mes(self):
        """Agosto: duas sessões de R$ 200 (uma paga) e duas despesas (o aluguel pago)."""
        with contexto.como(self.ana.pk):
            caso = cadastrar_paciente(Paciente(nome="Marcos"), valor=Decimal("200"),
                                      modalidade=CondicaoCobranca.Modalidade.POR_SESSAO, vigente_desde=date(2026, 1, 1))
            for dia in (5, 12):
                consulta = agenda.cadastrar_avulsa(
                    caso, estado=Consulta.Estado.REALIZADA,
                    inicio=timezone.make_aware(datetime.combine(date(2026, 8, dia), time(10))))
            servicos.registrar_pagamento_sessao(consulta, data=date(2026, 8, 12), forma=Pagamento.Forma.PIX)
            despesas.pagar(self.aluguel, AGOSTO, pago_em=date(2026, 8, 31))
            fluxo = despesas.fluxo_de_caixa(2026, 8)
        self.assertEqual((fluxo.receitas_recebidas, fluxo.receitas_a_receber, fluxo.total_receitas),
                         (Decimal("200"), Decimal("200"), Decimal("400")))
        self.assertEqual((fluxo.despesas_pagas, fluxo.despesas_a_pagar, fluxo.total_despesas),
                         (Decimal("1200"), Decimal("890"), Decimal("2090")))
        self.assertEqual(fluxo.resultado, Decimal("-1690"))
        self.assertEqual(fluxo.resultado_realizado, Decimal("-1000"))

    def test_mes_sem_nada_e_zero_e_o_ano_tem_doze_meses(self):
        with contexto.como(self.ana.pk):
            vazio = despesas.fluxo_de_caixa(2025, 6)
            ano = despesas.fluxo_do_ano(2026)
        self.assertEqual((vazio.total_receitas, vazio.total_despesas, vazio.resultado), (0, 0, 0))
        self.assertEqual([f.mes.month for f in ano], list(range(1, 13)))
        self.assertEqual(ano[7].total_despesas, Decimal("2090"))
        self.assertEqual(ano[11].despesas_a_pagar, Decimal("1200"))  # dezembro: a mensal já está prevista

    def test_cada_um_ve_so_as_proprias_despesas(self):
        with contexto.como(self.bruno.pk):
            self.assertEqual([o.despesa.descricao for o in despesas.despesas_do_mes(2026, 8)], ["Sala do Bruno"])
            with self.assertRaises(ValidationError):
                BaixaDeDespesa.objects.create(despesa=self.aluguel, mes=AGOSTO, pago_em=AGOSTO, valor=Decimal("1"))


class NoBanco(TransactionTestCase):
    def test_sql_cru_so_devolve_as_despesas_do_dono(self):
        if connection.vendor != "postgresql":
            self.skipTest("RLS exige PostgreSQL.")
        ana = criar_psicologo("ana.despbanco@exemplo.com", "33333333333", "939393")
        bruno = criar_psicologo("bruno.despbanco@exemplo.com", "44444444444", "949494")
        for psicologo in (ana, bruno):
            with contexto.como(psicologo.pk):
                despesa = Despesa.objects.create(descricao="Sala", valor=Decimal("100"), vencimento=AGOSTO)
                despesas.pagar(despesa, AGOSTO, pago_em=AGOSTO)
        for tabela in ["financeiro_despesa", "financeiro_baixadedespesa"]:
            with self.subTest(tabela=tabela), transaction.atomic():
                db.assumir_papel_da_aplicacao()
                db.aplicar_escopo(ana.pk)
                with connection.cursor() as cursor:
                    cursor.execute(f"SELECT DISTINCT psicologo_id FROM {tabela}")
                    self.assertEqual({linha[0] for linha in cursor.fetchall()}, {ana.pk})


class Telas(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.teladesp@exemplo.com", "11111111111", "959595")
        self.bruno = criar_psicologo("bruno.teladesp@exemplo.com", "22222222222", "969696")
        with contexto.como(self.ana.pk):
            self.aluguel = Despesa.objects.create(descricao="Aluguel da sala", valor=Decimal("1200"), mensal=True,
                                                  vencimento=date(2026, 1, 5))
        with contexto.como(self.bruno.pk):
            self.do_bruno = Despesa.objects.create(descricao="Sala do Bruno", valor=Decimal("900"),
                                                   vencimento=date(2026, 8, 5))

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def test_exigem_login(self):
        for rota in [reverse("financeiro:despesas"), reverse("financeiro:despesa_nova"), reverse("financeiro:fluxo")]:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 302)

    def test_as_tres_abas_do_financeiro_mostram_o_mesmo_mes(self):
        self.entrar(self.ana)
        for rota in ["financeiro:mes", "financeiro:despesas", "financeiro:fluxo"]:
            with self.subTest(rota=rota):
                resposta = self.client.get(reverse(rota), {"mes": "2026-08"})
                self.assertContains(resposta, "Agosto de 2026")
                self.assertContains(resposta, f"{reverse('financeiro:fluxo')}?mes=2026-08")

    def test_cadastrar_pela_tela_com_valor_mascarado(self):
        self.entrar(self.ana)
        # ADR-099: a despesa passou a ter **categoria** do carnê-leão, e ela é obrigatória — sem ela o formulário
        # volta com erro em vez de redirecionar.
        resposta = self.client.post(reverse("financeiro:despesa_nova"), {
            "categoria": "SUPERVISAO", "descricao": "Supervisão clínica", "valor": "1.400,50",
            "vencimento": "2026-08-20", "mensal": "on"})
        self.assertRedirects(resposta, reverse("financeiro:despesas") + "?mes=2026-08", fetch_redirect_response=False)
        despesa = Despesa.objetos_todos.get(descricao="Supervisão clínica")
        self.assertEqual((despesa.valor, despesa.mensal, despesa.psicologo_id), (Decimal("1400.50"), True, self.ana.pk))

    def test_marcar_como_paga_e_desfazer_pela_tela(self):
        self.entrar(self.ana)
        lista = reverse("financeiro:despesas")
        self.assertContains(self.client.get(lista, {"mes": "2026-08"}), "Em atraso")
        self.client.post(reverse("financeiro:despesa_pagar", args=[self.aluguel.pk]), {"mes": "2026-08"})
        resposta = self.client.get(lista, {"mes": "2026-08"})
        self.assertContains(resposta, "Paga")
        self.assertNotContains(resposta, "Em atraso")
        self.assertContains(self.client.get(reverse("financeiro:fluxo"), {"mes": "2026-08"}), "1200,00")
        self.client.post(reverse("financeiro:despesa_desfazer", args=[self.aluguel.pk]), {"mes": "2026-08"})
        self.assertFalse(BaixaDeDespesa.objetos_todos.filter(despesa=self.aluguel).exists())

    def test_nao_ve_nem_mexe_na_despesa_de_outro_psicologo(self):
        self.entrar(self.ana)
        self.assertNotContains(self.client.get(reverse("financeiro:despesas"), {"mes": "2026-08"}), "Sala do Bruno")
        for rota in ["financeiro:despesa_pagar", "financeiro:despesa_excluir", "financeiro:despesa_encerrar"]:
            with self.subTest(rota=rota):
                resposta = self.client.post(reverse(rota, args=[self.do_bruno.pk]), {"mes": "2026-08"})
                self.assertEqual(resposta.status_code, 404)
        self.assertEqual(self.client.get(reverse("financeiro:despesa_editar", args=[self.do_bruno.pk])).status_code, 404)
        self.assertTrue(Despesa.objetos_todos.filter(pk=self.do_bruno.pk).exists())
