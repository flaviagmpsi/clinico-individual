"""As telas da agenda, vistas por dois psicólogos ao mesmo tempo.

`test_servicos.py` prova que as **regras** da agenda funcionam. Este arquivo prova que as **telas** usam essas
regras sem atravessar a fronteira entre psicólogos — outra coisa. Uma view que buscasse a consulta pelo id sem
passar pelo manager do dono passaria em todos os testes de serviço e vazaria aqui.

`TransactionTestCase` pelo motivo de sempre nas telas: o middleware troca o papel do banco com `SET LOCAL ROLE`,
que se prende à transação.
"""

import re
from datetime import datetime, time, timedelta

from django.db import connection, transaction
from django.db.utils import ProgrammingError
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import HorarioDisponivel, Recorrencia
from atendimentos import servicos
from atendimentos.models import Consulta, Desfecho
from contas.models import Psicologo
from core import contexto, db
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente

SENHA = "senha-de-teste-123"
SEMANAL = Recorrencia.Frequencia.SEMANAL
QUINZENAL = Recorrencia.Frequencia.QUINZENAL
TERCA = Recorrencia.DiaSemana.TERCA
QUINTA = Recorrencia.DiaSemana.QUINTA
REALIZADA = Consulta.Estado.REALIZADA
FALTOU = Consulta.Estado.FALTOU
REMARCADA = Consulta.Estado.REMARCADA
CANCELADA_CLIENTE = Consulta.Estado.CANCELADA_CLIENTE
ONLINE = Paciente.Modalidade.ONLINE
PRESENCIAL = Paciente.Modalidade.PRESENCIAL


def momento(dia, hora, minuto=0):
    return timezone.make_aware(datetime.combine(dia, time(hora, minuto)))


def proxima(dia_semana):
    amanha = timezone.localdate() + timedelta(days=1)
    return amanha + timedelta(days=(dia_semana - amanha.weekday()) % 7)


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


def frequencia_desde(caso, hoje, semanas=3):
    """Semanal que começou semanas atrás, com a última sessão ontem às 9h — gravada direto, porque o serviço só
    aceita frequência de hoje em diante, e sem passado não há pendência para a tela mostrar."""
    return Recorrencia.objects.create(
        caso=caso, frequencia=SEMANAL, dia_semana=(hoje - timedelta(days=1)).weekday(), hora=time(9), duracao=50,
        inicio=hoje - timedelta(weeks=semanas))


