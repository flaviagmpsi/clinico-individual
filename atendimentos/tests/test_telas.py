"""As telas da agenda, vistas por dois psicólogos ao mesmo tempo.

`test_servicos.py` prova que as **regras** da agenda funcionam. Este arquivo prova que as **telas** usam essas
regras sem atravessar a fronteira entre psicólogos — outra coisa. Uma view que buscasse a consulta pelo id sem
passar pelo manager do dono passaria em todos os testes de serviço e vazaria aqui.

`TransactionTestCase` pelo motivo de sempre nas telas: o middleware troca o papel do banco com `SET LOCAL ROLE`,
que se prende à transação.
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
REALIZADA = Consulta.Estado.REALIZADA
FALTA_COBRADA = Consulta.Estado.FALTA_COBRADA
FALTA_REMARCADA = Consulta.Estado.FALTA_REMARCADA


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
        self.assertEqual(self.client.post(editar, {"estado": FALTA_REMARCADA}).status_code, 404)
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
                                    {"estado": FALTA_COBRADA, "hora": "09:00", "duracao": "50"})
        self.assertEqual(resposta.status_code, 302)
        consulta = Consulta.objetos_todos.get(recorrencia=self.regra_joao, data_prevista=self.ontem)
        self.assertEqual(consulta.estado, FALTA_COBRADA)
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
        resposta = self.client.post(reverse("atendimentos:editar", args=[consulta.pk]), {"estado": FALTA_REMARCADA})
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Consulta.objetos_todos.get(pk=consulta.pk).estado, FALTA_REMARCADA)

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

    def test_painel_mostra_as_sessoes_pendentes(self):
        self.entrar(self.ana)
        self.assertContains(self.client.get(reverse("painel")), "Sessões pendentes de cadastro")

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
