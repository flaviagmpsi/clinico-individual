"""As telas da agenda, vistas por dois psicólogos ao mesmo tempo.

`test_servicos.py` prova que as **regras** da agenda funcionam. Este arquivo prova que as **telas** usam
essas regras sem atravessar a fronteira entre psicólogos — outra coisa. Uma view que buscasse a consulta
pelo id sem passar pelo manager do dono passaria em todos os testes de serviço e vazaria aqui.

`TransactionTestCase` pelo motivo de sempre nas telas: o middleware troca o papel do banco com
`SET LOCAL ROLE`, que se prende à transação.
"""

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


def momento(dia, hora, minuto=0):
    return timezone.make_aware(datetime.combine(dia, time(hora, minuto)))


def proxima(dia_semana):
    amanha = timezone.localdate() + timedelta(days=1)
    return amanha + timedelta(days=(dia_semana - amanha.weekday()) % 7)


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


class BaseTelasAgenda(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.telagenda@exemplo.com", "11111111111", "939393")
        self.bruno = criar_psicologo("bruno.telagenda@exemplo.com", "22222222222", "949494")
        self.terca = proxima(TERCA)
        self.hoje = timezone.localdate()
        with contexto.como(self.ana.pk):
            self.maria = Paciente(nome="Maria Agenda")
            self.caso_maria = cadastrar_paciente(self.maria)
            self.joao = Paciente(nome="João Agenda")
            self.caso_joao = cadastrar_paciente(self.joao)
            servicos.definir_frequencia(
                self.caso_maria, frequencia=SEMANAL, dia_semana=TERCA, hora=time(14), a_partir_de=self.terca)
        with contexto.como(self.bruno.pk):
            self.carla = Paciente(nome="Carla Agenda")
            self.caso_carla = cadastrar_paciente(self.carla)
            self.consulta_do_bruno = servicos.marcar_avulsa(self.caso_carla, inicio=momento(self.terca, 9))

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def semana_da_terca(self):
        segunda = self.terca - timedelta(days=self.terca.weekday())
        return f"{reverse('atendimentos:agenda')}?semana={segunda:%Y-%m-%d}"

    def consulta_passada(self, caso=None):
        with contexto.como(self.ana.pk):
            return servicos.marcar_avulsa(caso or self.caso_joao, inicio=momento(self.hoje - timedelta(days=2), 9))


class RotasExigemLogin(BaseTelasAgenda):
    def test_nenhuma_tela_da_agenda_abre_sem_login(self):
        for nome, args in [
            ("atendimentos:agenda", []),
            ("atendimentos:nova", []),
            ("atendimentos:registrar", [self.consulta_do_bruno.pk]),
            ("atendimentos:remarcar", [self.consulta_do_bruno.pk]),
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
    def test_a_agenda_mostra_so_as_proprias_consultas(self):
        self.entrar(self.ana)
        resposta = self.client.get(self.semana_da_terca())
        self.assertContains(resposta, "Maria Agenda")
        self.assertNotContains(resposta, "Carla Agenda")

    def test_consulta_e_frequencia_alheias_dao_404(self):
        self.entrar(self.ana)
        for rota in [reverse("atendimentos:registrar", args=[self.consulta_do_bruno.pk]),
                     reverse("atendimentos:remarcar", args=[self.consulta_do_bruno.pk]),
                     reverse("atendimentos:frequencia", args=[self.caso_carla.pk])]:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 404)

    def test_post_em_consulta_alheia_nao_grava(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:registrar", args=[self.consulta_do_bruno.pk]),
                                    {"estado": "CANCELADA", "cobranca": "padrao"})
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(Consulta.objetos_todos.get(pk=self.consulta_do_bruno.pk).estado, Consulta.Estado.AGENDADA)

    def test_consulta_avulsa_so_oferece_os_proprios_atendimentos(self):
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


class FluxosPelaTela(BaseTelasAgenda):
    def test_marcar_consulta_avulsa(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:nova"), {
            "caso": self.caso_joao.pk, "data": f"{self.terca:%Y-%m-%d}", "hora": "10:00", "duracao": "50"})
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(Consulta.objetos_todos.filter(caso=self.caso_joao).exists())

    def test_horario_ocupado_volta_explicando(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:nova"), {
            "caso": self.caso_joao.pk, "data": f"{self.terca:%Y-%m-%d}", "hora": "14:15", "duracao": "50"})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Horário ocupado")
        self.assertFalse(Consulta.objetos_todos.filter(caso=self.caso_joao).exists())

    def test_definir_frequencia_gera_a_agenda(self):
        self.entrar(self.ana)
        quinta = proxima(QUINTA)
        resposta = self.client.post(reverse("atendimentos:frequencia", args=[self.caso_joao.pk]), {
            "frequencia": QUINZENAL, "dia_semana": str(QUINTA), "hora": "10:00", "duracao": "",
            "a_partir_de": f"{quinta:%Y-%m-%d}"})
        self.assertRedirects(resposta, reverse("pacientes:detalhe", args=[self.joao.pk]), fetch_redirect_response=False)
        regra = Recorrencia.objetos_todos.get(caso=self.caso_joao)
        self.assertEqual(regra.frequencia, QUINZENAL)
        self.assertTrue(Consulta.objetos_todos.filter(recorrencia=regra, inicio=momento(quinta, 10)).exists())

    def test_registrar_o_que_aconteceu(self):
        consulta = self.consulta_passada()
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:registrar", args=[consulta.pk]),
                                    {"estado": "REALIZADA", "cobranca": "padrao"})
        self.assertEqual(resposta.status_code, 302)
        consulta = Consulta.objetos_todos.get(pk=consulta.pk)
        self.assertEqual(consulta.estado, Consulta.Estado.REALIZADA)
        self.assertTrue(consulta.contabilizada)

    def test_remarcar_marca_a_sessao_como_remarcada(self):
        sessao = Consulta.objetos_todos.get(recorrencia__caso=self.caso_maria, data_prevista=self.terca)
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:remarcar", args=[sessao.pk]), {
            "data": f"{self.terca + timedelta(days=1):%Y-%m-%d}", "hora": "14:00", "duracao": "50"})
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(Consulta.objetos_todos.get(pk=sessao.pk).remarcada)

    def test_painel_mostra_a_consulta_sem_registro(self):
        self.consulta_passada()
        self.entrar(self.ana)
        self.assertContains(self.client.get(reverse("painel")), "Consultas passadas sem registro")

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

    def test_a_tela_avisa_o_que_vai_sumir_antes_de_gravar(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("atendimentos:desfecho", args=[self.caso_maria.pk]))
        self.assertContains(resposta, "termina hoje")
        self.assertContains(resposta, "serão removidas")

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
            "caso": self.caso_joao.pk, "data": f"{self.terca:%Y-%m-%d}", "hora": "20:00", "duracao": "50"}, follow=True)
        self.assertContains(resposta, "fora da sua grade")
        self.assertTrue(Consulta.objetos_todos.filter(caso=self.caso_joao).exists())

    def test_consulta_dentro_da_grade_nao_avisa(self):
        with contexto.como(self.ana.pk):
            HorarioDisponivel.objects.create(dia_semana=TERCA, inicio=time(8), fim=time(12))
        self.entrar(self.ana)
        resposta = self.client.post(reverse("atendimentos:nova"), {
            "caso": self.caso_joao.pk, "data": f"{self.terca:%Y-%m-%d}", "hora": "10:00", "duracao": "50"}, follow=True)
        self.assertNotContains(resposta, "fora da sua grade")


class RLSNaAgenda(TransactionTestCase):
    """As tabelas da agenda sob a terceira camada da ADR-001."""

    TABELAS = ["agenda_recorrencia", "agenda_horariodisponivel", "atendimentos_consulta", "atendimentos_desfecho"]

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("RLS exige PostgreSQL.")
        self.ana = criar_psicologo("ana.rlsagenda@exemplo.com", "33333333333", "959595")
        self.bruno = criar_psicologo("bruno.rlsagenda@exemplo.com", "44444444444", "969696")
        terca = proxima(TERCA)
        for psicologo, nome in [(self.ana, "Da Ana"), (self.bruno, "Do Bruno")]:
            with contexto.como(psicologo.pk):
                caso = cadastrar_paciente(Paciente(nome=nome))
                servicos.definir_frequencia(caso, frequencia=SEMANAL, dia_semana=TERCA, hora=time(14), a_partir_de=terca)
                HorarioDisponivel.objects.create(dia_semana=TERCA, inicio=time(13), fim=time(18))
                # Desfecho em outro caso: encerrar este apagaria as consultas que a tabela de consultas precisa ter.
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