class BaseTelasAgenda(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.telagenda@exemplo.com", "11111111111", "939393")
        self.bruno = criar_psicologo("bruno.telagenda@exemplo.com", "22222222222", "949494")
        self.hoje = timezone.localdate()
        self.ontem = self.hoje - timedelta(days=1)
        self.terca = proxima(TERCA)
        with contexto.como(self.ana.pk):
            self.maria = Paciente(nome="Maria Agenda")
            self.caso_maria = cadastrar_paciente(self.maria)
            self.joao = Paciente(nome="João Agenda")
            self.caso_joao = cadastrar_paciente(self.joao)
            servicos.definir_frequencia(
                self.caso_maria, frequencia=SEMANAL, dia_semana=TERCA, hora=time(14), a_partir_de=self.terca)
            self.regra_joao = frequencia_desde(self.caso_joao, self.hoje)
        with contexto.como(self.bruno.pk):
            self.carla = Paciente(nome="Carla Agenda")
            self.caso_carla = cadastrar_paciente(self.carla)
            self.regra_carla = frequencia_desde(self.caso_carla, self.hoje)
            self.consulta_do_bruno = servicos.cadastrar_avulsa(
                self.caso_carla, estado=REALIZADA, inicio=momento(self.ontem, 11))

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def semana_de(self, dia):
        return f"{reverse('atendimentos:agenda')}?semana={dia - timedelta(days=dia.weekday()):%Y-%m-%d}"

    def prevista_de_ontem(self, regra):
        return reverse("atendimentos:cadastrar_prevista", args=[regra.pk, self.ontem.isoformat()])


class RotasExigemLogin(BaseTelasAgenda):
    def test_nenhuma_tela_da_agenda_abre_sem_login(self):
        for nome, args in [
            ("atendimentos:agenda", []),
            ("atendimentos:nova", []),
            ("atendimentos:cadastrar_prevista", [self.regra_carla.pk, self.ontem.isoformat()]),
            ("atendimentos:editar", [self.consulta_do_bruno.pk]),
            ("atendimentos:excluir", [self.consulta_do_bruno.pk]),
            ("atendimentos:frequencia", [self.caso_maria.pk]),
            ("atendimentos:desfecho", [self.caso_maria.pk]),
            ("atendimentos:retomar", [self.caso_maria.pk]),
            ("agenda:horarios", []),
        ]:
            with self.subTest(tela=nome):
                resposta = self.client.get(reverse(nome, args=args))
                self.assertEqual(resposta.status_code, 302)
                self.assertIn(reverse("contas:entrar"), resposta["Location"])


class NaoAtravessaAFronteira(BaseTelasAgenda):
    def test_a_agenda_mostra_so_as_proprias_sessoes(self):
        self.entrar(self.ana)
        for semana, nome in [(self.terca, "Maria Agenda"), (self.ontem, "João Agenda")]:
            with self.subTest(semana=semana):
                resposta = self.client.get(self.semana_de(semana))
                self.assertContains(resposta, nome)
                self.assertNotContains(resposta, "Carla Agenda")

    def test_consulta_prevista_e_frequencia_alheias_dao_404(self):
        self.entrar(self.ana)
        for rota in [reverse("atendimentos:editar", args=[self.consulta_do_bruno.pk]),
                     self.prevista_de_ontem(self.regra_carla),
                     reverse("atendimentos:frequencia", args=[self.caso_carla.pk])]:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 404)

    def test_post_em_consulta_alheia_nao_grava(self):
        self.entrar(self.ana)
        editar = reverse("atendimentos:editar", args=[self.consulta_do_bruno.pk])
        excluir = reverse("atendimentos:excluir", args=[self.consulta_do_bruno.pk])
        self.assertEqual(self.client.post(editar, {"estado": REMARCADA}).status_code, 404)
        self.assertEqual(self.client.post(excluir).status_code, 404)
        self.assertEqual(Consulta.objetos_todos.get(pk=self.consulta_do_bruno.pk).estado, REALIZADA)

    def test_nao_cadastra_sessao_prevista_alheia(self):
        self.entrar(self.ana)
        resposta = self.client.post(self.prevista_de_ontem(self.regra_carla),
                                    {"estado": REALIZADA, "hora": "09:00", "duracao": "50"})
        self.assertEqual(resposta.status_code, 404)
        self.assertFalse(Consulta.objetos_todos.filter(recorrencia=self.regra_carla).exists())

    def test_cadastro_avulso_so_oferece_os_proprios_atendimentos(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("atendimentos:nova"))
        self.assertContains(resposta, "Maria Agenda")
        self.assertNotContains(resposta, "Carla Agenda")

    def test_nao_encerra_nem_retoma_atendimento_alheio(self):
        with contexto.como(self.bruno.pk):
            servicos.registrar_desfecho(self.caso_carla, tipo=Desfecho.Tipo.DESISTENCIA)
        self.entrar(self.ana)
        self.assertEqual(self.client.get(reverse("atendimentos:desfecho", args=[self.caso_carla.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("atendimentos:retomar", args=[self.caso_carla.pk])).status_code, 404)
        self.assertTrue(Desfecho.objetos_todos.filter(caso_id=self.caso_carla.pk, retomado_em__isnull=True).exists())

    def test_grade_alheia_nao_aparece_nem_e_apagada(self):
        with contexto.como(self.bruno.pk):
            bloco = HorarioDisponivel.objects.create(dia_semana=0, inicio=time(8), fim=time(12))
        self.entrar(self.ana)
        self.assertNotContains(self.client.get(reverse("agenda:horarios")), "08:00–12:00")
        self.assertEqual(self.client.post(reverse("agenda:excluir", args=[bloco.pk])).status_code, 404)
        self.assertTrue(HorarioDisponivel.objetos_todos.filter(pk=bloco.pk).exists())


class CadastroPelaTela(BaseTelasAgenda):
    def test_cadastrar_a_sessao_prevista_tira_da_pendencia(self):
        self.entrar(self.ana)
        self.assertContains(self.client.get(self.semana_de(self.ontem)), "pendente")
        resposta = self.client.post(self.prevista_de_ontem(self.regra_joao),
                                    {"estado": FALTOU, "hora": "09:00", "duracao": "50"})
        self.assertEqual(resposta.status_code, 302)
        consulta = Consulta.objetos_todos.get(recorrencia=self.regra_joao, data_prevista=self.ontem)
        self.assertEqual(consulta.estado, FALTOU)
        with contexto.como(self.ana.pk):
            self.assertNotIn(self.ontem, [s.data for s in servicos.sessoes_pendentes(caso=self.caso_joao)])

    def test_prevista_ja_cadastrada_leva_para_a_correcao(self):
        with contexto.como(self.ana.pk):
            consulta = servicos.cadastrar_prevista(self.regra_joao, self.ontem, estado=REALIZADA)
        self.entrar(self.ana)
        self.assertRedirects(self.client.get(self.prevista_de_ontem(self.regra_joao)),
                             reverse("atendimentos:editar", args=[consulta.pk]), fetch_redirect_response=False)

    def test_data_que_nao_e_da_frequencia_da_404(self):
        self.entrar(self.ana)
        rota = reverse("atendimentos:cadastrar_prevista",
                       args=[self.regra_joao.pk, (self.hoje - timedelta(days=2)).isoformat()])
        self.assertEqual(self.client.get(rota).status_code, 404)

    def test_cadastrar_consulta_avulsa(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:nova"), {
            "caso": self.caso_joao.pk, "estado": REALIZADA, "data": f"{self.ontem:%Y-%m-%d}",
            "hora": "15:00", "duracao": "50"})
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(Consulta.objetos_todos.filter(caso=self.caso_joao, recorrencia__isnull=True).exists())

    def test_cadastro_no_futuro_volta_explicando(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:nova"), {
            "caso": self.caso_joao.pk, "estado": REALIZADA, "data": f"{self.terca:%Y-%m-%d}",
            "hora": "10:00", "duracao": "50"})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "já aconteceu")
        self.assertFalse(Consulta.objetos_todos.filter(caso=self.caso_joao).exists())

    def test_horario_ocupado_volta_explicando(self):
        with contexto.como(self.ana.pk):
            servicos.cadastrar_avulsa(self.caso_maria, estado=REALIZADA, inicio=momento(self.ontem, 15))
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:nova"), {
            "caso": self.caso_joao.pk, "estado": REALIZADA, "data": f"{self.ontem:%Y-%m-%d}",
            "hora": "15:15", "duracao": "50"})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Horário ocupado")

    def test_corrigir_a_situacao(self):
        with contexto.como(self.ana.pk):
            consulta = servicos.cadastrar_avulsa(self.caso_joao, estado=REALIZADA, inicio=momento(self.ontem, 16))
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:editar", args=[consulta.pk]), {"estado": REMARCADA})
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Consulta.objetos_todos.get(pk=consulta.pk).estado, REMARCADA)

    def test_excluir_o_cadastro_devolve_a_pendencia(self):
        with contexto.como(self.ana.pk):
            consulta = servicos.cadastrar_prevista(self.regra_joao, self.ontem, estado=REALIZADA)
        self.entrar(self.ana)
        self.assertEqual(self.client.post(reverse("atendimentos:excluir", args=[consulta.pk])).status_code, 302)
        self.assertFalse(Consulta.objetos_todos.filter(pk=consulta.pk).exists())
        with contexto.como(self.ana.pk):
            self.assertIn(self.ontem, [s.data for s in servicos.sessoes_pendentes(caso=self.caso_joao)])

    def test_definir_frequencia_aparece_na_agenda(self):
        self.entrar(self.ana)
        quinta = proxima(QUINTA)
        resposta = self.client.post(reverse("atendimentos:frequencia", args=[self.caso_joao.pk]), {
            "frequencia": QUINZENAL, "dia_semana": str(QUINTA), "hora": "10:00", "duracao": "",
            "a_partir_de": f"{quinta:%Y-%m-%d}"})
        self.assertRedirects(resposta, reverse("pacientes:detalhe", args=[self.joao.pk]), fetch_redirect_response=False)
        self.assertEqual(Recorrencia.objetos_todos.get(caso=self.caso_joao, fim__isnull=True).frequencia, QUINZENAL)
        self.assertContains(self.client.get(self.semana_de(quinta)), "João Agenda")

    def test_painel_mostra_o_que_ficou_para_tras(self):
        """ADR-069: a pendência de cadastro vem antes do dia, no painel."""
        self.entrar(self.ana)
        resposta = self.client.get(reverse("painel"))
        self.assertContains(resposta, "esperando cadastro")
        self.assertContains(resposta, "João Agenda")

    def test_a_ficha_do_paciente_mostra_a_frequencia(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("pacientes:detalhe", args=[self.maria.pk]))
        self.assertContains(resposta, "Semanal")
        self.assertContains(resposta, reverse("atendimentos:frequencia", args=[self.caso_maria.pk]))


