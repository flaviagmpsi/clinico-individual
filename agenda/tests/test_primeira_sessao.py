"""A primeira sessão fora do dia da semana do horário fixo (ADR-120).

Aritmética de calendário, sem banco, como em `test_recorrencia`. Datas fixas e conferidas: **14/09/2026 é
segunda-feira**, logo 15/09 é terça e 18/09 é sexta.

O caso que originou isto: psicóloga cadastra a paciente numa **sexta**, informa que a primeira sessão é naquele
mesmo dia, e combina o horário fixo para **terça às 09:00**. Antes, a sexta não existia para o sistema — a agenda
desenhava só as terças, e a sessão combinada sumia sem aviso.

O par importa: a exceção tem de aparecer **uma vez** e não pode mexer na série nem na âncora da quinzenal.
"""

from datetime import date, time

from django.test import SimpleTestCase

from agenda.models import Recorrencia

SEMANAL = Recorrencia.Frequencia.SEMANAL
QUINZENAL = Recorrencia.Frequencia.QUINZENAL
TERCA = Recorrencia.DiaSemana.TERCA

SEGUNDA_14 = date(2026, 9, 14)
TERCA_15 = date(2026, 9, 15)
SEXTA_18 = date(2026, 9, 18)


def regra(frequencia=SEMANAL, inicio=SEGUNDA_14, fim=None, primeira=None, dia=TERCA):
    return Recorrencia(frequencia=frequencia, dia_semana=dia, hora=time(9), duracao=50,
                       inicio=inicio, fim=fim, primeira_sessao_em=primeira)


class CalendarioConferido(SimpleTestCase):
    def test_as_datas_de_referencia_sao_mesmo_o_que_dizem(self):
        self.assertEqual((SEGUNDA_14.weekday(), TERCA_15.weekday(), SEXTA_18.weekday()), (0, 1, 4))


class SemExcecao(SimpleTestCase):
    """Sem a data informada, nada muda — é a garantia de que toda regra que já existe continua igual."""

    def test_a_serie_e_so_o_dia_fixo(self):
        self.assertEqual(regra().ocorrencias(SEGUNDA_14, date(2026, 9, 30)),
                         [TERCA_15, date(2026, 9, 22), date(2026, 9, 29)])

    def test_a_sexta_nao_ocorre(self):
        self.assertFalse(regra().ocorre_em(SEXTA_18))


class ComExcecao(SimpleTestCase):
    def test_a_sexta_entra_na_serie_e_na_ordem_certa(self):
        self.assertEqual(regra(primeira=SEXTA_18).ocorrencias(SEGUNDA_14, date(2026, 9, 30)),
                         [TERCA_15, SEXTA_18, date(2026, 9, 22), date(2026, 9, 29)])

    def test_a_sexta_passa_a_ocorrer(self):
        """É isto que faz a tela de cadastrar a sessão aceitar a data em vez de devolver 404."""
        self.assertTrue(regra(primeira=SEXTA_18).ocorre_em(SEXTA_18))

    def test_entra_uma_vez_so(self):
        datas = regra(primeira=SEXTA_18).ocorrencias(SEGUNDA_14, date(2026, 12, 31))
        self.assertEqual(datas.count(SEXTA_18), 1)

    def test_nao_mexe_na_ancora_da_quinzenal(self):
        """A âncora continua sendo a primeira terça: a exceção é uma sessão, não um recomeço da contagem."""
        r = regra(QUINZENAL, primeira=SEXTA_18)
        self.assertEqual(r.primeira_ocorrencia, TERCA_15)
        self.assertEqual(r.ocorrencias(SEGUNDA_14, date(2026, 10, 15)),
                         [TERCA_15, SEXTA_18, date(2026, 9, 29), date(2026, 10, 13)])

    def test_nao_duplica_quando_cai_no_proprio_dia_fixo(self):
        """Defesa contra um dado inconsistente: se alguém gravar a exceção na terça, ela não vira duas sessões."""
        datas = regra(primeira=TERCA_15).ocorrencias(SEGUNDA_14, date(2026, 9, 30))
        self.assertEqual(datas, [TERCA_15, date(2026, 9, 22), date(2026, 9, 29)])


class ForaDaVigencia(SimpleTestCase):
    """A exceção obedece ao início e ao fim como qualquer sessão — senão viraria um furo na ADR-022."""

    def test_antes_do_inicio_nao_vale(self):
        r = regra(inicio=date(2026, 9, 21), primeira=SEXTA_18)
        self.assertFalse(r.ocorre_em(SEXTA_18))
        self.assertNotIn(SEXTA_18, r.ocorrencias(SEGUNDA_14, date(2026, 9, 30)))

    def test_na_data_do_fim_ou_depois_nao_vale(self):
        r = regra(fim=SEXTA_18, primeira=SEXTA_18)
        self.assertFalse(r.ocorre_em(SEXTA_18))
        self.assertNotIn(SEXTA_18, r.ocorrencias(SEGUNDA_14, date(2026, 9, 30)))

    def test_fora_do_intervalo_pedido_nao_aparece(self):
        self.assertNotIn(SEXTA_18, regra(primeira=SEXTA_18).ocorrencias(date(2026, 9, 20), date(2026, 9, 30)))
