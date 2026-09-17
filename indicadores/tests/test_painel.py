"""O painel (ADR-061, ADR-069): a agenda de hoje, o que ficou para trás e os números do mês.

- `AgendaDeHoje` — as sessões do dia, cadastradas ou esperando cadastro, com os avisos que mudam o que fazer.
- `OQueFicouParaTras` — sessão de dia anterior sem cadastro aparece antes do dia; a de hoje não se repete lá.
- `SemSessaoHaTempoDemais` — "dias sem sessão" virou alerta, e só quando o atendimento passa do próprio ritmo.
- `ResumoDoMes` — sessões feitas e que faltam, recebido e a receber, ativos e quantos precisam de atenção.
- `PainelPelaTela` — a tela abre logada e não mostra atendimento de outro psicólogo.

Calculado com `AGORA` fixo em 20/09/2026, 12h — um domingo. Setembro de 2026, conferido: as terças são 1, 8,
15, 22 e 29. As consultas de 20/09 são cadastradas passando `agora=AGORA`, porque o serviço só aceita o que já
aconteceu (ADR-060) e esse dia ainda não chegou no relógio de quem roda o teste.

O Marcos exercita os motivos de atenção de uma vez: falta sem aviso em 08/09 sem pagamento, a sessão de 15/09
sem cadastro e 19 dias desde a última sessão realizada (01/09), numa frequência semanal.
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
QUINZENAL = Recorrencia.Frequencia.QUINZENAL
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


def marcos_com_tres_motivos(nome="Marcos"):
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
            cls.caso_marcos = marcos_com_tres_motivos()
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

    def test_sessao_ainda_nao_cadastrada_aparece_como_a_cadastrar(self):
        """Prevista para as 14h de hoje, com o painel calculado ao meio-dia: ainda não passou."""
        with contexto.como(self.ana.pk):
            Recorrencia.objects.create(caso=self.caso_juliana, frequencia=SEMANAL, dia_semana=6, hora=time(14),
                                       duracao=50, inicio=setembro(13))
        [item] = self.painel().hoje_itens
        self.assertEqual((item.situacao, item.cadastrada), ("prevista", False))

        with contexto.como(self.ana.pk):
            Recorrencia.objects.filter(caso=self.caso_juliana).update(hora=time(9))
        [item] = self.painel().hoje_itens
        self.assertEqual(item.situacao, "a cadastrar")

    def test_sessao_remarcada_para_hoje_espera_cadastro(self):
        with contexto.como(self.ana.pk):
            agenda.cadastrar_avulsa(self.caso_marcos, estado=REMARCADA, inicio=momento(setembro(14)),
                                    remarcada_para=momento(setembro(20), 15))
        [item] = self.painel().hoje_itens
        self.assertEqual(timezone.localtime(item.inicio).hour, 15)
        self.assertIsNotNone(item.espera.origem)

    def test_avisos_de_pagamento_em_aberto_e_prontuario_por_escrever(self):
        with contexto.como(self.ana.pk):
            self.hoje(self.caso_marcos)
        [item] = self.painel().hoje_itens
        self.assertTrue(item.pagamento_em_aberto)   # a falta de 08/09 venceu e ninguém pagou
        self.assertTrue(item.prontuario_pendente)   # sessão realizada hoje, prontuário ainda não escrito

        with contexto.como(self.ana.pk):
            prontuarios.confirmar(item.consulta, self.caso_marcos.pacientes.first(), texto="Registro da sessão.")
        [item] = self.painel().hoje_itens
        self.assertFalse(item.prontuario_pendente)

    def test_dia_sem_sessao_nao_inventa_linha(self):
        self.assertEqual(self.painel().hoje_itens, [])


class OQueFicouParaTras(BasePainel):
    def test_sessao_de_dia_anterior_sem_cadastro_aparece(self):
        """A de 15/09 do Marcos passou e ninguém cadastrou."""
        atrasadas = self.painel().atrasadas
        self.assertEqual([timezone.localtime(s.inicio).date() for s in atrasadas], [setembro(15)])

    def test_a_pendencia_de_hoje_nao_se_repete_fora_do_dia(self):
        with contexto.como(self.ana.pk):
            Recorrencia.objects.create(caso=self.caso_juliana, frequencia=SEMANAL, dia_semana=6, hora=time(9),
                                       duracao=50, inicio=setembro(13))
        painel = self.painel()
        self.assertIn("a cadastrar", [item.situacao for item in painel.hoje_itens])
        self.assertNotIn(setembro(20), [timezone.localtime(s.inicio).date() for s in painel.atrasadas])


class SemSessaoHaTempoDemais(BasePainel):
    def test_quinzenal_tolera_21_dias_e_semanal_nao(self):
        """Última sessão realizada em 30/08: 21 dias até 20/09. As frequências só começam a prever em 25/09."""
        with contexto.como(self.ana.pk):
            casos = {}
            for frequencia, hora in [(QUINZENAL, 9), (SEMANAL, 11)]:
                caso = cadastrar_paciente(Paciente(nome=frequencia))
                agenda.cadastrar_avulsa(caso, estado=REALIZADA, inicio=momento(date(2026, 8, 30), hora))
                Recorrencia.objects.create(caso=caso, frequencia=frequencia, dia_semana=4, hora=time(hora),
                                           duracao=50, inicio=setembro(19))
                casos[frequencia] = caso
        alertas = {alerta.caso.pk: alerta.dias for alerta in self.painel().alertas}
        self.assertNotIn(casos[QUINZENAL].pk, alertas)
        self.assertEqual(alertas[casos[SEMANAL].pk], 21)

    def test_o_marcos_esta_ha_19_dias_sem_sessao(self):
        [alerta] = [a for a in self.painel().alertas if a.caso.pk == self.caso_marcos.pk]
        self.assertEqual((alerta.dias, alerta.frequencia), (19, "Semanal"))

    def test_atendimento_encerrado_sai_do_painel(self):
        with contexto.como(self.ana.pk):
            agenda.registrar_desfecho(self.caso_juliana, tipo="DESISTENCIA", data=setembro(14))
        painel = self.painel()
        self.assertNotIn(self.caso_juliana.pk, [alerta.caso.pk for alerta in painel.alertas])
        self.assertEqual(painel.resumo.pacientes_ativos, 1)

    def test_atendimento_de_outro_psicologo_nao_aparece(self):
        painel = self.painel()
        self.assertNotIn(self.caso_carla.pk, [alerta.caso.pk for alerta in painel.alertas])
        self.assertNotIn(self.caso_carla.pk, [item.caso.pk for item in painel.hoje_itens])


class ResumoDoMes(BasePainel):
    def test_sessoes_feitas_e_as_que_faltam(self):
        """Feita: 01/09. Faltam: 22 e 29/09. A de 15/09 é pendente de cadastro, não previsão."""
        resumo = self.painel().resumo
        self.assertEqual((resumo.sessoes_feitas, resumo.sessoes_faltam), (1, 2))

    def test_recebido_e_a_receber(self):
        """Recebido: a sessão de 01/09. A receber: falta cobrada (200) + mensalidade (700) + duas previstas (400)."""
        resumo = self.painel().resumo
        self.assertEqual((resumo.recebido, resumo.a_receber), (Decimal("200"), Decimal("1300")))

    def test_pacientes_ativos_e_quantos_precisam_de_atencao(self):
        resumo = self.painel().resumo
        self.assertEqual((resumo.pacientes_ativos, resumo.precisam_de_atencao), (2, 2))

    def test_mensalidade_paga_tira_o_atendimento_da_conta(self):
        with contexto.como(self.ana.pk):
            financeiro.registrar_pagamento_mensalidade(
                self.caso_juliana, ano=2026, mes=9, valor=Decimal("700"), data=setembro(5), forma=PIX)
        self.assertEqual(self.painel().resumo.precisam_de_atencao, 1)


class PainelPelaTela(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.telapainel@exemplo.com", "33333333333", "595959")
        self.bruno = criar_psicologo("bruno.telapainel@exemplo.com", "44444444444", "606060")
        with contexto.como(self.ana.pk):
            marcos_com_tres_motivos("Marcos Painel")
        with contexto.como(self.bruno.pk):
            cadastrar_paciente(Paciente(nome="Carla Painel"))

    def test_exige_login(self):
        resposta = self.client.get(reverse("painel"))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("contas:entrar"), resposta["Location"])

    def test_mostra_o_dia_as_pendencias_e_nao_o_atendimento_alheio(self):
        self.assertTrue(self.client.login(username=self.ana.email, password=SENHA))
        resposta = self.client.get(reverse("painel"))
        for texto in ["Hoje", "esperando cadastro", "Sem sessão há tempo demais", "Pagamentos pendentes",
                      "Prontuários para escrever", "Marcos Painel"]:
            with self.subTest(texto=texto):
                self.assertContains(resposta, texto)
        self.assertNotContains(resposta, "Carla Painel")