class DesfechoPelaTela(BaseTelasAgenda):
    def test_encerrar_tira_da_lista_de_ativos_e_oferece_retomar(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:desfecho", args=[self.caso_maria.pk]), {
            "tipo": "DESISTENCIA", "iniciativa": "", "data": f"{self.hoje:%Y-%m-%d}", "motivo": "Parou de responder."})
        self.assertRedirects(resposta, reverse("pacientes:detalhe", args=[self.maria.pk]), fetch_redirect_response=False)
        self.assertEqual(Desfecho.objetos_todos.get(caso=self.caso_maria).iniciativa, Desfecho.Iniciativa.PACIENTE)

        self.assertContains(self.client.get(reverse("pacientes:detalhe", args=[self.maria.pk])), "Retomar atendimento")
        self.assertNotContains(self.client.get(reverse("pacientes:lista")), "Maria Agenda")
        self.assertContains(self.client.get(reverse("pacientes:lista"), {"situacao": "encerrados"}), "Maria Agenda")

    def test_a_tela_avisa_o_que_muda_antes_de_gravar(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("atendimentos:desfecho", args=[self.caso_joao.pk]))
        self.assertContains(resposta, "termina hoje")
        self.assertContains(resposta, "pendentes de cadastro")

    def test_alta_sem_iniciativa_volta_explicando(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:desfecho", args=[self.caso_maria.pk]), {
            "tipo": "ALTA", "data": f"{self.hoje:%Y-%m-%d}"})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Informe de quem partiu")
        self.assertFalse(Desfecho.objetos_todos.filter(caso=self.caso_maria).exists())

    def test_retomar_leva_a_definir_a_frequencia(self):
        with contexto.como(self.ana.pk):
            servicos.registrar_desfecho(self.caso_maria, tipo=Desfecho.Tipo.DESISTENCIA)
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:retomar", args=[self.caso_maria.pk]))
        self.assertRedirects(resposta, reverse("atendimentos:frequencia", args=[self.caso_maria.pk]),
                             fetch_redirect_response=False)
        self.assertIsNotNone(Desfecho.objetos_todos.get(caso=self.caso_maria).retomado_em)


