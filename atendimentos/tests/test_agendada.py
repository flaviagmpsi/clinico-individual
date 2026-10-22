"""A sessão **agendada** — marcada à mão, ainda vai acontecer (ADR-139).

O caso do usuário: uma consulta avulsa que ainda não aconteceu precisa entrar na agenda, para ela ficar fiel ao
que o psicólogo marcou. Antes, os únicos estados eram "o que aconteceu", e marcar presente/falta no futuro era
(corretamente) barrado — então não havia como pôr uma avulsa futura na agenda.

- Agendada no futuro é aceita, não cobra e não conta presença.
- Ocupa o horário (bloqueia outra sessão no mesmo horário).
- Passado o horário sem atualização, vira pendência ("atualize o que aconteceu").
- Quando acontece, edita-se para presente/falta/cancelada.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from atendimentos import servicos
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto
from indicadores.estatisticas import presenca_do_paciente
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente

E = Consulta.Estado


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = Psicologo.objects.create_user(
            email="ana.agendada@exemplo.com", password="senha-de-teste-123", nome_completo="Ana",
            crp_regiao="04", crp_numero="717272")
        with contexto.como(cls.ana.pk):
            cls.caso = cadastrar_paciente(Paciente(nome="Paciente Avulso"))

    def futuro(self, dias=3, hora=15):
        return timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=dias), time(hora)))

    def passado(self, dias=2, hora=15):
        return timezone.make_aware(datetime.combine(timezone.localdate() - timedelta(days=dias), time(hora)))


class Cadastro(Base):
    def test_agendar_uma_avulsa_futura_e_aceito_e_nao_cobra(self):
        with contexto.como(self.ana.pk):
            c = servicos.cadastrar_avulsa(self.caso, estado=E.AGENDADA, inicio=self.futuro())
        self.assertEqual(c.estado, E.AGENDADA)
        self.assertFalse(c.cobrada)
        self.assertIsNone(c.valor)

    def test_presente_no_futuro_continua_barrado(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.cadastrar_avulsa(self.caso, estado=E.REALIZADA, inicio=self.futuro())

    def test_agendada_ocupa_o_horario(self):
        with contexto.como(self.ana.pk):
            quando = self.futuro()
            servicos.cadastrar_avulsa(self.caso, estado=E.AGENDADA, inicio=quando)
            with self.assertRaises(ValidationError):
                servicos.cadastrar_avulsa(self.caso, estado=E.AGENDADA, inicio=quando)

    def test_agendada_nao_conta_presenca(self):
        with contexto.como(self.ana.pk):
            servicos.cadastrar_avulsa(self.caso, estado=E.AGENDADA, inicio=self.futuro())
            p = presenca_do_paciente(self.caso.pacientes.first())
        self.assertEqual((p.presentes, p.faltas, p.esperadas, p.total), (0, 0, 0, 0))


class Vencida(Base):
    def test_agendada_que_passou_vira_pendencia(self):
        with contexto.como(self.ana.pk):
            servicos.cadastrar_avulsa(self.caso, estado=E.AGENDADA, inicio=self.passado())
            vencidas = servicos.agendadas_vencidas()
        self.assertEqual(len(vencidas), 1)
        self.assertEqual(vencidas[0].caso_id, self.caso.pk)

    def test_agendada_futura_nao_e_pendencia(self):
        with contexto.como(self.ana.pk):
            servicos.cadastrar_avulsa(self.caso, estado=E.AGENDADA, inicio=self.futuro())
            self.assertEqual(servicos.agendadas_vencidas(), [])

    def test_atualizar_para_presente_tira_da_pendencia(self):
        with contexto.como(self.ana.pk):
            c = servicos.cadastrar_avulsa(self.caso, estado=E.AGENDADA, inicio=self.passado())
            servicos.alterar_situacao(c, E.REALIZADA)
            self.assertEqual(servicos.agendadas_vencidas(), [])
        self.assertEqual(Consulta.objetos_todos.get(pk=c.pk).estado, E.REALIZADA)
