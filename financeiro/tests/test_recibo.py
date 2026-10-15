"""O controle de recibo a emitir (ADR-132).

Decisão do usuário: ao registrar um pagamento, pergunta-se se o recibo foi emitido. Marcado "não", vira um
lembrete; a pessoa emite por fora, volta pelo lembrete, marca que emitiu, e a pendência some.

Emitir recibo (Receita Saúde) é obrigação legal do psicólogo — por isso vale a pena o sistema não deixar esquecer.
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

PIX = Pagamento.Forma.PIX


def setembro(dia):
    return date(2026, 9, dia)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = Psicologo.objects.create_user(
            email="ana.recibo@exemplo.com", password="senha-de-teste-123", nome_completo="Ana",
            crp_regiao="04", crp_numero="717272")
        with contexto.como(cls.ana.pk):
            cls.caso = cadastrar_paciente(
                Paciente(nome="Mensalista"), valor=Decimal("300"),
                modalidade=CondicaoCobranca.Modalidade.MENSAL, dia_vencimento=10, vigente_desde=setembro(1))

    def pagar(self, *, recibo_emitido):
        with contexto.como(self.ana.pk):
            return servicos.registrar_pagamento_mensalidade(
                self.caso, ano=2026, mes=9, valor=Decimal("300"), data=setembro(2), forma=PIX,
                recibo_emitido=recibo_emitido)


class ReciboComoPendencia(Base):
    def test_pago_com_recibo_emitido_nao_vira_pendencia(self):
        self.pagar(recibo_emitido=True)
        with contexto.como(self.ana.pk):
            self.assertEqual(servicos.recibos_pendentes(), [])

    def test_pago_sem_recibo_vira_pendencia(self):
        self.pagar(recibo_emitido=False)
        with contexto.como(self.ana.pk):
            pendentes = servicos.recibos_pendentes()
        self.assertEqual(len(pendentes), 1)
        self.assertEqual(pendentes[0].caso, self.caso)
        self.assertIn("Mensalidade de setembro", pendentes[0].descricao)

    def test_os_pagamentos_que_ja_existiam_nao_viram_pendencia(self):
        """`default=True` no campo: ligar o recurso não pode encher o painel de recibos retroativos."""
        with contexto.como(self.ana.pk):
            Pagamento.objects.create(caso=self.caso, mes_referencia=setembro(1), valor=Decimal("300"),
                                     data=setembro(2), forma=PIX)  # sem passar recibo_emitido
            self.assertEqual(servicos.recibos_pendentes(), [])


class EmitirDepois(Base):
    def test_marcar_emitido_tira_da_pendencia(self):
        self.pagar(recibo_emitido=False)
        with contexto.como(self.ana.pk):
            pagamento = Pagamento.objects.get(caso=self.caso)
            servicos.editar_pagamento(pagamento, valor=pagamento.valor, data=pagamento.data,
                                      forma=pagamento.forma, recibo_emitido=True)
            self.assertEqual(servicos.recibos_pendentes(), [])

    def test_editar_corrige_valor_e_mantem_o_recibo(self):
        self.pagar(recibo_emitido=False)
        with contexto.como(self.ana.pk):
            pagamento = Pagamento.objects.get(caso=self.caso)
            servicos.editar_pagamento(pagamento, valor=Decimal("250"), data=pagamento.data,
                                      forma=pagamento.forma, recibo_emitido=False)
            pagamento.refresh_from_db()
            self.assertEqual(pagamento.valor, Decimal("250"))
            self.assertEqual(len(servicos.recibos_pendentes()), 1)  # ainda a emitir


class NoPainel(Base):
    def test_o_recibo_pendente_entra_na_contagem_de_pendencias(self):
        from indicadores.servicos import montar_painel
        self.pagar(recibo_emitido=False)
        with contexto.como(self.ana.pk):
            painel = montar_painel()
        self.assertEqual(len(painel.pendencias.recibos), 1)
        self.assertGreaterEqual(painel.pendencias.total, 1)


class PorSessao(Base):
    def test_recibo_de_pagamento_de_sessao(self):
        with contexto.como(self.ana.pk):
            caso = cadastrar_paciente(Paciente(nome="Por sessão"), valor=Decimal("200"),
                                      vigente_desde=date(2026, 1, 1))
            consulta = agenda.cadastrar_avulsa(
                caso, estado=Consulta.Estado.REALIZADA,
                inicio=timezone.make_aware(datetime.combine(setembro(3), time(10))))
            servicos.registrar_pagamento_sessao(consulta, data=setembro(3), forma=PIX, recibo_emitido=False)
            pendentes = servicos.recibos_pendentes()
        self.assertEqual(len(pendentes), 1)
        self.assertIn("Sessão de 03/09", pendentes[0].descricao)