class GradePelaTela(BaseTelasAgenda):
    def test_adicionar_horario_mostra_quem_ocupa_e_o_que_sobra(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("agenda:horarios"),
                                    {"dia_semana": str(TERCA), "inicio": "13:00", "fim": "18:00"})
        self.assertRedirects(resposta, reverse("agenda:horarios"), fetch_redirect_response=False)
        mapa = self.client.get(reverse("agenda:horarios"))
        self.assertContains(mapa, "Maria Agenda")
        self.assertContains(mapa, "livre")

    def test_horario_sobreposto_volta_explicando(self):
        with contexto.como(self.ana.pk):
            HorarioDisponivel.objects.create(dia_semana=TERCA, inicio=time(13), fim=time(18))
        self.entrar(self.ana)
        resposta = self.client.post(reverse("agenda:horarios"),
                                    {"dia_semana": str(TERCA), "inicio": "17:00", "fim": "20:00"})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "sobrepõe")

    def test_consulta_fora_da_grade_grava_e_avisa(self):
        """ADR-056: aviso, nunca bloqueio."""
        with contexto.como(self.ana.pk):
            HorarioDisponivel.objects.create(dia_semana=TERCA, inicio=time(13), fim=time(18))
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:nova"), {
            "caso": self.caso_joao.pk, "estado": REALIZADA, "data": f"{self.ontem:%Y-%m-%d}",
            "hora": "20:00", "duracao": "50"}, follow=True)
        self.assertContains(resposta, "fora da sua grade")
        self.assertTrue(Consulta.objetos_todos.filter(caso=self.caso_joao).exists())

    def test_consulta_dentro_da_grade_nao_avisa(self):
        with contexto.como(self.ana.pk):
            HorarioDisponivel.objects.create(dia_semana=self.ontem.weekday(), inicio=time(8), fim=time(12))
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:nova"), {
            "caso": self.caso_joao.pk, "estado": REALIZADA, "data": f"{self.ontem:%Y-%m-%d}",
            "hora": "10:00", "duracao": "50"}, follow=True)
        self.assertNotContains(resposta, "fora da sua grade")



