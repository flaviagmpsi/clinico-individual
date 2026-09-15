"""O calendário dos vencimentos: Páscoa, feriados nacionais e N-ésimo dia útil (ADR-063).

Datas conferidas no calendário: 1º/09/2026 é terça e 07/09 é segunda-feira de feriado, então o 5º dia útil de
setembro de 2026 é 08/09. Sem banco — é aritmética de calendário.
"""

from datetime import date

from django.test import SimpleTestCase

from core.calendario import TipoDia, data_no_mes, descrever_dia, dia_util, feriados_nacionais, pascoa

UTIL = TipoDia.DIA_UTIL
FIXO = TipoDia.DIA_FIXO


class Pascoa(SimpleTestCase):
    def test_datas_conhecidas(self):
        self.assertEqual(pascoa(2024), date(2024, 3, 31))
        self.assertEqual(pascoa(2025), date(2025, 4, 20))
        self.assertEqual(pascoa(2026), date(2026, 4, 5))


class Feriados(SimpleTestCase):
    def test_sexta_feira_santa_e_feriado_e_carnaval_nao(self):
        feriados = feriados_nacionais(2026)
        self.assertIn(date(2026, 4, 3), feriados)
        self.assertNotIn(date(2026, 2, 16), feriados)  # segunda de Carnaval: ponto facultativo

    def test_consciencia_negra_so_a_partir_de_2024(self):
        self.assertIn(date(2026, 11, 20), feriados_nacionais(2026))
        self.assertNotIn(date(2023, 11, 20), feriados_nacionais(2023))

    def test_fim_de_semana_e_feriado_nao_sao_dia_util(self):
        self.assertFalse(dia_util(date(2026, 9, 7)))   # Independência, segunda-feira
        self.assertFalse(dia_util(date(2026, 9, 12)))  # sábado
        self.assertTrue(dia_util(date(2026, 9, 8)))


class DataNoMes(SimpleTestCase):
    def test_quinto_dia_util_pula_feriado(self):
        self.assertEqual(data_no_mes(UTIL, 5, 2026, 9), date(2026, 9, 8))
        self.assertEqual(data_no_mes(UTIL, 5, 2026, 10), date(2026, 10, 7))
        self.assertEqual(data_no_mes(UTIL, 5, 2026, 11), date(2026, 11, 9))  # 02/11 é Finados

    def test_dia_util_alem_do_mes_vira_o_ultimo(self):
        self.assertEqual(data_no_mes(UTIL, 23, 2026, 2), date(2026, 2, 27))

    def test_dia_fixo(self):
        self.assertEqual(data_no_mes(FIXO, 10, 2026, 9), date(2026, 9, 10))
        self.assertEqual(data_no_mes(FIXO, 31, 2026, 2), date(2026, 2, 28))

    def test_descricao(self):
        self.assertEqual(descrever_dia(FIXO, 10), "todo dia 10")
        self.assertEqual(descrever_dia(UTIL, 5), "todo 5º dia útil")
