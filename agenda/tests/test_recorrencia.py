"""O cálculo de datas da regra — sem banco, porque é aritmética de calendário.

Datas fixas de propósito, e conferidas: **14/09/2026 é segunda-feira**. Aqui não há "hoje" envolvido, então
fixar o calendário é o que torna o teste legível — e errado de um jeito visível, se alguém mexer na conta.
"""

from datetime import date, time

from django.test import SimpleTestCase

from agenda.models import Recorrencia

SEMANAL = Recorrencia.Frequencia.SEMANAL
QUINZENAL = Recorrencia.Frequencia.QUINZENAL
TERCA = Recorrencia.DiaSemana.TERCA


def regra(frequencia, inicio, fim=None, dia=TERCA):
    return Recorrencia(frequencia=frequencia, dia_semana=dia, hora=time(14), duracao=50, inicio=inicio, fim=fim)


class CalendarioConferido(SimpleTestCase):
    def test_a_data_de_referencia_e_mesmo_segunda(self):
        self.assertEqual(date(2026, 9, 14).weekday(), 0)


class PrimeiraOcorrencia(SimpleTestCase):
    def test_e_o_proximo_dia_da_semana_da_regra(self):
        self.assertEqual(regra(SEMANAL, date(2026, 9, 14)).primeira_ocorrencia, date(2026, 9, 15))

    def test_o_proprio_dia_de_inicio_conta(self):
        self.assertEqual(regra(SEMANAL, date(2026, 9, 15)).primeira_ocorrencia, date(2026, 9, 15))


class Semanal(SimpleTestCase):
    def test_toda_semana(self):
        self.assertEqual(
            regra(SEMANAL, date(2026, 9, 15)).ocorrencias(date(2026, 9, 15), date(2026, 10, 6)),
            [date(2026, 9, 15), date(2026, 9, 22), date(2026, 9, 29), date(2026, 10, 6)])


class Quinzenal(SimpleTestCase):
    """ADR-053: semana sim, semana não."""

    def test_semana_sim_semana_nao(self):
        r = regra(QUINZENAL, date(2026, 9, 15))
        self.assertEqual(r.ocorrencias(date(2026, 9, 15), date(2026, 10, 13)),
                         [date(2026, 9, 15), date(2026, 9, 29), date(2026, 10, 13)])
        self.assertFalse(r.ocorre_em(date(2026, 9, 22)))
        self.assertTrue(r.ocorre_em(date(2026, 9, 29)))

    def test_a_alternancia_conta_da_primeira_sessao_e_nao_do_inicio(self):
        """Início numa quinta: a primeira terça é 22/09, e é ela que define as semanas "sim"."""
        r = regra(QUINZENAL, date(2026, 9, 17))
        self.assertFalse(r.ocorre_em(date(2026, 9, 29)))
        self.assertTrue(r.ocorre_em(date(2026, 10, 6)))

    def test_janela_no_meio_da_serie_respeita_a_alternancia(self):
        r = regra(QUINZENAL, date(2026, 9, 15))
        self.assertEqual(r.ocorrencias(date(2026, 9, 20), date(2026, 10, 20)),
                         [date(2026, 9, 29), date(2026, 10, 13)])


class Encerramento(SimpleTestCase):
    def test_a_data_de_fim_ja_nao_tem_sessao(self):
        r = regra(SEMANAL, date(2026, 9, 15), fim=date(2026, 9, 29))
        self.assertEqual(r.ocorrencias(date(2026, 9, 15), date(2026, 10, 13)),
                         [date(2026, 9, 15), date(2026, 9, 22)])
        self.assertFalse(r.ocorre_em(date(2026, 9, 29)))

    def test_regra_encerrada_no_dia_do_inicio_nao_preve_nada(self):
        """Corrigir um horário recém-cadastrado encerra a regra no próprio dia de início."""
        r = regra(SEMANAL, date(2026, 9, 15), fim=date(2026, 9, 15))
        self.assertEqual(r.ocorrencias(date(2026, 9, 1), date(2026, 12, 31)), [])
