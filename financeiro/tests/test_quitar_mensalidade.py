"""Dar um mês de mensalidade como quitado à mão (ADR-133).

O caso do usuário: paciente começou no meio do mês e, por combinação, paga só metade neste primeiro mês. O
psicólogo registra R$ 150 de uma mensalidade de R$ 300; o sistema mostraria R$ 150 pendentes — dívida que não
existe. Dar o mês como quitado tira o saldo da pendência e deixa o que foi pago intacto no faturamento.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase

from contas.models import Psicologo
from core import contexto, db
from core.calendario import TipoDia
from financeiro import servicos
from financeiro.models import MensalidadeQuitada, Pagamento
from pacientes.models import CondicaoCobranca, Paciente
from pacientes.servicos import cadastrar_paciente

MENSAL = CondicaoCobranca.Modalidade.MENSAL
PIX = Pagamento.Forma.PIX


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = Psicologo.objects.create_user(
            email="ana.quitar@exemplo.com", password="senha-de-teste-123", nome_completo="Ana",
            crp_regiao="04", crp_numero="818282")
        with contexto.como(cls.ana.pk):
            cls.caso = cadastrar_paciente(
                Paciente(nome="Mensalista"), valor=Decimal("300"), modalidade=MENSAL,
                dia_vencimento=10, vigente_desde=date(2026, 9, 1))
            # paga só metade do primeiro mês
            servicos.registrar_pagamento_mensalidade(cls.caso, ano=2026, mes=9, valor=Decimal("150"),
                                                     data=date(2026, 9, 5), forma=PIX)

    def mensalidade(self):
        with contexto.como(self.ana.pk):
            return servicos.mensalidade(self.caso, 2026, 9)


class DarComoQuitado(Base):
    def test_antes_de_quitar_o_saldo_e_pendencia(self):
        c = self.mensalidade()
        self.assertEqual(c.saldo, Decimal("150"))
        self.assertFalse(c.quitada)
        self.assertTrue(c.vencida(date(2026, 9, 30)))

    def test_depois_de_quitar_o_saldo_some_e_o_pago_fica(self):
        with contexto.como(self.ana.pk):
            servicos.quitar_mensalidade_a_mao(self.caso, 2026, 9)
            c = servicos.mensalidade(self.caso, 2026, 9)
        self.assertEqual(c.saldo, Decimal("0"))
        self.assertEqual(c.pago, Decimal("150"))   # o faturamento não muda
        self.assertTrue(c.quitada)
        self.assertTrue(c.quitada_manualmente)
        self.assertFalse(c.vencida(date(2026, 9, 30)))
        self.assertFalse(c.em_aberto(date(2026, 9, 30)))

    def test_sai_da_lista_de_vencidos_e_nao_entra_em_pendentes(self):
        with contexto.como(self.ana.pk):
            servicos.quitar_mensalidade_a_mao(self.caso, 2026, 9)
            self.assertEqual(servicos.pagamentos_vencidos(date(2026, 9, 30), caso=self.caso), [])
            self.assertEqual(servicos.pagamentos_pendentes(date(2026, 9, 30), caso=self.caso), [])

    def test_reabrir_traz_o_saldo_de_volta(self):
        with contexto.como(self.ana.pk):
            servicos.quitar_mensalidade_a_mao(self.caso, 2026, 9)
            servicos.reabrir_mensalidade(self.caso, 2026, 9)
            c = servicos.mensalidade(self.caso, 2026, 9)
        self.assertEqual(c.saldo, Decimal("150"))
        self.assertFalse(c.quitada)

    def test_quitar_duas_vezes_nao_duplica(self):
        with contexto.como(self.ana.pk):
            servicos.quitar_mensalidade_a_mao(self.caso, 2026, 9)
            servicos.quitar_mensalidade_a_mao(self.caso, 2026, 9)
            self.assertEqual(MensalidadeQuitada.objects.filter(caso=self.caso).count(), 1)

    def test_nao_quita_mes_sem_mensalidade(self):
        """Paciente por sessão, ou mês sem condição mensal: não há o que quitar."""
        with contexto.como(self.ana.pk):
            avulso = cadastrar_paciente(Paciente(nome="Por sessão"), valor=Decimal("200"),
                                        vigente_desde=date(2026, 1, 1))
            with self.assertRaises(ValidationError):
                servicos.quitar_mensalidade_a_mao(avulso, 2026, 9)


class Isolamento(TransactionTestCase):
    """ADR-001: a quitação de um psicólogo não vaza para outro, nem por SQL cru."""

    def test_sql_cru_so_devolve_o_proprio_dono(self):
        if connection.vendor != "postgresql":
            self.skipTest("RLS exige PostgreSQL.")
        ana = Psicologo.objects.create_user(email="ana.iso@t.com", password="x", nome_completo="Ana",
                                            crp_regiao="04", crp_numero="838484")
        bruno = Psicologo.objects.create_user(email="bruno.iso@t.com", password="x", nome_completo="Bruno",
                                              crp_regiao="04", crp_numero="848585")
        for psi in (ana, bruno):
            with contexto.como(psi.pk):
                caso = cadastrar_paciente(Paciente(nome=f"Pac {psi.pk}"), valor=Decimal("300"), modalidade=MENSAL,
                                          dia_vencimento=10, vigente_desde=date(2026, 9, 1))
                servicos.quitar_mensalidade_a_mao(caso, 2026, 9)

        def quantas(psicologo_id):
            with transaction.atomic():
                db.assumir_papel_da_aplicacao()
                db.aplicar_escopo(psicologo_id, administradora=False)
                with connection.cursor() as c:
                    c.execute("SELECT count(*) FROM financeiro_mensalidadequitada")
                    return c.fetchone()[0]

        self.assertEqual(quantas(ana.pk), 1)
        self.assertEqual(quantas(bruno.pk), 1)