class FiltroDaAgenda(BaseTelasAgenda):
    """ADR-065: ver o período que se quer, filtrar por situação e saber quanto é online."""

    def setUp(self):
        super().setUp()
        # Três dias atrás: nenhuma frequência prevê nada nesse dia, então só aparece o que este teste cadastrar.
        self.dia = self.hoje - timedelta(days=3)
        with contexto.como(self.ana.pk):
            servicos.cadastrar_avulsa(self.caso_joao, estado=REALIZADA, modalidade=ONLINE,
                                      inicio=momento(self.dia, 8))
            servicos.cadastrar_avulsa(self.caso_maria, estado=FALTOU, modalidade=PRESENCIAL,
                                      inicio=momento(self.dia, 12))

    def periodo(self, de, ate, situacao=""):
        return f"{reverse('atendimentos:agenda')}?de={de:%Y-%m-%d}&ate={ate:%Y-%m-%d}&situacao={situacao}"

    def total(self, resposta):
        """O contador da tela. Lido do HTML porque o número vem dentro do `<strong>`, e não solto no texto."""
        return int(re.search(r'text-body">(\d+)</strong> sess', resposta.content.decode()).group(1))

    def test_mostra_o_periodo_pedido_com_a_proporcao_de_online(self):
        self.entrar(self.ana)
        resposta = self.client.get(self.periodo(self.dia, self.dia))
        self.assertEqual(self.total(resposta), 2)
        self.assertContains(resposta, "1 online (50%)")
        self.assertContains(resposta, "Maria Agenda")

    def test_dia_vizinho_nao_traz_as_sessoes_do_periodo(self):
        self.entrar(self.ana)
        vespera = self.dia - timedelta(days=1)
        self.assertEqual(self.total(self.client.get(self.periodo(vespera, vespera))), 0)

    def test_filtra_por_situacao(self):
        self.entrar(self.ana)
        resposta = self.client.get(self.periodo(self.dia, self.dia, situacao=FALTOU))
        self.assertEqual(self.total(resposta), 1)
        self.assertContains(resposta, "Maria Agenda")

    def test_previstas_e_cadastradas_nao_se_misturam_no_filtro(self):
        self.entrar(self.ana)
        self.assertEqual(self.total(self.client.get(self.periodo(self.dia, self.dia, situacao="PREVISTA"))), 0)
        self.assertContains(self.client.get(self.periodo(self.terca, self.terca, situacao="PREVISTA")),
                            "Maria Agenda")

    def test_periodo_invertido_cai_na_semana_de_hoje(self):
        self.entrar(self.ana)
        resposta = self.client.get(self.periodo(self.dia, self.dia - timedelta(days=5)))
        self.assertContains(resposta, f"{self.hoje - timedelta(days=self.hoje.weekday()):%d/%m/%Y}")


class CobrancaEModalidadePelaTela(BaseTelasAgenda):
    def test_cliente_cancelou_sem_marcar_cobrar_nao_cobra_e_a_modalidade_vai_junto(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:nova"), {
            "caso": self.caso_joao.pk, "estado": CANCELADA_CLIENTE, "data": f"{self.ontem:%Y-%m-%d}",
            "hora": "17:00", "duracao": "50", "modalidade": ONLINE})
        self.assertEqual(resposta.status_code, 302)
        consulta = Consulta.objetos_todos.get(caso=self.caso_joao)
        self.assertEqual((consulta.cobrada, consulta.modalidade), (False, ONLINE))

    def test_corrigir_para_cobrar_o_cancelamento(self):
        with contexto.como(self.ana.pk):
            consulta = servicos.cadastrar_avulsa(self.caso_joao, estado=CANCELADA_CLIENTE, cobrada=False,
                                                 inicio=momento(self.ontem, 18))
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:editar", args=[consulta.pk]),
                                    {"estado": CANCELADA_CLIENTE, "cobrar": "on"})
        self.assertEqual(resposta.status_code, 302)
        consulta.refresh_from_db()
        self.assertEqual((consulta.cobrada, consulta.modalidade), (True, PRESENCIAL))

