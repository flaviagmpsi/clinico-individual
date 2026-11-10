"""O cálculo de datas da regra — sem banco, porque é aritmética de calendário.

Datas fixas de propósito, e conferidas: **14/09/2026 é segunda-feira**, logo 01/09/2026 é terça. As terças de
setembro são 1, 8, 15, 22 e 29 (cinco — mês de cinco semanas); as de outubro, 6, 13, 20 e 27. Aqui não há "hoje"
envolvido, então fixar o calendário é o que torna o teste legível — e errado de um jeito visível, se alguém mexer.
"""

from collections import Counter
from datetime import date, time

from django.test import SimpleTestCase

from agenda.models import Recorrencia

SEMANAL = Recorrencia.Frequencia.SEMANAL
QUINZENAL = Recorrencia.Frequencia.QUINZENAL
TERCA = Recorrencia.DiaSemana.TERCA


def regra(frequencia, inicio, fim=None, dia=TERCA, semanas="1E3"):
    return Recorrencia(frequencia=frequencia, dia_semana=dia, hora=time(14), duracao=50, inicio=inicio, fim=fim,
                       semanas_do_mes=semanas if frequencia == QUINZENAL else "")


class CalendarioConferido(SimpleTestCase):
    def test_as_datas_de_referencia_sao_mesmo_o_que_dizem(self):
        self.assertEqual(date(2026, 9, 14).weekday(), 0)   # segunda
        self.assertEqual(date(2026, 9, 1).weekday(), 1)    # terça


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
    """ADR-146: par fixo de semanas do mês — sempre duas por mês, nunca três, a 5ª semana ignorada."""

    def test_primeira_e_terceira_semana(self):
        r = regra(QUINZENAL, date(2026, 9, 1), semanas="1E3")
        self.assertEqual(r.ocorrencias(date(2026, 9, 1), date(2026, 10, 31)),
                         [date(2026, 9, 1), date(2026, 9, 15), date(2026, 10, 6), date(2026, 10, 20)])

    def test_segunda_e_quarta_semana(self):
        r = regra(QUINZENAL, date(2026, 9, 1), semanas="2E4")
        self.assertEqual(r.ocorrencias(date(2026, 9, 1), date(2026, 9, 30)),
                         [date(2026, 9, 8), date(2026, 9, 22)])

    def test_mes_de_cinco_semanas_nunca_tem_tres_sessoes(self):
        """Setembro/2026 tem cinco terças. Os dois pares pegam só duas; a 5ª (29/09) fica de fora."""
        for semanas in ("1E3", "2E4"):
            datas = regra(QUINZENAL, date(2026, 9, 1), semanas=semanas).ocorrencias(date(2026, 9, 1), date(2026, 9, 30))
            self.assertEqual(len(datas), 2, semanas)
        self.assertFalse(regra(QUINZENAL, date(2026, 9, 1), semanas="1E3").ocorre_em(date(2026, 9, 29)))

    def test_nunca_mais_de_duas_por_mes_ao_longo_do_ano(self):
        datas = regra(QUINZENAL, date(2026, 1, 1), semanas="2E4").ocorrencias(date(2026, 1, 1), date(2026, 12, 31))
        por_mes = Counter((d.year, d.month) for d in datas)
        self.assertEqual(set(por_mes.values()), {2})

    def test_dentro_do_par_sao_catorze_dias_entre_meses_estica(self):
        r = regra(QUINZENAL, date(2026, 9, 1), semanas="1E3")
        self.assertEqual((date(2026, 9, 15) - date(2026, 9, 1)).days, 14)   # dentro do par
        self.assertEqual((date(2026, 10, 6) - date(2026, 9, 15)).days, 21)  # virando o mês, estica
        self.assertTrue(r.ocorre_em(date(2026, 10, 6)))
        self.assertFalse(r.ocorre_em(date(2026, 9, 22)))

    def test_janela_no_meio_da_serie(self):
        r = regra(QUINZENAL, date(2026, 9, 1), semanas="1E3")
        self.assertEqual(r.ocorrencias(date(2026, 9, 16), date(2026, 10, 31)),
                         [date(2026, 10, 6), date(2026, 10, 20)])

    def test_respeita_o_inicio(self):
        """Começa em 16/09: as terças de 01 e 15/09 já passaram, então a primeira é a 1ª de outubro (06/10)."""
        r = regra(QUINZENAL, date(2026, 9, 16), semanas="1E3")
        self.assertEqual(r.primeira_ocorrencia, date(2026, 10, 6))
        self.assertFalse(r.ocorre_em(date(2026, 9, 15)))
        self.assertTrue(r.ocorre_em(date(2026, 10, 6)))


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

    def test_quinzenal_encerrada_respeita_o_fim(self):
        r = regra(QUINZENAL, date(2026, 9, 1), fim=date(2026, 10, 6), semanas="1E3")
        self.assertEqual(r.ocorrencias(date(2026, 9, 1), date(2026, 10, 31)),
                         [date(2026, 9, 1), date(2026, 9, 15)])
