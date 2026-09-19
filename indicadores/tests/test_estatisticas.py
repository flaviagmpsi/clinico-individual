"""Estatísticas, aniversariantes e o que a ficha do paciente recebe de `indicadores` (ADR-084).

- `ContaDaPresenca` — o que entra e o que não entra no percentual.
- `RetratoDaClinica` — horário e dia mais usados, composição por frequência, presença por paciente.
- `Aniversariantes` — só do mês, só de quem está em atendimento.
- `Telas` — a aba de estatísticas, o quadro do painel e a ficha do paciente; e o isolamento entre psicólogos.
"""

from datetime import date, datetime, time
from decimal import Decimal

from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Recorrencia
from atendimentos import servicos as agenda
from atendimentos.models import Consulta, Desfecho
from contas.models import Psicologo
from core import contexto
from financeiro import servicos as financeiro
from financeiro.models import Pagamento
from indicadores import estatisticas
from indicadores.templatetags.ficha_do_paciente import situacao_financeira
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente

SENHA = "senha-de-teste-123"
E = Consulta.Estado


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


def momento(mes, dia, hora):
    return timezone.make_aware(datetime.combine(date(2026, mes, dia), time(hora)))


class ContaDaPresenca(SimpleTestCase):
    def test_so_conta_o_que_dependia_do_paciente(self):
        presenca = estatisticas.Presenca(presentes=6, faltas=1, canceladas_pelo_cliente=1,
                                         canceladas_pelo_profissional=3, remarcadas=2)
        self.assertEqual((presenca.esperadas, presenca.ausencias, presenca.canceladas, presenca.total), (8, 2, 4, 13))
        self.assertEqual(presenca.percentual, 75)

    def test_sem_sessao_nao_ha_percentual(self):
        self.assertIsNone(estatisticas.Presenca(remarcadas=2).percentual)


