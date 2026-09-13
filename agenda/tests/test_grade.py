"""A grade de horários: declarar, avisar fora dela e derivar a ocupação (ADR-029, ADR-056).

Datas partem de "hoje" porque a frequência só vale de hoje em diante; `proxima` garante que a série começa no
futuro, seja qual for o dia em que o teste roda. A grade em si não tem data — é semanal.
"""

from datetime import time, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from agenda import grade
from agenda.models import HorarioDisponivel, Recorrencia
from atendimentos import servicos
from contas.models import Psicologo
from core import contexto
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente

SEMANAL = Recorrencia.Frequencia.SEMANAL
QUINZENAL = Recorrencia.Frequencia.QUINZENAL
SEGUNDA = Recorrencia.DiaSemana.SEGUNDA
TERCA = Recorrencia.DiaSemana.TERCA
QUARTA = Recorrencia.DiaSemana.QUARTA


def proxima(dia_semana):
    amanha = timezone.localdate() + timedelta(days=1)
    return amanha + timedelta(days=(dia_semana - amanha.weekday()) % 7)


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password="senha-de-teste-123", nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


def bloco(dia, de, ate):
    return HorarioDisponivel.objects.create(dia_semana=dia, inicio=time(*de) if isinstance(de, tuple) else time(de),
                                            fim=time(*ate) if isinstance(ate, tuple) else time(ate))


class BaseGrade(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.grade@exemplo.com", "11111111111", "979797")
        cls.bruno = criar_psicologo("bruno.grade@exemplo.com", "22222222222", "989898")
        with contexto.como(cls.ana.pk):
            cls.caso_maria = cadastrar_paciente(Paciente(nome="Maria Grade"))
            cls.caso_joao = cadastrar_paciente(Paciente(nome="João Grade"))
        with contexto.como(cls.bruno.pk):
            cls.caso_carla = cadastrar_paciente(Paciente(nome="Carla Grade"))

    def frequencia(self, caso, dia, hora, frequencia=SEMANAL, duracao=60):
        return servicos.definir_frequencia(
            caso, frequencia=frequencia, dia_semana=dia, hora=time(hora), duracao=duracao, a_partir_de=proxima(dia))


class DeclararGrade(BaseGrade):
    def test_fim_antes_do_inicio_e_recusado(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                bloco(TERCA, 18, 14)

    def test_bloco_sobreposto_no_mesmo_dia_e_recusado(self):
        """Contaria a mesma hora duas vezes na ocupação."""
        with contexto.como(self.ana.pk):
            bloco(TERCA, 14, 18)
            with self.assertRaises(ValidationError):
                bloco(TERCA, 17, 20)

    def test_bloco_encostado_e_aceito(self):
        with contexto.como(self.ana.pk):
            bloco(TERCA, 8, 12)
            bloco(TERCA, 12, 14)
            self.assertEqual(HorarioDisponivel.objects.count(), 2)

    def test_grade_de_outro_psicologo_nao_conflita(self):
        with contexto.como(self.bruno.pk):
            bloco(TERCA, 14, 18)
        with contexto.como(self.ana.pk):
            bloco(TERCA, 14, 18)
            self.assertEqual(HorarioDisponivel.objects.count(), 1)


class ForaDaGrade(BaseGrade):
    def test_sem_grade_nunca_avisa(self):
        """Quem não declarou grade não é lembrado a cada consulta de algo que escolheu não usar."""
        with contexto.como(self.ana.pk):
            self.assertFalse(grade.fora_da_grade(TERCA, time(3), 50))

    def test_dentro_da_grade_nao_avisa(self):
        with contexto.como(self.ana.pk):
            bloco(TERCA, 14, 18)
            self.assertFalse(grade.fora_da_grade(TERCA, time(14), 50))
            self.assertFalse(grade.fora_da_grade(TERCA, time(17, 10), 50))

    def test_passar_do_fim_ou_trocar_de_dia_avisa(self):
        with contexto.como(self.ana.pk):
            bloco(TERCA, 14, 18)
            self.assertTrue(grade.fora_da_grade(TERCA, time(17, 30), 50))
            self.assertTrue(grade.fora_da_grade(SEGUNDA, time(14), 50))

    def test_blocos_encostados_valem_como_um(self):
        with contexto.como(self.ana.pk):
            bloco(TERCA, 8, 12)
            bloco(TERCA, 12, 14)
            self.assertFalse(grade.fora_da_grade(TERCA, time(11, 30), 60))

    def test_grade_de_outro_psicologo_nao_conta(self):
        with contexto.como(self.bruno.pk):
            bloco(TERCA, 14, 18)
        with contexto.como(self.ana.pk):
            self.assertFalse(grade.fora_da_grade(SEGUNDA, time(3), 50))


class MapaDaSemana(BaseGrade):
    def test_semanal_ocupa_e_o_resto_sobra(self):
        with contexto.como(self.ana.pk):
            bloco(TERCA, 14, 18)
            self.frequencia(self.caso_maria, TERCA, 14)
            mapa = grade.mapa_da_semana()
        _, trechos = mapa.dias[0].blocos[0]
        self.assertEqual([(t.hora_inicio, t.hora_fim, t.livre) for t in trechos],
                         [(time(14), time(15), False), (time(15), time(18), True)])
        self.assertEqual(trechos[0].regras[0].caso, self.caso_maria)
        self.assertEqual((mapa.minutos_disponiveis, mapa.minutos_ocupados, mapa.ocupacao), (240, 60, 25))

    def test_quinzenal_ocupa_metade(self):
        """Na outra semana o horário está livre (ADR-056)."""
        with contexto.como(self.ana.pk):
            bloco(TERCA, 14, 18)
            self.frequencia(self.caso_joao, TERCA, 16, frequencia=QUINZENAL)
            mapa = grade.mapa_da_semana()
        self.assertEqual(mapa.minutos_ocupados, 30)
        self.assertEqual(mapa.horas_livres, "3h30")

    def test_sessao_fixa_fora_da_grade_aparece_e_nao_conta(self):
        with contexto.como(self.ana.pk):
            bloco(TERCA, 14, 18)
            regra = self.frequencia(self.caso_joao, QUARTA, 9)
            mapa = grade.mapa_da_semana()
        quarta = next(dia for dia in mapa.dias if dia.numero == QUARTA)
        self.assertEqual(quarta.fora, [regra])
        self.assertEqual(mapa.minutos_ocupados, 0)

    def test_quem_virou_avulso_deixa_de_ocupar(self):
        with contexto.como(self.ana.pk):
            bloco(TERCA, 14, 18)
            self.frequencia(self.caso_maria, TERCA, 14)
            servicos.definir_frequencia(self.caso_maria, frequencia=servicos.AVULSO)
            self.assertEqual(grade.mapa_da_semana().minutos_ocupados, 0)

    def test_so_enxerga_a_propria_grade_e_os_proprios_pacientes(self):
        with contexto.como(self.bruno.pk):
            bloco(SEGUNDA, 8, 12)
            self.frequencia(self.caso_carla, SEGUNDA, 9)
        with contexto.como(self.ana.pk):
            mapa = grade.mapa_da_semana()
        self.assertEqual(mapa.dias, [])
        self.assertFalse(mapa.tem_grade)