class ValorSoOndeFazSentido(BaseTelasAgenda):
    """ADR-093: o campo "valor desta sessão" só aparece na avulsa. Na que já estava combinada, a tela diz o que acontece."""

    def test_avulsa_sempre_mostra_o_valor(self):
        self.entrar(self.ana)
        self.assertContains(self.client.get(reverse("atendimentos:nova")), "Valor desta sessão")

    def test_sessao_da_frequencia_de_quem_paga_mensalidade_nao_mostra(self):
        with contexto.como(self.ana.pk):
            from decimal import Decimal
            from pacientes.models import CondicaoCobranca
            mensalista = cadastrar_paciente(Paciente(nome="Mensalista Agenda"), valor=Decimal("700"),
                                            modalidade=CondicaoCobranca.Modalidade.MENSAL, dia_vencimento=10,
                                            vigente_desde=self.hoje - timedelta(days=60))
            regra = frequencia_desde(mensalista, self.hoje)
        self.entrar(self.ana)
        resposta = self.client.get(self.prevista_de_ontem(regra))
        self.assertNotContains(resposta, "Valor desta sessão")
        self.assertContains(resposta, "já está na mensalidade do mês e não gera cobrança nova")
        # E cadastrar sem o campo continua funcionando.
        resposta = self.client.post(self.prevista_de_ontem(regra), {"estado": REALIZADA, "hora": "09:00", "duracao": "50"})
        self.assertEqual(resposta.status_code, 302)

    def test_sessao_da_frequencia_de_quem_paga_por_sessao_nao_pergunta_e_diz_que_vira_cobranca(self):
        with contexto.como(self.ana.pk):
            from decimal import Decimal
            por_sessao = cadastrar_paciente(Paciente(nome="Por Sessão Agenda"), valor=Decimal("200"),
                                            vigente_desde=self.hoje - timedelta(days=60))
            regra = frequencia_desde(por_sessao, self.hoje)
        self.entrar(self.ana)
        resposta = self.client.get(self.prevista_de_ontem(regra))
        self.assertNotContains(resposta, "Valor desta sessão")
        self.assertContains(resposta, "R$ 200,00 por sessão")
        self.assertContains(resposta, "entra no financeiro como pagamento pendente")
        # Cadastrada, a cobrança nasce sozinha, pelo valor combinado — sem ninguém digitar valor.
        self.assertEqual(self.client.post(self.prevista_de_ontem(regra),
                                          {"estado": REALIZADA, "hora": "09:00", "duracao": "50"}).status_code, 302)
        with contexto.como(self.ana.pk):
            from financeiro import servicos as financeiro
            consulta = Consulta.objects.get(recorrencia=regra)
            cobranca = financeiro.sessao(consulta)
        self.assertIsNone(consulta.valor)
        self.assertEqual(cobranca.devido, Decimal("200"))

    def test_sem_valor_combinado_a_tela_avisa_que_nao_gera_cobranca(self):
        self.entrar(self.ana)
        resposta = self.client.get(self.prevista_de_ontem(self.regra_joao))
        self.assertNotContains(resposta, "Valor desta sessão")
        self.assertContains(resposta, "Ainda não há valor combinado")


