"""Correções nos gráficos relatadas por uma testadora (ADR-128).

Dois defeitos reais, medidos na conta dela:

- **Horas de trabalho contavam o futuro.** O cartão diz "como a sua agenda funcionou", mas somava compromissos
  que ainda não tinham acontecido — 23 de 35 num mês, e o ano inteiro até dezembro. Agora conta só até hoje, o
  mesmo critério das sessões.
- **O gráfico de horários pulava horas vazias.** Só devolvia as horas com sessão, e as barras desenhavam "11h"
  colado em "18h"; a forma dizia "tarde cheia" com a tarde vazia. Agora a faixa é contínua, com zero no vão.
"""

from datetime import date, time, timedelta

from django.test import TestCase
from django.utils import timezone

from agenda.models import Compromisso
from atendimentos import servicos as agenda
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto
from indicadores import estatisticas
from indicadores.periodo import Periodo
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = Psicologo.objects.create_user(
            email="ana.graf@exemplo.com", password="senha-de-teste-123", nome_completo="Ana",
            crp_regiao="04", crp_numero="757676")
        cls.hoje = timezone.localdate()


class HorasDeTrabalho(Base):
    def test_nao_conta_compromisso_que_ainda_nao_aconteceu(self):
        depois = self.hoje + timedelta(days=3)
        with contexto.como(self.ana.pk):
            # um compromisso de uma vez só, no futuro, dentro do mês ou não — não deve contar
            Compromisso.objects.create(titulo="Supervisão futura", frequencia=Compromisso.Frequencia.UNICO,
                                       inicio=depois + timedelta(days=400), hora=time(10), duracao=60)
            retrato = estatisticas.retrato_da_agenda(Periodo(self.hoje.year, None))  # o ano
        self.assertEqual(retrato.minutos_fora_da_clinica, 0)

    def test_conta_o_compromisso_que_ja_passou(self):
        if self.hoje.day < 3:
            self.skipTest("precisa de um dia já passado neste mês")
        with contexto.como(self.ana.pk):
            Compromisso.objects.create(titulo="Supervisão de ontem", frequencia=Compromisso.Frequencia.UNICO,
                                       inicio=self.hoje - timedelta(days=1), hora=time(10), duracao=60)
            retrato = estatisticas.retrato_da_agenda(Periodo(self.hoje.year, self.hoje.month))
        self.assertEqual(retrato.minutos_fora_da_clinica, 60)


class GraficoDeHorarios(Base):
    def test_a_faixa_de_horas_e_continua(self):
        """Uma sessão às 9h e outra às 18h: o gráfico mostra 9h..18h, não só as duas pontas."""
        with contexto.como(self.ana.pk):
            caso = cadastrar_paciente(Paciente(nome="P"))
            ontem = self.hoje - timedelta(days=1)
            for hora in (9, 18):
                agenda.cadastrar_avulsa(
                    caso, estado=Consulta.Estado.REALIZADA,
                    inicio=timezone.make_aware(__import__("datetime").datetime.combine(ontem, time(hora))))
            retrato = estatisticas.retrato_da_agenda(Periodo(self.hoje.year, self.hoje.month))
        rotulos = [r for r, _ in retrato.horarios]
        self.assertEqual(rotulos, [f"{h:02d}h" for h in range(9, 19)])   # sem buracos
        valores = dict(retrato.horarios)
        self.assertEqual(valores["09h"], 1)
        self.assertEqual(valores["18h"], 1)
        self.assertEqual(valores["13h"], 0)   # o vão existe e é zero

    def test_sem_sessao_nenhuma_o_grafico_fica_vazio(self):
        with contexto.como(self.ana.pk):
            retrato = estatisticas.retrato_da_agenda(Periodo(self.hoje.year, self.hoje.month))
        self.assertEqual(retrato.horarios, [])