class BaseEstatisticas(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.estat@exemplo.com", "11111111111", "979797")
        cls.bruno = criar_psicologo("bruno.estat@exemplo.com", "22222222222", "989898")
        with contexto.como(cls.ana.pk):
            cls.marcos = Paciente(nome="Marcos", data_nascimento=date(1988, 9, 25))
            cls.caso_marcos = cadastrar_paciente(cls.marcos, valor=Decimal("200"), vigente_desde=date(2026, 1, 1))
            cls.julia = Paciente(nome="Júlia", data_nascimento=date(1995, 9, 3))
            cls.caso_julia = cadastrar_paciente(cls.julia)
            cls.pedro = Paciente(nome="Pedro", data_nascimento=date(1990, 3, 10))
            cls.caso_pedro = cadastrar_paciente(cls.pedro)
            # Marcos: três terças às 14h (duas presentes, uma falta) e uma quarta às 9h, remarcada.
            cls.sessoes_do_marcos = [
                agenda.cadastrar_avulsa(cls.caso_marcos, estado=E.REALIZADA, inicio=momento(9, 1, 14)),
                agenda.cadastrar_avulsa(cls.caso_marcos, estado=E.REALIZADA, inicio=momento(9, 8, 14)),
                agenda.cadastrar_avulsa(cls.caso_marcos, estado=E.FALTOU, inicio=momento(9, 15, 14)),
            ]
            agenda.cadastrar_avulsa(cls.caso_marcos, estado=E.CANCELADA_PROFISSIONAL, inicio=momento(9, 2, 9))
            # Júlia: uma quarta às 9h, presente. Sessão de 2025 não entra nas estatísticas de 2026.
            agenda.cadastrar_avulsa(cls.caso_julia, estado=E.REALIZADA, inicio=momento(9, 9, 9))
            Recorrencia.objects.create(caso=cls.caso_julia, frequencia=Recorrencia.Frequencia.QUINZENAL, dia_semana=2,
                                       hora=time(9), duracao=50, inicio=date(2026, 9, 9))
            # Pedro desistiu: sai da composição e dos aniversariantes.
            agenda.registrar_desfecho(cls.caso_pedro, tipo=Desfecho.Tipo.DESISTENCIA, data=date(2026, 9, 1))
        with contexto.como(cls.bruno.pk):
            carla = Paciente(nome="Carla", data_nascimento=date(1980, 9, 12))
            agenda.cadastrar_avulsa(cadastrar_paciente(carla), estado=E.REALIZADA, inicio=momento(9, 4, 20))


class RetratoDaClinica(BaseEstatisticas):
    def montar(self, ano=2026):
        with contexto.como(self.ana.pk):
            return estatisticas.montar(ano)

    def test_presenca_horario_dia_e_composicao(self):
        e = self.montar()
        self.assertEqual((e.presenca.presentes, e.presenca.esperadas, e.presenca.percentual), (3, 4, 75))
        self.assertEqual(e.presenca.canceladas_pelo_profissional, 1)
        self.assertEqual(e.horario_mais_usado, ("14h", 2))
        self.assertEqual(e.dia_mais_cheio, ("Terça", 2))
        self.assertNotIn("20h", [rotulo for rotulo, _ in e.horarios])  # a sessão do Bruno não aparece
        self.assertEqual((e.composicao.semanais, e.composicao.quinzenais, e.composicao.avulsos), (0, 1, 1))

    def test_presenca_por_paciente_vem_da_menor_para_a_maior(self):
        por_paciente = [(str(caso), p.percentual, p.presentes, p.esperadas) for caso, p in self.montar().por_paciente]
        self.assertEqual(por_paciente, [("Marcos", 67, 2, 3), ("Júlia", 100, 1, 1)])

    def test_no_mes_quem_esta_em_atendimento_sem_sessao_aparece_por_ultimo(self):
        """ADR-087: "sem sessão no mês" é informação real da clínica; o Pedro, encerrado, não entra."""
        with contexto.como(self.ana.pk):
            setembro = estatisticas.montar(2026, 9)
            agosto = estatisticas.montar(2026, 8)
        self.assertEqual(setembro.mes, 9)
        self.assertEqual([(str(caso), p.percentual) for caso, p in setembro.por_paciente],
                         [("Marcos", 67), ("Júlia", 100)])
        self.assertEqual([(str(caso), p.total) for caso, p in agosto.por_paciente], [("Júlia", 0), ("Marcos", 0)])
        self.assertEqual((agosto.presenca.total, agosto.horario_mais_usado), (0, None))
        self.assertEqual(len(agosto.fluxos), 12)  # o dinheiro é sempre do ano

    def test_ano_sem_sessao_nao_quebra(self):
        e = self.montar(2024)
        self.assertEqual((e.presenca.total, e.horario_mais_usado, e.dia_mais_cheio, e.por_paciente), (0, None, None, []))
        self.assertEqual(len(e.fluxos), 12)

    def test_frequencia_do_paciente_conta_todas_as_sessoes_dele(self):
        with contexto.como(self.ana.pk):
            presenca = estatisticas.presenca_do_paciente(self.marcos)
        self.assertEqual((presenca.presentes, presenca.faltas, presenca.canceladas, presenca.remarcadas), (2, 1, 1, 0))


class SituacaoFinanceiraNaFicha(BaseEstatisticas):
    def test_pendente_em_dia_e_sem_cobranca(self):
        with contexto.como(self.ana.pk):
            pendente = situacao_financeira(self.caso_marcos)
            self.assertEqual((pendente["estado"], len(pendente["pendentes"]), pendente["total"]),
                             ("pendente", 3, Decimal("600")))  # a falta sem aviso também é cobrada (ADR-065)
            for consulta in self.sessoes_do_marcos:
                financeiro.registrar_pagamento_sessao(consulta, data=date(2026, 9, 16), forma=Pagamento.Forma.PIX)
            self.assertEqual(situacao_financeira(self.caso_marcos)["estado"], "em_dia")
            self.assertEqual(situacao_financeira(self.caso_julia)["estado"], "sem_cobranca")
            self.assertEqual(situacao_financeira(None)["estado"], "sem_cobranca")


class Aniversariantes(BaseEstatisticas):
    def test_so_do_mes_e_so_de_quem_esta_em_atendimento(self):
        with contexto.como(self.ana.pk):
            setembro = estatisticas.aniversariantes_do_mes(date(2026, 9, 25))
            marco = estatisticas.aniversariantes_do_mes(date(2026, 3, 1))
        self.assertEqual([(a["paciente"].nome, a["dia"], a["idade"], a["hoje"], a["passou"]) for a in setembro],
                         [("Júlia", 3, 31, False, True), ("Marcos", 25, 38, True, False)])
        self.assertEqual(marco, [])  # o Pedro faz em março, mas desistiu


class Telas(TransactionTestCase):
    def setUp(self):
        hoje = timezone.localdate()
        self.ana = criar_psicologo("ana.telaestat@exemplo.com", "11111111111", "999999")
        self.bruno = criar_psicologo("bruno.telaestat@exemplo.com", "22222222222", "909090")
        with contexto.como(self.ana.pk):
            self.marcos = Paciente(nome="Marcos Aniversariante", data_nascimento=date(1988, hoje.month, 1))
            caso = cadastrar_paciente(self.marcos, valor=Decimal("200"), vigente_desde=date(2026, 1, 1))
            agenda.cadastrar_avulsa(caso, estado=E.REALIZADA, inicio=momento(9, 1, 14))
            agenda.cadastrar_avulsa(caso, estado=E.FALTOU, inicio=momento(9, 8, 14))
        with contexto.como(self.bruno.pk):
            carla = Paciente(nome="Carla Alheia", data_nascimento=date(1980, hoje.month, 2))
            agenda.cadastrar_avulsa(cadastrar_paciente(carla), estado=E.REALIZADA, inicio=momento(9, 4, 20))

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def test_estatisticas_exige_login_e_mostra_so_a_propria_clinica(self):
        self.assertEqual(self.client.get(reverse("estatisticas")).status_code, 302)
        self.entrar(self.ana)
        resposta = self.client.get(reverse("estatisticas"), {"periodo": "ano", "ano": "2026"})
        self.assertContains(resposta, "Resultado previsto de 2026")
        self.assertContains(resposta, "Receitas de 2026")
        self.assertIsNone(resposta.context["mes"])
        self.assertContains(resposta, "1 de 2 sessões realizadas")
        self.assertContains(resposta, "14h")
        self.assertNotContains(resposta, "20h")
        self.assertNotContains(resposta, "Carla Alheia")
        self.assertEqual(resposta.context["grafico"]["horarios"], {"rotulos": ["14h"], "valores": [1]})
        self.assertEqual(len(resposta.context["grafico"]["resultado"]), 12)
        self.assertContains(self.client.get(reverse("painel")), reverse("estatisticas"))  # a barra lateral leva até lá

    def test_abre_no_mes_corrente_e_lixo_cai_no_padrao(self):
        """ADR-087: o padrão é o mês; o ano é opção no topo."""
        self.entrar(self.ana)
        hoje = timezone.localdate()
        resposta = self.client.get(reverse("estatisticas"))
        self.assertEqual((resposta.context["ano"], resposta.context["mes"]), (hoje.year, hoje.month))
        self.assertNotContains(resposta, "Receitas de")  # os cartões de dinheiro são do modo ano
        self.assertContains(resposta, "fluxo de caixa")
        self.assertEqual(self.client.get(reverse("estatisticas"), {"mes": "abc"}).context["mes"], hoje.month)
        self.assertIsNone(self.client.get(reverse("estatisticas"), {"periodo": "ano", "ano": "abc"}).context["mes"])

    def test_painel_mostra_os_aniversariantes_do_mes(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("painel"))
        self.assertContains(resposta, "Aniversariantes de")
        self.assertContains(resposta, "Marcos Aniversariante")
        self.assertNotContains(resposta, "Carla Alheia")

    def test_ficha_mostra_frequencia_e_situacao_financeira(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("pacientes:detalhe", args=[self.marcos.pk]))
        self.assertContains(resposta, "50%</strong> de presença · 1 de 2")
        self.assertContains(resposta, "2 pendências")
        self.assertContains(resposta, reverse("prontuarios:anamnese", args=[self.marcos.pk]))
        with contexto.como(self.ana.pk):
            for consulta in Consulta.objects.all():
                financeiro.registrar_pagamento_sessao(consulta, data=date(2026, 9, 16), forma=Pagamento.Forma.PIX)
        self.assertContains(self.client.get(reverse("pacientes:detalhe", args=[self.marcos.pk])), "Em dia")
