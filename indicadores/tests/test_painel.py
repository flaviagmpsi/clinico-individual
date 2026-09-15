"""O painel (ADR-061): sessões, receita e situação de cada atendimento no mês.

Calculado com `AGORA` fixo em 20/09/2026, 12h. Setembro de 2026, conferido: as terças são 1, 8, 15, 22 e 29.
Consultas só se cadastram no passado, então as datas usadas são anteriores ao dia em que o teste roda.

O Marcos exercita os três motivos de atenção de uma vez: falta cobrada de 08/09 sem pagamento, a sessão de 15/09
sem cadastro e 19 dias desde a última sessão realizada (01/09), numa frequência semanal.
"""

from datetime import date, datetime, time
from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Recorrencia
from atendimentos import servicos as agenda
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto
from financeiro import servicos as financeiro
from financeiro.models import Pagamento
from indicadores.servicos import montar_painel
from pacientes.models import CondicaoCobranca, Paciente
from pacientes.servicos import cadastrar_paciente

SENHA = "senha-de-teste-123"
AGORA = timezone.make_aware(datetime(2026, 9, 20, 12))
SEMANAL = Recorrencia.Frequencia.SEMANAL
QUINZENAL = Recorrencia.Frequencia.QUINZENAL
REALIZADA = Consulta.Estado.REALIZADA
FALTA_COBRADA = Consulta.Estado.FALTA_COBRADA
PIX = Pagamento.Forma.PIX


def setembro(dia):
    return date(2026, 9, dia)


def momento(dia, hora=10):
    return timezone.make_aware(datetime.combine(dia, time(hora)))


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


def marcos_com_tres_motivos(nome="Marcos"):
    caso = cadastrar_paciente(Paciente(nome=nome), valor=Decimal("200"), vigente_desde=date(2026, 1, 1))
    regra = Recorrencia.objects.create(caso=caso, frequencia=SEMANAL, dia_semana=1, hora=time(14), duracao=50,
                                       inicio=setembro(1))
    primeira = agenda.cadastrar_prevista(regra, setembro(1), estado=REALIZADA)
    agenda.cadastrar_prevista(regra, setembro(8), estado=FALTA_COBRADA)
    financeiro.registrar_pagamento_sessao(primeira, data=setembro(1), forma=PIX)
    return caso


