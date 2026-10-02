"""Três situações, não duas: pendente, vencida e quitada (rodada 80).

Decisão do usuário, nas palavras dele: *"pagamentos mensais, logo no início do mês já aparece como pendente, pois
a pessoa precisa realizar o pagamento daquele mês até a data de vencimento"*. Antes disto, uma cobrança só existia
para o sistema a partir do vencimento — e o psicólogo cadastrava um mensalista no dia 1º, olhava o painel e não
via nada a receber. Nada estava errado no cálculo; faltava a situação do meio.

O par importa nos dois sentidos: a mensalidade do mês corrente aparece **antes** de vencer e **não** como alerta;
a sessão, que vence no dia em que acontece (ADR-063), nunca passa por "pendente".

Setembro de 2026, conferido: 1º/09 é terça.
"""

from datetime import date, datetime, time
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from atendimentos import servicos as agenda
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto
from financeiro import servicos
from financeiro.models import Pagamento
from pacientes.models import CondicaoCobranca, Paciente
from pacientes.servicos import cadastrar_paciente

MENSAL = CondicaoCobranca.Modalidade.MENSAL


def setembro(dia):
    return date(2026, 9, dia)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = Psicologo.objects.create_user(
            email="ana.areceber@exemplo.com", password="senha-de-teste-123", nome_completo="Ana",
            crp_regiao="04", crp_numero="717171")
        with contexto.como(cls.ana.pk):
            # Mensalista de R$ 500 vencendo todo dia 10, desde agosto: setembro vence em 10/09.
            cls.caso = cadastrar_paciente(Paciente(nome="Mensalista"), valor=Decimal("500"), modalidade=MENSAL,
                                          dia_vencimento=10, vigente_desde=date(2026, 8, 1))

    def cobranca_de_setembro(self):
        with contexto.como(self.ana.pk):
            return next(c for c in servicos.cobrancas_do_mes(2026, 9, caso=self.caso)
                        if c.tipo == servicos.MENSALIDADE)


class QuandoACobrancaExiste(Base):
    def test_a_mensalidade_existe_desde_o_dia_primeiro(self):
        """O ponto da rodada 80: dia 1º ela já conta, mesmo vencendo no dia 10."""
        cobranca = self.cobranca_de_setembro()
        self.assertEqual(cobranca.desde, setembro(1))
        self.assertTrue(cobranca.em_aberto(setembro(1)))

    def test_no_mes_anterior_ela_nao_existe(self):
        """Não se cobra em agosto o mês que não começou — o contrário de "aparece sempre"."""
        cobranca = self.cobranca_de_setembro()
        self.assertFalse(cobranca.em_aberto(date(2026, 8, 31)))

    def test_a_sessao_existe_no_dia_dela(self):
        with contexto.como(self.ana.pk):
            caso = cadastrar_paciente(Paciente(nome="Por sessão"), valor=Decimal("200"),
                                      vigente_desde=date(2026, 1, 1))
            consulta = agenda.cadastrar_avulsa(
                caso, estado=Consulta.Estado.REALIZADA,
                inicio=timezone.make_aware(datetime.combine(setembro(3), time(10))))
            cobranca = servicos.sessao(consulta)
        self.assertEqual(cobranca.desde, setembro(3))


class PendenteEVencida(Base):
    def test_antes_do_vencimento_esta_pendente_e_nao_vencida(self):
        cobranca = self.cobranca_de_setembro()
        for dia in (1, 5, 9):
            with self.subTest(dia=dia):
                self.assertTrue(cobranca.pendente(setembro(dia)))
                self.assertFalse(cobranca.vencida(setembro(dia)))

    def test_no_dia_do_vencimento_ja_esta_vencida(self):
        """A regra N-08 não muda: pendente **a partir do** vencimento, inclusive no próprio dia."""
        cobranca = self.cobranca_de_setembro()
        self.assertTrue(cobranca.vencida(setembro(10)))
        self.assertFalse(cobranca.pendente(setembro(10)))

    def test_paga_antes_do_vencimento_sai_das_duas_listas(self):
        with contexto.como(self.ana.pk):
            servicos.registrar_pagamento_mensalidade(self.caso, ano=2026, mes=9, valor=Decimal("500"),
                                                     data=setembro(4), forma=Pagamento.Forma.PIX)
        cobranca = self.cobranca_de_setembro()
        self.assertFalse(cobranca.pendente(setembro(5)))
        self.assertFalse(cobranca.vencida(setembro(30)))
        self.assertFalse(cobranca.em_aberto(setembro(5)))

    def test_paga_pela_metade_continua_pendente_pelo_resto(self):
        with contexto.como(self.ana.pk):
            servicos.registrar_pagamento_mensalidade(self.caso, ano=2026, mes=9, valor=Decimal("200"),
                                                     data=setembro(4), forma=Pagamento.Forma.PIX)
        cobranca = self.cobranca_de_setembro()
        self.assertTrue(cobranca.pendente(setembro(5)))
        self.assertEqual(cobranca.saldo, Decimal("300"))

    def test_dias_de_atraso_e_para_vencer_nunca_sao_negativos(self):
        """A tela usa os dois para graduar o alerta; negativo apareceria como "-5 dias de atraso"."""
        cobranca = self.cobranca_de_setembro()
        self.assertEqual(cobranca.dias_para_vencer(setembro(1)), 9)
        self.assertEqual(cobranca.dias_para_vencer(setembro(20)), 0)
        self.assertEqual(cobranca.dias_de_atraso(setembro(1)), 0)
        self.assertEqual(cobranca.dias_de_atraso(setembro(20)), 10)


