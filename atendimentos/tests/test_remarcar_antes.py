"""Remarcar e cancelar antes da sessão acontecer (ADR-131).

Decisão do usuário: "quero que seja possivel remarcar um atendimento antes dele acontecer, porque até entao só
pode remarcar depois que passa do horario do atendimento, só que na maioria das vezes a remarcação é feita antes".

A regra fina: **presença e falta** continuam exigindo que a sessão tenha acontecido — não há como saber antes.
**Remarcação e cancelamento** são decisões da véspera e passam a ser aceitas para uma sessão futura.
"""

from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from atendimentos import servicos
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto
from agenda.models import Recorrencia
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente

E = Consulta.Estado


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = Psicologo.objects.create_user(
            email="ana.remarcar@exemplo.com", password="senha-de-teste-123", nome_completo="Ana",
            crp_regiao="04", crp_numero="737474")
        cls.hoje = timezone.localdate()
        with contexto.como(cls.ana.pk):
            cls.caso = cadastrar_paciente(Paciente(nome="Paciente"))
            # Frequência semanal começando hoje; a próxima ocorrência cai daqui a 7 dias — no futuro.
            servicos.definir_frequencia(cls.caso, frequencia=Recorrencia.Frequencia.SEMANAL,
                                        dia_semana=cls.hoje.weekday(), hora=time(10), a_partir_de=cls.hoje)
            cls.regra = cls.caso.regra_aberta()

    def futura(self):
        return self.regra.ocorrencias(self.hoje + timedelta(days=1), self.hoje + timedelta(days=20))[0]

    def destino(self, dia):
        return timezone.make_aware(datetime.combine(dia + timedelta(days=2), time(15)))


class PresencaEFaltaSoDepois(Base):
    def test_marcar_presente_numa_sessao_futura_e_recusado(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.cadastrar_prevista(self.regra, self.futura(), estado=E.REALIZADA)

    def test_marcar_faltou_numa_sessao_futura_e_recusado(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.cadastrar_prevista(self.regra, self.futura(), estado=E.FALTOU)


class RemarcarECancelarAntes(Base):
    def test_remarcar_uma_sessao_futura_e_aceito(self):
        dia = self.futura()
        with contexto.como(self.ana.pk):
            consulta = servicos.cadastrar_prevista(
                self.regra, dia, estado=E.REMARCADA, remarcada_para=self.destino(dia))
        self.assertEqual(consulta.estado, E.REMARCADA)
        self.assertIsNotNone(consulta.remarcada_para)

    def test_a_sessao_remarcada_aparece_na_agenda_do_destino(self):
        dia = self.futura()
        with contexto.como(self.ana.pk):
            servicos.cadastrar_prevista(self.regra, dia, estado=E.REMARCADA, remarcada_para=self.destino(dia))
            rem = servicos.sessoes_remarcadas(dia + timedelta(days=1), dia + timedelta(days=5))
        self.assertEqual(len(rem), 1)

    def test_cancelar_antes_tambem_e_aceito(self):
        with contexto.como(self.ana.pk):
            consulta = servicos.cadastrar_prevista(
                self.regra, self.futura(), estado=E.CANCELADA_CLIENTE, cobrada=False)
        self.assertEqual(consulta.estado, E.CANCELADA_CLIENTE)

    def test_presenca_numa_sessao_passada_continua_funcionando(self):
        """A regra nova não pode ter quebrado o caso comum: registrar o que já aconteceu."""
        with contexto.como(self.ana.pk):
            ontem = timezone.make_aware(datetime.combine(self.hoje - timedelta(days=1), time(9)))
            consulta = servicos.cadastrar_avulsa(self.caso, estado=E.REALIZADA, inicio=ontem)
        self.assertEqual(consulta.estado, E.REALIZADA)