class BasePainel(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.painel@exemplo.com", "11111111111", "575757")
        cls.bruno = criar_psicologo("bruno.painel@exemplo.com", "22222222222", "585858")
        with contexto.como(cls.ana.pk):
            cls.caso_marcos = marcos_com_tres_motivos()
            cls.caso_juliana = cadastrar_paciente(
                Paciente(nome="Juliana"), valor=Decimal("700"), modalidade=CondicaoCobranca.Modalidade.MENSAL,
                dia_vencimento=10, vigente_desde=setembro(1))
        with contexto.como(cls.bruno.pk):
            cls.caso_carla = cadastrar_paciente(Paciente(nome="Carla"), valor=Decimal("250"),
                                                vigente_desde=date(2026, 1, 1))
            agenda.cadastrar_avulsa(cls.caso_carla, estado=REALIZADA, inicio=momento(setembro(2)))

    def painel(self):
        with contexto.como(self.ana.pk):
            return montar_painel(AGORA)

    def linha(self, painel, caso):
        return next(linha for linha in painel.linhas if linha.caso.pk == caso.pk)


class ResumoDoMes(BasePainel):
    def test_sessoes_feitas_e_as_que_faltam(self):
        """Feita: 01/09. Faltam: 22 e 29/09. A de 15/09 é pendente de cadastro, não previsão."""
        resumo = self.painel().resumo
        self.assertEqual((resumo.sessoes_feitas, resumo.sessoes_faltam), (1, 2))

    def test_recebido_e_a_receber(self):
        """Recebido: a sessão de 01/09. A receber: falta cobrada (200) + mensalidade (700) + duas previstas (400)."""
        resumo = self.painel().resumo
        self.assertEqual((resumo.recebido, resumo.a_receber), (Decimal("200"), Decimal("1300")))

    def test_pacientes_ativos_e_quantos_precisam_de_atencao(self):
        resumo = self.painel().resumo
        self.assertEqual((resumo.pacientes_ativos, resumo.precisam_de_atencao), (2, 2))


class Situacao(BasePainel):
    def test_os_tres_motivos_de_atencao(self):
        linha = self.linha(self.painel(), self.caso_marcos)
        self.assertEqual(linha.motivos, ["pagamento vencido", "sessão pendente de cadastro", "19 dias sem sessão"])
        self.assertEqual((linha.sessoes_no_mes, linha.dias_sem_sessao), (1, 19))
        self.assertEqual((linha.pago, linha.devido, linha.situacao_financeira),
                         (Decimal("200"), Decimal("400"), "pendente"))

    def test_mensalidade_paga_deixa_regular(self):
        with contexto.como(self.ana.pk):
            financeiro.registrar_pagamento_mensalidade(
                self.caso_juliana, ano=2026, mes=9, valor=Decimal("700"), data=setembro(5), forma=PIX)
        linha = self.linha(self.painel(), self.caso_juliana)
        self.assertFalse(linha.atencao)
        self.assertEqual((linha.situacao_financeira, linha.formas, linha.dias_sem_sessao), ("pago", ["Pix"], None))

    def test_quinzenal_tolera_21_dias_e_semanal_nao(self):
        """Última sessão realizada em 30/08: 21 dias até 20/09. As frequências só começam a prever em 25/09."""
        with contexto.como(self.ana.pk):
            casos = {}
            for frequencia, hora in [(QUINZENAL, 9), (SEMANAL, 11)]:
                caso = cadastrar_paciente(Paciente(nome=frequencia))
                agenda.cadastrar_avulsa(caso, estado=REALIZADA, inicio=momento(date(2026, 8, 30), hora))
                Recorrencia.objects.create(caso=caso, frequencia=frequencia, dia_semana=4, hora=time(hora),
                                           duracao=50, inicio=setembro(19))
                casos[frequencia] = caso
        painel = self.painel()
        self.assertEqual(self.linha(painel, casos[QUINZENAL]).motivos, [])
        self.assertEqual(self.linha(painel, casos[SEMANAL]).motivos, ["21 dias sem sessão"])

    def test_atendimento_encerrado_sai_do_painel(self):
        with contexto.como(self.ana.pk):
            agenda.registrar_desfecho(self.caso_juliana, tipo="DESISTENCIA", data=setembro(14))
        painel = self.painel()
        self.assertNotIn(self.caso_juliana.pk, [linha.caso.pk for linha in painel.linhas])
        self.assertEqual(painel.resumo.pacientes_ativos, 1)

    def test_atendimento_de_outro_psicologo_nao_aparece(self):
        self.assertNotIn(self.caso_carla.pk, [linha.caso.pk for linha in self.painel().linhas])


class PainelPelaTela(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.telapainel@exemplo.com", "33333333333", "595959")
        self.bruno = criar_psicologo("bruno.telapainel@exemplo.com", "44444444444", "606060")
        with contexto.como(self.ana.pk):
            marcos_com_tres_motivos("Marcos Painel")
        with contexto.como(self.bruno.pk):
            cadastrar_paciente(Paciente(nome="Carla Painel"))

    def test_exige_login(self):
        resposta = self.client.get(reverse("painel"))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("contas:entrar"), resposta["Location"])

    def test_mostra_os_proprios_atendimentos_e_a_situacao(self):
        self.assertTrue(self.client.login(username=self.ana.email, password=SENHA))
        resposta = self.client.get(reverse("painel"))
        for texto in ["Atendimentos em curso", "Marcos Painel", "Precisa de atenção", "Sessões pendentes de cadastro",
                      "Pagamentos pendentes"]:
            self.assertContains(resposta, texto)
        self.assertNotContains(resposta, "Carla Painel")
