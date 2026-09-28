"""O painel (ADR-061, ADR-069, ADR-072): a agenda de hoje, as pendências num bloco e os números do mês.

- `AgendaDeHoje` — as sessões do dia, cadastradas ou esperando cadastro; nada além do dia.
- `Pendencias` — sessão de dia anterior sem cadastro, pagamento vencido e prontuário por escrever, uma vez cada;
  a de hoje não se repete; sem nada pendente, o bloco diz que está vazio.
- `ResumoDoMes` — sessões feitas e que faltam, recebido e a receber, ativos.
- `Isolamento` — nada de outro psicólogo, em nenhum bloco.
- `PainelPelaTela` — a tela abre logada com os três blocos.

Calculado com `AGORA` fixo em 20/09/2026, 12h — um domingo. Setembro de 2026, conferido: as terças são 1, 8,
15, 22 e 29. As consultas de 20/09 são cadastradas passando `agora=AGORA`, porque o serviço só aceita o que já
aconteceu (ADR-060) e esse dia ainda não chegou no relógio de quem roda o teste.

O Marcos exercita as três pendências de uma vez: falta sem aviso em 08/09 sem pagamento, a sessão de 15/09
sem cadastro e a sessão de 01/09 sem prontuário.
"""

from datetime import date, datetime, time
from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Recorrencia
from atendimentos import servicos as agenda
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto
from financeiro import servicos as financeiro
from financeiro.models import Pagamento
from indicadores.servicos import montar_painel
from pacientes.models import CondicaoCobranca, Paciente
from pacientes.servicos import cadastrar_paciente
from prontuarios import servicos as prontuarios

SENHA = "senha-de-teste-123"
AGORA = timezone.make_aware(datetime(2026, 9, 20, 12))
SEMANAL = Recorrencia.Frequencia.SEMANAL
REALIZADA = Consulta.Estado.REALIZADA
FALTOU = Consulta.Estado.FALTOU
REMARCADA = Consulta.Estado.REMARCADA
ONLINE = Paciente.Modalidade.ONLINE
PIX = Pagamento.Forma.PIX


def setembro(dia):
    return date(2026, 9, dia)


def momento(dia, hora=10):
    return timezone.make_aware(datetime.combine(dia, time(hora)))


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


def marcos_com_tres_pendencias(nome="Marcos"):
    caso = cadastrar_paciente(Paciente(nome=nome), valor=Decimal("200"), vigente_desde=date(2026, 1, 1))
    regra = Recorrencia.objects.create(caso=caso, frequencia=SEMANAL, dia_semana=1, hora=time(14), duracao=50,
                                       inicio=setembro(1))
    primeira = agenda.cadastrar_prevista(regra, setembro(1), estado=REALIZADA)
    agenda.cadastrar_prevista(regra, setembro(8), estado=FALTOU)
    financeiro.registrar_pagamento_sessao(primeira, data=setembro(1), forma=PIX)
    return caso


