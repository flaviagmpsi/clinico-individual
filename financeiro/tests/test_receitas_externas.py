"""Ganhos do psicólogo fora da clínica particular (ADR-136): supervisão, ONG, CLT, bicos.

Espelha os testes de despesa, do outro lado do caixa:
- `Ocorrencias` — o ganho mensal é uma linha e aparece em todo mês; o avulso, no mês dele.
- `Recebimentos` — marcar como recebido, desfazer, encerrar, excluir.
- `Pendencia` — o que ainda não caiu conta como pendência (controle do que há a receber).
- `NoFluxo` — os externos somam no total de receitas, com o detalhamento clínica × fora.
- `NoPainel` — o "quanto ganhei no mês" fica completo, e o a receber vira pendência.
- `Isolamento` — ADR-001, nem por SQL cru.
- `Telas` — cadastrar e receber pela tela, e a fronteira entre psicólogos.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from contas.models import Psicologo
from core import contexto, db
from financeiro import despesas, receitas_externas
from financeiro.models import Pagamento, RecebimentoExterno, ReceitaExterna

SENHA = "senha-de-teste-123"
PIX = Pagamento.Forma.PIX
AGOSTO, SETEMBRO = date(2026, 8, 1), date(2026, 9, 1)


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


class BaseReceitas(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.receita@exemplo.com", "11111111111", "515151")
        cls.bruno = criar_psicologo("bruno.receita@exemplo.com", "22222222222", "525252")
        with contexto.como(cls.ana.pk):
            cls.supervisao = ReceitaExterna.objects.create(
                descricao="Supervisão", valor=Decimal("600"), forma=PIX, vencimento=date(2026, 1, 10),
                mensal=True, entra_no_carne_leao=True)
            cls.clt = ReceitaExterna.objects.create(
                descricao="CLT hospital", valor=Decimal("3000"), forma=PIX, vencimento=date(2026, 1, 5),
                mensal=True, entra_no_carne_leao=False)
            cls.bico = ReceitaExterna.objects.create(
                descricao="Palestra", valor=Decimal("800"), forma=PIX, vencimento=date(2026, 8, 20))

    def do_mes(self, mes):
        with contexto.como(self.ana.pk):
            return receitas_externas.receitas_do_mes(mes.year, mes.month)


class Ocorrencias(BaseReceitas):
    def test_mensal_aparece_todo_mes_e_avulso_so_no_dele(self):
        self.assertEqual({o.receita.descricao for o in self.do_mes(AGOSTO)},
                         {"Supervisão", "CLT hospital", "Palestra"})
        self.assertEqual({o.receita.descricao for o in self.do_mes(SETEMBRO)},
                         {"Supervisão", "CLT hospital"})

    def test_valor_e_carne_leao_vem_do_cadastro(self):
        por_nome = {o.receita.descricao: o for o in self.do_mes(AGOSTO)}
        self.assertEqual(por_nome["Supervisão"].valor, Decimal("600"))
        self.assertTrue(por_nome["Supervisão"].entra_no_carne_leao)
        self.assertFalse(por_nome["CLT hospital"].entra_no_carne_leao)

    def test_avulso_nao_pode_ter_fim(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                ReceitaExterna.objects.create(descricao="X", valor=Decimal("1"), forma=PIX,
                                              vencimento=date(2026, 8, 1), mensal=False, fim=date(2026, 9, 1))


class Recebimentos(BaseReceitas):
    def test_receber_marca_o_mes_e_guarda_o_valor(self):
        with contexto.como(self.ana.pk):
            receitas_externas.receber(self.bico, AGOSTO, recebido_em=date(2026, 8, 21), valor=Decimal("800"))
            o = [x for x in receitas_externas.receitas_do_mes(2026, 8) if x.receita.pk == self.bico.pk][0]
        self.assertTrue(o.recebida)
        self.assertEqual(o.valor, Decimal("800"))

    def test_nao_recebe_duas_vezes_o_mesmo_mes(self):
        with contexto.como(self.ana.pk):
            receitas_externas.receber(self.supervisao, AGOSTO, recebido_em=date(2026, 8, 10))
            with self.assertRaises(ValidationError):
                receitas_externas.receber(self.supervisao, AGOSTO, recebido_em=date(2026, 8, 11))

    def test_desfazer_devolve_a_a_receber(self):
        with contexto.como(self.ana.pk):
            receitas_externas.receber(self.supervisao, AGOSTO, recebido_em=date(2026, 8, 10))
            receitas_externas.desfazer_recebimento(self.supervisao, AGOSTO)
            o = [x for x in receitas_externas.receitas_do_mes(2026, 8) if x.receita.pk == self.supervisao.pk][0]
        self.assertFalse(o.recebida)

    def test_encerrar_para_de_aparecer_depois(self):
        with contexto.como(self.ana.pk):
            receitas_externas.encerrar(self.supervisao, AGOSTO)
            self.assertNotIn("Supervisão", {o.receita.descricao for o in receitas_externas.receitas_do_mes(2026, 9)})
            self.assertIn("Supervisão", {o.receita.descricao for o in receitas_externas.receitas_do_mes(2026, 8)})

    def test_excluir_recusa_com_recebimento(self):
        with contexto.como(self.ana.pk):
            receitas_externas.receber(self.bico, AGOSTO, recebido_em=date(2026, 8, 21))
            with self.assertRaises(ValidationError):
                receitas_externas.excluir(self.bico)


class NoFluxo(BaseReceitas):
    def test_externos_somam_no_total_com_detalhamento(self):
        with contexto.como(self.ana.pk):
            receitas_externas.receber(self.supervisao, AGOSTO, recebido_em=date(2026, 8, 10))
            fluxo = despesas.fluxo_de_caixa(2026, 8)
        # Agosto: supervisão 600 (recebida) + CLT 3000 + palestra 800 (a receber) = 4400 em externos, sem clínica.
        self.assertEqual(fluxo.externas_recebidas, Decimal("600"))
        self.assertEqual(fluxo.externas_a_receber, Decimal("3800"))
        self.assertEqual(fluxo.total_externas, Decimal("4400"))
        self.assertEqual(fluxo.total_clinica, Decimal("0"))
        self.assertEqual(fluxo.total_receitas, Decimal("4400"))
        self.assertEqual(fluxo.recebidas_total, Decimal("600"))


class Pendencia(BaseReceitas):
    def test_a_receber_do_mes_e_de_antes_conta_como_pendencia(self):
        with contexto.como(self.ana.pk):
            # "hoje" em setembro/2026: supervisão e CLT de ago e set a receber, mais a palestra de agosto.
            pendentes = receitas_externas.recebimentos_pendentes(date(2026, 9, 15))
            nomes = [o.receita.descricao for o in pendentes]
        self.assertIn("Palestra", nomes)          # avulso de agosto, não recebido
        self.assertIn("Supervisão", nomes)         # mensal
        # Não traz mês futuro (outubro em diante): o que ainda vai vencer é previsão, não pendência.
        self.assertTrue(all(o.mes <= date(2026, 9, 1) for o in pendentes))


class Isolamento(TransactionTestCase):
    def test_sql_cru_so_devolve_o_proprio_dono(self):
        if connection.vendor != "postgresql":
            self.skipTest("RLS exige PostgreSQL.")
        ana = criar_psicologo("ana.recrls@t.com", "11111111111", "535353")
        bruno = criar_psicologo("bruno.recrls@t.com", "22222222222", "545454")
        for psi in (ana, bruno):
            with contexto.como(psi.pk):
                ReceitaExterna.objects.create(descricao=f"R{psi.pk}", valor=Decimal("100"), forma=PIX,
                                              vencimento=date(2026, 8, 1))

        def quantas(psicologo_id):
            with transaction.atomic():
                db.assumir_papel_da_aplicacao()
                db.aplicar_escopo(psicologo_id, administradora=False)
                with connection.cursor() as c:
                    c.execute("SELECT count(*) FROM financeiro_receitaexterna")
                    return c.fetchone()[0]

        self.assertEqual(quantas(ana.pk), 1)
        self.assertEqual(quantas(bruno.pk), 1)


class Telas(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.rectela@t.com", "11111111111", "818282")
        self.bruno = criar_psicologo("bruno.rectela@t.com", "22222222222", "828383")
        with contexto.como(self.bruno.pk):
            self.do_bruno = ReceitaExterna.objects.create(descricao="Bico do Bruno", valor=Decimal("100"),
                                                          forma=PIX, vencimento=date(2026, 8, 1))

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def test_cadastrar_pela_tela(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("financeiro:receita_nova"), {
            "descricao": "Supervisão da Bete", "valor": "600,00", "forma": PIX,
            "vencimento": "2026-08-10", "entra_no_carne_leao": "on"})
        self.assertEqual(resposta.status_code, 302)
        with contexto.como(self.ana.pk):
            self.assertTrue(ReceitaExterna.objects.filter(descricao="Supervisão da Bete").exists())

    def test_nao_recebe_nem_edita_ganho_alheio(self):
        self.entrar(self.ana)
        receber = reverse("financeiro:receita_receber", args=[self.do_bruno.pk])
        self.assertEqual(self.client.post(receber, {"mes": "2026-08"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("financeiro:receita_editar", args=[self.do_bruno.pk])).status_code, 404)
