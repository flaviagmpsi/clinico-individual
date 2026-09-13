"""A troca de cobrança vale no dia 1º do mês seguinte — nunca na hora.

Decisão tomada com o usuário a partir de dois exemplos: valer na hora faz o psicólogo atender de
graça (sessão → mensalidade no meio do mês) ou o paciente pagar em dobro (mensalidade → sessão).
Estes testes guardam a regra e as três consequências registradas em `servicos.trocar_condicao`.

As datas saem de `date.today()` e não de uma data fixa: a condição inicial do caso é criada "hoje",
e fixar setembro de 2026 faria o teste quebrar no dia em que rodasse em outro mês.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo
from core import contexto
from pacientes.models import CondicaoCobranca, Paciente
from pacientes.servicos import (
    cadastrar_paciente,
    caso_individual_de,
    primeiro_dia_do_mes_seguinte,
    trocar_condicao,
)

SENHA = "senha-de-teste-123"
_MENSAL = CondicaoCobranca.Modalidade.MENSAL
_INICIO = CondicaoCobranca.Vencimento.INICIO_DO_MES


def criar_psicologo(email, cpf, crp_numero):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp_numero)


class Calendario(TestCase):
    def test_meio_do_mes_vira_no_dia_primeiro_seguinte(self):
        self.assertEqual(primeiro_dia_do_mes_seguinte(date(2026, 9, 15)), date(2026, 10, 1))

    def test_dezembro_vira_janeiro_do_ano_seguinte(self):
        self.assertEqual(primeiro_dia_do_mes_seguinte(date(2026, 12, 31)), date(2027, 1, 1))

    def test_dia_primeiro_tambem_espera_o_proximo_mes(self):
        """Mesmo trocando no dia 1º, a cobrança do mês pode já ter sido gerada (mensalidade que
        vence no início) — a regra não abre exceção."""
        self.assertEqual(primeiro_dia_do_mes_seguinte(date(2026, 9, 1)), date(2026, 10, 1))


class TrocaDeCobranca(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.troca@exemplo.com", "11111111111", "717171")
        with contexto.como(cls.ana.pk):
            cls.marcos = Paciente(nome="Marcos")
            cls.caso_marcos = cadastrar_paciente(cls.marcos, valor=Decimal("200"))
            cls.sem_valor = Paciente(nome="Sem Valor")
            cls.caso_sem_valor = cadastrar_paciente(cls.sem_valor)

    def test_troca_vale_no_primeiro_dia_do_mes_seguinte(self):
        hoje = date.today()
        virada = primeiro_dia_do_mes_seguinte(hoje)
        with contexto.como(self.ana.pk):
            nova = trocar_condicao(self.caso_marcos, valor=Decimal("700"), modalidade=_MENSAL, vencimento=_INICIO)
            self.assertEqual(nova.vigente_desde, virada)
            self.assertEqual(self.caso_marcos.condicao_vigente(hoje).valor, Decimal("200"))
            self.assertEqual(self.caso_marcos.condicao_vigente(virada - timedelta(days=1)).valor, Decimal("200"))
            self.assertEqual(self.caso_marcos.condicao_vigente(virada).valor, Decimal("700"))

    def test_a_condicao_anterior_nao_e_alterada(self):
        with contexto.como(self.ana.pk):
            anterior = self.caso_marcos.condicao_vigente()
            trocar_condicao(self.caso_marcos, valor=Decimal("700"), modalidade=_MENSAL, vencimento=_INICIO)
            anterior.refresh_from_db()
        self.assertEqual(anterior.valor, Decimal("200"))
        self.assertEqual(anterior.modalidade, CondicaoCobranca.Modalidade.POR_SESSAO)

    def test_quem_nunca_teve_valor_combinado_comeca_hoje(self):
        with contexto.como(self.ana.pk):
            nova = trocar_condicao(self.caso_sem_valor, valor=Decimal("150"),
                                   modalidade=CondicaoCobranca.Modalidade.POR_SESSAO)
        self.assertEqual(nova.vigente_desde, date.today())

    def test_trocar_duas_vezes_no_mesmo_mes_substitui_a_agendada(self):
        with contexto.como(self.ana.pk):
            trocar_condicao(self.caso_marcos, valor=Decimal("700"), modalidade=_MENSAL, vencimento=_INICIO)
            trocar_condicao(self.caso_marcos, valor=Decimal("650"), modalidade=_MENSAL, vencimento=_INICIO)
            self.assertEqual(self.caso_marcos.condicoes.count(), 2)
            self.assertEqual(self.caso_marcos.proxima_condicao().valor, Decimal("650"))


class TrocaPelaTela(TransactionTestCase):
    """`TransactionTestCase` pelo mesmo motivo das demais telas: o middleware usa `SET LOCAL ROLE`."""

    def setUp(self):
        self.ana = criar_psicologo("ana.telatroca@exemplo.com", "11111111111", "727272")
        self.bruno = criar_psicologo("bruno.telatroca@exemplo.com", "22222222222", "737373")
        with contexto.como(self.ana.pk):
            self.marcos = Paciente(nome="Marcos Tela")
            cadastrar_paciente(self.marcos, valor=Decimal("200"))
        with contexto.como(self.bruno.pk):
            self.carla = Paciente(nome="Carla Tela")
            cadastrar_paciente(self.carla, valor=Decimal("250"))

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def test_a_tela_avisa_a_data_da_virada_antes_de_gravar(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("pacientes:cobranca", args=[self.marcos.pk]))
        self.assertContains(resposta, "não vale na hora")
        self.assertContains(resposta, primeiro_dia_do_mes_seguinte().strftime("%d/%m/%Y"))

    def test_salvar_agenda_a_troca_e_mantem_a_atual(self):
        self.entrar(self.ana)
        self.client.post(reverse("pacientes:cobranca", args=[self.marcos.pk]), {
            "modalidade": "MENSAL", "valor": "700", "vencimento": "INICIO"})
        with contexto.como(self.ana.pk):
            caso = caso_individual_de(self.marcos)
            self.assertEqual(caso.condicao_vigente().valor, Decimal("200"))
            self.assertEqual(caso.proxima_condicao().valor, Decimal("700"))

    def test_valor_e_obrigatorio_nesta_tela(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("pacientes:cobranca", args=[self.marcos.pk]),
                                    {"modalidade": "POR_SESSAO", "valor": ""})
        self.assertEqual(resposta.status_code, 200)
        with contexto.como(self.ana.pk):
            self.assertIsNone(caso_individual_de(self.marcos).proxima_condicao())

    def test_nao_troca_a_cobranca_de_paciente_alheio(self):
        self.entrar(self.ana)
        rota = reverse("pacientes:cobranca", args=[self.carla.pk])
        self.assertEqual(self.client.get(rota).status_code, 404)
        self.assertEqual(self.client.post(rota, {"modalidade": "MENSAL", "valor": "1",
                                                 "vencimento": "INICIO"}).status_code, 404)

    def test_exige_login(self):
        resposta = self.client.get(reverse("pacientes:cobranca", args=[self.marcos.pk]))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("contas:entrar"), resposta["Location"])