class BasePainel(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.painel@exemplo.com", "11111111111", "575757")
        cls.bruno = criar_psicologo("bruno.painel@exemplo.com", "22222222222", "585858")
        with contexto.como(cls.ana.pk):
            cls.caso_marcos = marcos_com_tres_pendencias()
            cls.caso_juliana = cadastrar_paciente(
                Paciente(nome="Juliana", modalidade=ONLINE), valor=Decimal("700"),
                modalidade=CondicaoCobranca.Modalidade.MENSAL, dia_vencimento=10, vigente_desde=setembro(1))
        with contexto.como(cls.bruno.pk):
            cls.caso_carla = cadastrar_paciente(Paciente(nome="Carla"), valor=Decimal("250"),
                                                vigente_desde=date(2026, 1, 1))
            agenda.cadastrar_avulsa(cls.caso_carla, estado=REALIZADA, inicio=momento(setembro(2)))

    def painel(self):
        with contexto.como(self.ana.pk):
            return montar_painel(AGORA)

    def hoje(self, caso, hora=9, estado=REALIZADA):
        """Uma sessão em 20/09 — o 'hoje' do painel. `agora=AGORA` porque o dia ainda não chegou de verdade."""
        return agenda.cadastrar_avulsa(caso, estado=estado, inicio=momento(setembro(20), hora), agora=AGORA)

    def prevista_para_hoje(self, hora):
        """Semanal aos domingos desde 13/09: prevê 20/09 no horário pedido."""
        return Recorrencia.objects.create(caso=self.caso_juliana, frequencia=SEMANAL, dia_semana=6,
                                          hora=time(hora), duracao=50, inicio=setembro(13))


class AgendaDeHoje(BasePainel):
    def test_as_sessoes_do_dia_em_ordem_de_horario(self):
        with contexto.como(self.ana.pk):
            self.hoje(self.caso_juliana, hora=11)
            self.hoje(self.caso_marcos, hora=9)
        itens = self.painel().hoje_itens
        self.assertEqual([(timezone.localtime(i.inicio).hour, i.caso.pk) for i in itens],
                         [(9, self.caso_marcos.pk), (11, self.caso_juliana.pk)])
        self.assertTrue(all(item.cadastrada for item in itens))

    def test_a_modalidade_vem_junto(self):
        with contexto.como(self.ana.pk):
            self.hoje(self.caso_juliana)
        [item] = self.painel().hoje_itens
        self.assertTrue(item.online)

    def test_prevista_para_hoje_e_prevista_ate_passar_e_depois_a_cadastrar(self):
        """Painel calculado ao meio-dia: às 14h ainda não passou; às 9h já passou."""
        with contexto.como(self.ana.pk):
            regra = self.prevista_para_hoje(hora=14)
        [item] = self.painel().hoje_itens
        self.assertEqual((item.situacao, item.cadastrada), ("prevista", False))

        with contexto.como(self.ana.pk):
            Recorrencia.objects.filter(pk=regra.pk).update(hora=time(9))
        [item] = self.painel().hoje_itens
        self.assertEqual(item.situacao, "a cadastrar")

    def test_sessao_remarcada_para_hoje_espera_cadastro(self):
        with contexto.como(self.ana.pk):
            agenda.cadastrar_avulsa(self.caso_marcos, estado=REMARCADA, inicio=momento(setembro(14)),
                                    remarcada_para=momento(setembro(20), 15))
        [item] = self.painel().hoje_itens
        self.assertEqual(timezone.localtime(item.inicio).hour, 15)
        self.assertIsNotNone(item.espera.origem)

    def test_o_dia_e_so_o_dia(self):
        """A sessão de 15/09 sem cadastro não entra na agenda de hoje — é pendência, e mora no bloco dela."""
        self.assertEqual(self.painel().hoje_itens, [])


class Pendencias(BasePainel):
    def test_as_tres_pendencias_do_marcos_uma_vez_cada(self):
        pendencias = self.painel().pendencias
        self.assertEqual([timezone.localtime(s.inicio).date() for s in pendencias.sessoes], [setembro(15)])
        self.assertEqual([(c.caso.pk, c.vencimento) for c in pendencias.pagamentos],
                         [(self.caso_marcos.pk, setembro(8)), (self.caso_juliana.pk, setembro(10))])
        self.assertEqual([(r.consulta.inicio.date(), r.paciente.nome) for r in pendencias.prontuarios],
                         [(setembro(1), "Marcos")])
        self.assertEqual(pendencias.total, 4)

    def test_a_sessao_de_hoje_que_passou_fica_no_dia_e_nao_se_repete_nas_pendencias(self):
        with contexto.como(self.ana.pk):
            self.prevista_para_hoje(hora=9)
        painel = self.painel()
        self.assertIn("a cadastrar", [item.situacao for item in painel.hoje_itens])
        self.assertNotIn(setembro(20), [timezone.localtime(s.inicio).date() for s in painel.pendencias.sessoes])

    def test_resolver_tira_da_lista(self):
        with contexto.como(self.ana.pk):
            financeiro.registrar_pagamento_mensalidade(
                self.caso_juliana, ano=2026, mes=9, valor=Decimal("700"), data=setembro(5), forma=PIX)
            sessao = self.caso_marcos.consultas.filter(estado=REALIZADA).first()
            prontuarios.confirmar(sessao, self.caso_marcos.pacientes.first(), texto="Registro da sessão.")
        pendencias = self.painel().pendencias
        self.assertEqual([c.caso.pk for c in pendencias.pagamentos], [self.caso_marcos.pk])
        self.assertEqual(pendencias.prontuarios, [])

    def test_sem_nada_pendente_o_bloco_e_vazio(self):
        with contexto.como(self.ana.pk):
            caso = cadastrar_paciente(Paciente(nome="Em dia"))
            outra = criar_psicologo("limpa.painel@exemplo.com", "33333333333", "595959")
        with contexto.como(outra.pk):
            self.assertEqual(montar_painel(AGORA).pendencias.total, 0)
        self.assertIsNotNone(caso)


class ResumoDoMes(BasePainel):
    def test_sessoes_feitas_e_as_que_faltam(self):
        """Feita: 01/09. Faltam: 22 e 29/09. A de 15/09 é pendente de cadastro, não previsão."""
        resumo = self.painel().resumo
        self.assertEqual((resumo.sessoes_feitas, resumo.sessoes_faltam), (1, 2))

    def test_recebido_e_a_receber(self):
        """Recebido: a sessão de 01/09. A receber: falta cobrada (200) + mensalidade (700) + duas previstas (400)."""
        resumo = self.painel().resumo
        self.assertEqual((resumo.recebido, resumo.a_receber), (Decimal("200"), Decimal("1300")))

    def test_pacientes_ativos_e_atendimento_encerrado_sai(self):
        self.assertEqual(self.painel().resumo.pacientes_ativos, 2)
        with contexto.como(self.ana.pk):
            agenda.registrar_desfecho(self.caso_juliana, tipo="DESISTENCIA", data=setembro(14))
        self.assertEqual(self.painel().resumo.pacientes_ativos, 1)


class Isolamento(BasePainel):
    def test_nada_de_outro_psicologo_em_bloco_nenhum(self):
        with contexto.como(self.bruno.pk):
            agenda.cadastrar_avulsa(self.caso_carla, estado=REALIZADA, inicio=momento(setembro(20), 8),
                                    agora=AGORA)
        painel = self.painel()
        self.assertNotIn(self.caso_carla.pk, [item.caso.pk for item in painel.hoje_itens])
        self.assertNotIn(self.caso_carla.pk, [c.caso.pk for c in painel.pendencias.pagamentos])
        self.assertNotIn("Carla", [r.paciente.nome for r in painel.pendencias.prontuarios])


class PainelPelaTela(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.telapainel@exemplo.com", "33333333333", "595959")
        self.bruno = criar_psicologo("bruno.telapainel@exemplo.com", "44444444444", "606060")
        with contexto.como(self.ana.pk):
            marcos_com_tres_pendencias("Marcos Painel")
        with contexto.como(self.bruno.pk):
            cadastrar_paciente(Paciente(nome="Carla Painel"))

    def test_exige_login(self):
        resposta = self.client.get(reverse("painel"))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("contas:entrar"), resposta["Location"])

    def test_mostra_o_dia_as_pendencias_e_nao_o_atendimento_alheio(self):
        self.assertTrue(self.client.login(username=self.ana.email, password=SENHA))
        resposta = self.client.get(reverse("painel"))
        # ADR-104: cada pendência virou uma linha-resumo que começa pelo número e continua em minúscula
        # ("3 sessões esperando cadastro"). Os títulos em maiúscula que este teste procurava sumiram com ela.
        # O trecho procurado é o que **não** muda com o singular e o plural, para a asserção não depender de
        # quantas pendências a semente gerou.
        for texto in ["Hoje", "Pendências", "esperando cadastro", "pendente",
                      "para escrever", "Marcos Painel"]:
            with self.subTest(texto=texto):
                self.assertContains(resposta, texto)
        self.assertNotContains(resposta, "Carla Painel")
        self.assertNotContains(resposta, "sem sessão")
