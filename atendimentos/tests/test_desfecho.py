"""O fim do atendimento: o que o desfecho faz na agenda, o momento calculado e a retomada (ADR-049, ADR-055).

Cada classe guarda uma parte da decisão:

- `EfeitosNaAgenda` — a frequência termina, o futuro sai, o passado fica, o encerrado não aceita sessão.
- `RegrasDoRegistro` — data, desfecho único, iniciativa que decorre do tipo.
- `MomentoERetomada` — sessões contadas desde a última retomada; retomar reabre o mesmo atendimento.
- `ListaDeAtivos` — encerrado sai dos ativos; quem segue no casal continua.
- `Exclusao` — desfecho é atendimento (ADR-048); casal com sessões agendadas sai sem erro.
"""

from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from agenda.models import Recorrencia
from atendimentos import servicos
from atendimentos.models import Consulta, Desfecho
from contas.models import Psicologo
from core import contexto
from pacientes.models import Caso, Paciente
from pacientes.servicos import (
    cadastrar_paciente,
    criar_caso_coletivo,
    excluir_caso_coletivo,
    excluir_paciente,
    pacientes_ativos,
    pacientes_encerrados,
)

SEMANAL = Recorrencia.Frequencia.SEMANAL
TERCA = Recorrencia.DiaSemana.TERCA
ALTA = Desfecho.Tipo.ALTA
DESISTENCIA = Desfecho.Tipo.DESISTENCIA
INTERRUPCAO = Desfecho.Tipo.INTERRUPCAO
PACIENTE = Desfecho.Iniciativa.PACIENTE
PSICOLOGO = Desfecho.Iniciativa.PSICOLOGO


def momento(dia, hora, minuto=0):
    return timezone.make_aware(datetime.combine(dia, time(hora, minuto)))


def proxima(dia_semana):
    amanha = timezone.localdate() + timedelta(days=1)
    return amanha + timedelta(days=(dia_semana - amanha.weekday()) % 7)


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password="senha-de-teste-123", nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