class RemarcacaoPelaTela(BaseTelasAgenda):
    """ADR-068: marcar "remarcada" pergunta para quando, e a data nova vira sessão a cadastrar."""

    def editar(self, consulta):
        return reverse("atendimentos:editar", args=[consulta.pk])

    def remarcar_pela_tela(self, consulta, dia, hora="15:00"):
        return self.client.post(self.editar(consulta), {
            "estado": REMARCADA, "nova_data": f"{dia:%Y-%m-%d}", "nova_hora": hora})

    def consulta_de_ontem(self):
        with contexto.como(self.ana.pk):
            return servicos.cadastrar_avulsa(self.caso_joao, estado=REALIZADA, inicio=momento(self.ontem, 16))

    def test_remarcar_guarda_a_data_nova_e_a_agenda_espera_a_sessao(self):
        consulta = self.consulta_de_ontem()
        self.entrar(self.ana)
        destino = self.hoje + timedelta(days=1)
        self.assertEqual(self.remarcar_pela_tela(consulta, destino).status_code, 302)
        consulta.refresh_from_db()
        self.assertEqual(timezone.localtime(consulta.remarcada_para).date(), destino)

        resposta = self.client.get(f"{reverse('atendimentos:agenda')}?de={destino:%Y-%m-%d}&ate={destino:%Y-%m-%d}")
        self.assertContains(resposta, "remarcada de")
        self.assertContains(resposta, reverse("atendimentos:cadastrar_remarcada", args=[consulta.pk]))

    def test_dia_sem_horario_volta_explicando(self):
        consulta = self.consulta_de_ontem()
        self.entrar(self.ana)
        resposta = self.client.post(self.editar(consulta), {
            "estado": REMARCADA, "nova_data": f"{self.hoje + timedelta(days=1):%Y-%m-%d}", "nova_hora": ""})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Informe o dia e o horário")
        consulta.refresh_from_db()
        self.assertIsNone(consulta.remarcada_para)

    def test_cadastrar_a_sessao_remarcada_ja_vem_preenchida(self):
        consulta = self.consulta_de_ontem()
        self.entrar(self.ana)
        self.remarcar_pela_tela(consulta, self.ontem, hora="18:00")  # destino no passado: cadastrável hoje
        rota = reverse("atendimentos:cadastrar_remarcada", args=[consulta.pk])
        self.assertContains(self.client.get(rota), "Sessão remarcada de")

        resposta = self.client.post(rota, {
            "caso": self.caso_joao.pk, "estado": REALIZADA, "data": f"{self.ontem:%Y-%m-%d}",
            "hora": "18:00", "duracao": "50"})
        self.assertEqual(resposta.status_code, 302)
        nova = Consulta.objetos_todos.get(caso=self.caso_joao, inicio=momento(self.ontem, 18))
        self.assertEqual(nova.estado, REALIZADA)

    def test_remarcada_de_outro_psicologo_da_404(self):
        with contexto.como(self.bruno.pk):
            servicos.alterar_situacao(self.consulta_do_bruno, REMARCADA,
                                      remarcada_para=momento(self.hoje + timedelta(days=1), 11))
        self.entrar(self.ana)
        rota = reverse("atendimentos:cadastrar_remarcada", args=[self.consulta_do_bruno.pk])
        self.assertEqual(self.client.get(rota).status_code, 404)