class AsListasDoPainel(Base):
    def test_no_dia_primeiro_esta_pendente_e_nao_vencida(self):
        with contexto.como(self.ana.pk):
            self.assertEqual([c.mes for c in servicos.pagamentos_pendentes(setembro(1), caso=self.caso)],
                             [setembro(1)])
            # Agosto já venceu: é o que fica no alerta no dia 1º de setembro.
            self.assertEqual([c.mes for c in servicos.pagamentos_vencidos(setembro(1), caso=self.caso)],
                             [date(2026, 8, 1)])

    def test_depois_do_vencimento_troca_de_lista(self):
        with contexto.como(self.ana.pk):
            pendentes = servicos.pagamentos_pendentes(setembro(15), caso=self.caso)
            vencidas = servicos.pagamentos_vencidos(setembro(15), caso=self.caso)
        self.assertEqual(pendentes, [])
        self.assertEqual([c.mes for c in vencidas], [date(2026, 8, 1), setembro(1)])

    def test_em_aberto_e_a_soma_exata_das_duas_listas(self):
        """Se um dia as três funções discordarem, é aqui que se vê — e não numa tela."""
        with contexto.como(self.ana.pk):
            abertas = servicos.cobrancas_em_aberto(setembro(5), caso=self.caso)
            pendentes = servicos.pagamentos_pendentes(setembro(5), caso=self.caso)
            vencidas = servicos.pagamentos_vencidos(setembro(5), caso=self.caso)
        self.assertEqual(len(abertas), len(pendentes) + len(vencidas))
        self.assertEqual({c.mes for c in abertas}, {c.mes for c in pendentes} | {c.mes for c in vencidas})

    def test_a_sessao_fica_pendente_pelos_tres_dias_de_tolerancia(self):
        """A ADR-123 abriu a janela que a ADR-063 não tinha: a sessão vence no dia dela, mas o alerta espera.

        Era "sessão nunca fica pendente", e deixou de ser verdade de propósito — registrar a sessão com atraso é
        rotina do psicólogo, e não pode acender alerta de inadimplência sobre o paciente.
        """
        with contexto.como(self.ana.pk):
            caso = cadastrar_paciente(Paciente(nome="Avulso"), valor=Decimal("200"), vigente_desde=date(2026, 1, 1))
            agenda.cadastrar_avulsa(caso, estado=Consulta.Estado.REALIZADA,
                                    inicio=timezone.make_aware(datetime.combine(setembro(3), time(10))))
            # Dentro da tolerância: pendente, sem alerta.
            self.assertEqual(len(servicos.pagamentos_pendentes(setembro(5), caso=caso)), 1)
            self.assertEqual(servicos.pagamentos_vencidos(setembro(5), caso=caso), [])
            # Passada a tolerância: troca de lista.
            self.assertEqual(servicos.pagamentos_pendentes(setembro(6), caso=caso), [])
            self.assertEqual(len(servicos.pagamentos_vencidos(setembro(6), caso=caso)), 1)


class ToleranciaDaSessao(Base):
    """ADR-123: a cobrança de sessão só vira alerta três dias depois do atendimento.

    Ela nasce quando o psicólogo **registra** a sessão, e registrar com atraso é rotina dele — não dívida do
    paciente. Sem a tolerância, a sexta em que ele lança a semana inteira pintava de vermelho a segunda.

    O par importa: a sessão ganha tolerância e a mensalidade **não**, porque a data da mensalidade foi combinada
    com o paciente e é conhecida de véspera.
    """

    def sessao_do_dia_3(self):
        with contexto.como(self.ana.pk):
            caso = cadastrar_paciente(Paciente(nome="Por sessão"), valor=Decimal("200"),
                                      vigente_desde=date(2026, 1, 1))
            consulta = agenda.cadastrar_avulsa(
                caso, estado=Consulta.Estado.REALIZADA,
                inicio=timezone.make_aware(datetime.combine(setembro(3), time(10))))
            return servicos.sessao(consulta)

    def test_vence_no_dia_do_atendimento(self):
        """O vencimento não muda: é o que foi combinado, e é ele que a tela mostra."""
        self.assertEqual(self.sessao_do_dia_3().vencimento, setembro(3))

    def test_o_alerta_so_acende_tres_dias_depois(self):
        cobranca = self.sessao_do_dia_3()
        self.assertEqual(cobranca.alerta_em, setembro(6))
        for dia in (3, 4, 5):
            with self.subTest(dia=dia):
                self.assertFalse(cobranca.vencida(setembro(dia)))
                self.assertTrue(cobranca.pendente(setembro(dia)))
        self.assertTrue(cobranca.vencida(setembro(6)))
        self.assertFalse(cobranca.pendente(setembro(6)))

    def test_os_dias_de_atraso_contam_do_vencimento_e_nao_do_alerta(self):
        """O número que a tela mostra é o atraso de verdade; a tolerância só decide quando mostrá-lo."""
        self.assertEqual(self.sessao_do_dia_3().dias_de_atraso(setembro(10)), 7)

    def test_a_mensalidade_nao_tem_tolerancia(self):
        cobranca = self.cobranca_de_setembro()
        self.assertEqual(cobranca.alerta_em, cobranca.vencimento)
        self.assertTrue(cobranca.vencida(setembro(10)))