class BaseDesfecho(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.desfecho@exemplo.com", "11111111111", "818181")
        cls.bruno = criar_psicologo("bruno.desfecho@exemplo.com", "22222222222", "828282")
        with contexto.como(cls.ana.pk):
            cls.maria = Paciente(nome="Maria Desfecho")
            cls.caso_maria = cadastrar_paciente(cls.maria)
            cls.joao = Paciente(nome="João Desfecho")
            cls.caso_joao = cadastrar_paciente(cls.joao)
        with contexto.como(cls.bruno.pk):
            cls.caso_carla = cadastrar_paciente(Paciente(nome="Carla Desfecho"))

    def setUp(self):
        self.terca = proxima(TERCA)
        self.hoje = timezone.localdate()

    def semanal(self, caso, hora=14):
        return servicos.definir_frequencia(
            caso, frequencia=SEMANAL, dia_semana=TERCA, hora=time(hora), a_partir_de=self.terca)

    def passada(self, caso, dias, estado=None, hora=9):
        consulta = servicos.marcar_avulsa(caso, inicio=momento(self.hoje - timedelta(days=dias), hora))
        if estado:
            servicos.registrar(consulta, estado)
        return consulta

    def encerrar(self, caso, tipo=DESISTENCIA, **kwargs):
        return servicos.registrar_desfecho(caso, tipo=tipo, **kwargs)


class EfeitosNaAgenda(BaseDesfecho):
    def test_o_futuro_sai_inteiro_inclusive_remarcada_e_avulsa(self):
        with contexto.como(self.ana.pk):
            self.semanal(self.caso_maria)
            segunda_sessao = Consulta.objects.get(caso=self.caso_maria, data_prevista=self.terca + timedelta(weeks=1))
            servicos.remarcar(segunda_sessao, inicio=momento(self.terca + timedelta(days=8), 14))
            servicos.marcar_avulsa(self.caso_maria, inicio=momento(self.terca, 9))

            self.encerrar(self.caso_maria)

            self.assertFalse(Consulta.objects.filter(caso=self.caso_maria).exists())
            self.assertIsNone(self.caso_maria.regra_aberta())

    def test_regra_que_ja_valia_termina_hoje_e_nao_gera_mais_nada(self):
        with contexto.como(self.ana.pk):
            amanha = (self.hoje.weekday() + 1) % 7
            servicos.definir_frequencia(
                self.caso_maria, frequencia=SEMANAL, dia_semana=amanha, hora=time(14), a_partir_de=self.hoje)
            self.encerrar(self.caso_maria)
            self.assertEqual(Recorrencia.objects.get(caso=self.caso_maria).fim, self.hoje)
            servicos.gerar_consultas(self.hoje)
            self.assertFalse(Consulta.objects.filter(caso=self.caso_maria).exists())

    def test_o_passado_fica_e_a_pendencia_continua(self):
        """O desfecho não registra nada no lugar do psicólogo (ADR-052)."""
        with contexto.como(self.ana.pk):
            realizada = self.passada(self.caso_maria, 10, Consulta.Estado.REALIZADA)
            sem_registro = self.passada(self.caso_maria, 3)
            self.encerrar(self.caso_maria)
            self.assertTrue(Consulta.objects.filter(pk=realizada.pk).exists())
            self.assertIn(sem_registro, list(servicos.consultas_sem_registro()))

    def test_encerrado_nao_aceita_frequencia_consulta_nem_remarcacao(self):
        with contexto.como(self.ana.pk):
            sem_registro = self.passada(self.caso_maria, 3)
            self.encerrar(self.caso_maria)
            with self.assertRaises(ValidationError):
                self.semanal(self.caso_maria)
            with self.assertRaises(ValidationError):
                servicos.marcar_avulsa(self.caso_maria, inicio=momento(self.terca, 9))
            with self.assertRaises(ValidationError):
                servicos.remarcar(sem_registro, inicio=momento(self.terca, 9))

    def test_desfecho_do_casal_e_do_caso_inteiro_e_os_individuais_seguem(self):
        with contexto.como(self.ana.pk):
            casal = criar_caso_coletivo([self.maria, self.joao])
            self.semanal(casal, hora=19)
            self.encerrar(casal, tipo=ALTA, iniciativa=PSICOLOGO)
            self.assertIsNotNone(casal.desfecho_aberto())
            self.assertIsNone(self.caso_maria.desfecho_aberto())
            self.semanal(self.caso_maria)  # o individual da Maria continua aceitando agenda


class RegrasDoRegistro(BaseDesfecho):
    def test_data_no_futuro_e_recusada(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                self.encerrar(self.caso_maria, data=self.hoje + timedelta(days=1))

    def test_segundo_desfecho_em_aberto_e_recusado(self):
        with contexto.como(self.ana.pk):
            self.encerrar(self.caso_maria)
            with self.assertRaises(ValidationError):
                self.encerrar(self.caso_maria, tipo=ALTA, iniciativa=PACIENTE)

    def test_desistencia_e_interrupcao_ja_dizem_de_quem_partiu(self):
        with contexto.como(self.ana.pk):
            self.assertEqual(self.encerrar(self.caso_maria, tipo=DESISTENCIA).iniciativa, PACIENTE)
            self.assertEqual(self.encerrar(self.caso_joao, tipo=INTERRUPCAO).iniciativa, PSICOLOGO)

    def test_alta_sem_iniciativa_e_recusada_sem_mexer_na_agenda(self):
        with contexto.como(self.ana.pk):
            self.semanal(self.caso_maria)
            antes = Consulta.objects.filter(caso=self.caso_maria).count()
            with self.assertRaises(ValidationError):
                self.encerrar(self.caso_maria, tipo=ALTA)
            self.assertEqual(Consulta.objects.filter(caso=self.caso_maria).count(), antes)

    def test_desistencia_do_psicologo_e_contradicao(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                self.encerrar(self.caso_maria, tipo=DESISTENCIA, iniciativa=PSICOLOGO)

    def test_nao_registra_desfecho_no_caso_de_outro_psicologo(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                self.encerrar(self.caso_carla)


class MomentoERetomada(BaseDesfecho):
    def test_o_momento_e_contado_e_nao_perguntado(self):
        """Falta não é sessão realizada (ADR-027)."""
        with contexto.como(self.ana.pk):
            self.passada(self.caso_maria, 20, Consulta.Estado.REALIZADA)
            self.passada(self.caso_maria, 13, Consulta.Estado.REALIZADA)
            self.passada(self.caso_maria, 6, Consulta.Estado.FALTA)
            self.assertEqual(self.encerrar(self.caso_maria).sessoes_realizadas, 2)

    def test_retomar_reabre_o_mesmo_atendimento_e_a_contagem_recomeca(self):
        with contexto.como(self.ana.pk):
            self.passada(self.caso_maria, 10, Consulta.Estado.REALIZADA)
            self.passada(self.caso_maria, 8, Consulta.Estado.REALIZADA)
            primeiro = self.encerrar(self.caso_maria, data=self.hoje - timedelta(days=5))
            self.assertEqual(primeiro.sessoes_realizadas, 2)

            servicos.retomar(self.caso_maria, hoje=self.hoje - timedelta(days=2))
            self.assertIsNone(self.caso_maria.desfecho_aberto())
            self.passada(self.caso_maria, 1, Consulta.Estado.REALIZADA)
            segundo = self.encerrar(self.caso_maria, tipo=ALTA, iniciativa=PACIENTE)

            self.assertEqual(segundo.sessoes_realizadas, 1)
            self.assertEqual(list(self.caso_maria.desfechos_anteriores()), [Desfecho.objects.get(pk=primeiro.pk)])

    def test_retomado_volta_a_aceitar_frequencia(self):
        with contexto.como(self.ana.pk):
            self.encerrar(self.caso_maria)
            servicos.retomar(self.caso_maria)
            self.assertIsNotNone(self.semanal(self.caso_maria))

    def test_retomar_o_que_nao_esta_encerrado_e_recusado(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.retomar(self.caso_maria)

    def test_o_banco_garante_um_so_desfecho_em_aberto(self):
        with contexto.como(self.ana.pk):
            Desfecho.objects.create(caso=self.caso_maria, tipo=DESISTENCIA, iniciativa=PACIENTE, data=self.hoje)
            with self.assertRaises(ValidationError):
                Desfecho.objects.create(caso=self.caso_maria, tipo=DESISTENCIA, iniciativa=PACIENTE, data=self.hoje)


class ListaDeAtivos(BaseDesfecho):
    def test_encerrado_sai_dos_ativos_sem_ser_apagado(self):
        with contexto.como(self.ana.pk):
            self.encerrar(self.caso_maria)
            self.assertNotIn(self.maria, pacientes_ativos())
            self.assertIn(self.maria, pacientes_encerrados())
            self.assertIn(self.joao, pacientes_ativos())

    def test_quem_segue_no_casal_continua_ativo(self):
        with contexto.como(self.ana.pk):
            criar_caso_coletivo([self.maria, self.joao])
            self.encerrar(self.caso_maria)
            self.assertIn(self.maria, pacientes_ativos())

    def test_retomado_volta_aos_ativos(self):
        with contexto.como(self.ana.pk):
            self.encerrar(self.caso_maria)
            servicos.retomar(self.caso_maria)
            self.assertIn(self.maria, pacientes_ativos())
            self.assertNotIn(self.maria, pacientes_encerrados())


class Exclusao(BaseDesfecho):
    def test_paciente_com_desfecho_nao_e_apagado(self):
        """Desistência antes da primeira sessão ainda é atendimento (ADR-049)."""
        with contexto.como(self.ana.pk):
            self.encerrar(self.caso_joao)
            with self.assertRaises(ValidationError):
                excluir_paciente(self.joao)

    def test_casal_com_sessoes_agendadas_e_apagado_sem_erro(self):
        with contexto.como(self.ana.pk):
            casal = criar_caso_coletivo([self.maria, self.joao])
            self.semanal(casal, hora=19)
            excluir_caso_coletivo(casal)
            self.assertFalse(Caso.objects.filter(pk=casal.pk).exists())
        self.assertFalse(Consulta.objetos_todos.filter(caso_id=casal.pk).exists())

    def test_casal_com_sessao_realizada_nao_e_apagado(self):
        with contexto.como(self.ana.pk):
            casal = criar_caso_coletivo([self.maria, self.joao])
            self.passada(casal, 3, Consulta.Estado.REALIZADA)
            with self.assertRaises(ValidationError):
                excluir_caso_coletivo(casal)