class CalendarioPelaTela(BaseTelasAgenda):
    """ADR-073: a agenda no desenho da planilha — colunas por dia, cartões por horário, livres onde há grade."""

    def grade(self, dia_semana, de, ate):
        with contexto.como(self.ana.pk):
            return HorarioDisponivel.objects.create(dia_semana=dia_semana, inicio=time(de), fim=time(ate))

    def rota(self, visao, data, situacao=""):
        return f"{reverse('atendimentos:agenda')}?visao={visao}&data={data:%Y-%m-%d}&situacao={situacao}"

    def test_semana_e_o_padrao_com_uma_coluna_por_dia(self):
        self.entrar(self.ana)
        resposta = self.client.get(self.rota("semana", self.terca))
        for dia in ["Segunda-feira", "Terça-feira", "Sexta-feira"]:
            self.assertContains(resposta, dia)
        self.assertContains(resposta, "Maria Agenda - 14H")

    def test_livre_so_onde_ha_horario_cadastrado_e_nao_em_cima_de_sessao(self):
        """Grade de terça 13h–16h com a Maria às 14h: livre às 13h e às 15h, e em nenhum outro dia."""
        self.grade(TERCA, 13, 16)
        self.entrar(self.ana)
        corpo = self.client.get(self.rota("semana", self.terca)).content.decode()
        self.assertIn("LIVRE - 13H", corpo)
        self.assertIn("LIVRE - 15H", corpo)
        self.assertNotIn("LIVRE - 14H", corpo)
        self.assertEqual(corpo.count("LIVRE - "), 2)

    def test_sem_grade_nao_ha_livre_nenhum(self):
        self.entrar(self.ana)
        self.assertNotContains(self.client.get(self.rota("semana", self.terca)), "LIVRE - ")

    def test_fim_de_semana_so_aparece_com_conteudo(self):
        """Procura o **cabeçalho da coluna** ("Sábado · 26/09"), e não a palavra solta: o gráfico de dias da semana
        vive na mesma tela desde a ADR-103 e nomeia todos os dias.

        A base cria uma frequência semanal no dia de hoje; rodando num sábado ou domingo, ela encheria a coluna e o
        resultado dependeria do dia em que o teste roda. Encerrá-la deixa o fim de semana limpo.
        """
        with contexto.como(self.ana.pk):
            servicos.definir_frequencia(self.caso_joao, frequencia=servicos.AVULSO)
        self.entrar(self.ana)
        coluna = "Sábado ·"
        self.assertNotContains(self.client.get(self.rota("semana", self.terca)), coluna)
        self.grade(5, 9, 11)  # sábado
        self.assertContains(self.client.get(self.rota("semana", self.terca)), coluna)

    def test_visao_do_dia_e_do_mes(self):
        self.entrar(self.ana)
        dia = self.client.get(self.rota("dia", self.terca))
        self.assertContains(dia, "Maria Agenda - 14H")
        self.assertNotContains(dia, "Segunda-feira")
        mes = self.client.get(self.rota("mes", self.terca))
        self.assertContains(mes, f"{self.terca:%Y}")
        self.assertContains(mes, "Maria Agenda - 14H")

    def test_filtro_de_situacao_esconde_livres_e_previstas(self):
        self.grade(TERCA, 13, 16)
        self.entrar(self.ana)
        corpo = self.client.get(self.rota("semana", self.terca, situacao=REALIZADA)).content.decode()
        self.assertNotIn("LIVRE - ", corpo)
        self.assertNotIn("Maria Agenda - 14H", corpo)  # prevista, não cadastrada

    def test_a_grade_de_outro_psicologo_nao_vira_livre_aqui(self):
        with contexto.como(self.bruno.pk):
            HorarioDisponivel.objects.create(dia_semana=TERCA, inicio=time(8), fim=time(10))
        self.entrar(self.ana)
        self.assertNotContains(self.client.get(self.rota("semana", self.terca)), "LIVRE - ")


class RLSNaAgenda(TransactionTestCase):
    """As tabelas da agenda sob a terceira camada da ADR-001."""

    TABELAS = ["agenda_recorrencia", "agenda_horariodisponivel", "atendimentos_consulta", "atendimentos_desfecho"]

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("RLS exige PostgreSQL.")
        self.ana = criar_psicologo("ana.rlsagenda@exemplo.com", "33333333333", "959595")
        self.bruno = criar_psicologo("bruno.rlsagenda@exemplo.com", "44444444444", "969696")
        hoje = timezone.localdate()
        for psicologo, nome in [(self.ana, "Da Ana"), (self.bruno, "Do Bruno")]:
            with contexto.como(psicologo.pk):
                regra = frequencia_desde(cadastrar_paciente(Paciente(nome=nome)), hoje)
                servicos.cadastrar_prevista(regra, hoje - timedelta(days=1), estado=REALIZADA)
                HorarioDisponivel.objects.create(dia_semana=TERCA, inicio=time(13), fim=time(18))
                servicos.registrar_desfecho(cadastrar_paciente(Paciente(nome=f"{nome}, encerrado")),
                                            tipo=Desfecho.Tipo.DESISTENCIA)

    def test_sql_cru_so_devolve_o_proprio_dono(self):
        for tabela in self.TABELAS:
            with self.subTest(tabela=tabela):
                with transaction.atomic():
                    db.assumir_papel_da_aplicacao()
                    db.aplicar_escopo(self.ana.pk)
                    with connection.cursor() as cursor:
                        cursor.execute(f"SELECT DISTINCT psicologo_id FROM {tabela}")
                        donos = {linha[0] for linha in cursor.fetchall()}
                self.assertEqual(donos, {self.ana.pk})

    def test_papel_anonimo_nao_le_a_agenda(self):
        for tabela in self.TABELAS:
            with self.subTest(tabela=tabela):
                with self.assertRaises(ProgrammingError):
                    with transaction.atomic():
                        db.assumir_papel_da_web()
                        with connection.cursor() as cursor:
                            cursor.execute(f"SELECT 1 FROM {tabela}")
