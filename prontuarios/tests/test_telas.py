"""As telas do prontuário, vistas por dois psicólogos ao mesmo tempo (ADR-064).

`TransactionTestCase` pelo motivo de sempre nas telas: o middleware usa `SET LOCAL ROLE`.
"""

from datetime import datetime

from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from atendimentos import servicos as agenda
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto
from core.models import RegistroAuditoria
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente
from prontuarios import servicos
from prontuarios.models import Prontuario, VersaoProntuario

SENHA = "senha-de-teste-123"
REALIZADA = Consulta.Estado.REALIZADA


def momento(dia, hora=10):
    return timezone.make_aware(datetime(2026, 9, dia, hora))


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


class BaseTelasProntuario(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.telapront@exemplo.com", "11111111111", "656565")
        self.bruno = criar_psicologo("bruno.telapront@exemplo.com", "22222222222", "666666")
        with contexto.como(self.ana.pk):
            self.marcos = Paciente(nome="Marcos Tela")
            caso = cadastrar_paciente(self.marcos)
            self.sessao = agenda.cadastrar_avulsa(caso, estado=REALIZADA, inicio=momento(3))
            self.falta = agenda.cadastrar_avulsa(caso, estado=Consulta.Estado.FALTOU, inicio=momento(4))
        with contexto.como(self.bruno.pk):
            self.carla = Paciente(nome="Carla Tela")
            caso_carla = cadastrar_paciente(self.carla)
            self.sessao_carla = agenda.cadastrar_avulsa(caso_carla, estado=REALIZADA, inicio=momento(3))

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def escrever(self, consulta=None, paciente=None):
        return reverse("prontuarios:escrever", args=[(consulta or self.sessao).pk, (paciente or self.marcos).pk])


class ExigeLoginENaoAtravessa(BaseTelasProntuario):
    def test_nenhuma_tela_abre_sem_login(self):
        for rota in [reverse("prontuarios:lista"), self.escrever(),
                     reverse("prontuarios:descartar", args=[self.sessao.pk, self.marcos.pk])]:
            with self.subTest(rota=rota):
                resposta = self.client.get(rota)
                self.assertEqual(resposta.status_code, 302)
                self.assertIn(reverse("contas:entrar"), resposta["Location"])

    def test_prontuario_alheio_falta_e_quem_nao_participou_dao_404(self):
        self.entrar(self.ana)
        for rota in [self.escrever(self.sessao_carla, self.carla), self.escrever(self.falta),
                     self.escrever(paciente=self.carla)]:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 404)
        resposta = self.client.post(self.escrever(self.sessao_carla, self.carla),
                                    {"texto": "Intrusão.", "acao": "confirmar"})
        self.assertEqual(resposta.status_code, 404)
        self.assertFalse(Prontuario.objetos_todos.filter(consulta=self.sessao_carla).exists())

    def test_lista_mostra_so_os_proprios_pendentes(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("prontuarios:lista"))
        self.assertContains(resposta, "Marcos Tela")
        self.assertNotContains(resposta, "Carla Tela")


class EscritaPelaTela(BaseTelasProntuario):
    def test_salvar_rascunho_e_confirmar(self):
        self.entrar(self.ana)
        self.assertEqual(self.client.post(self.escrever(), {"texto": "Rascunho.", "acao": "rascunho"}).status_code, 302)
        self.assertIsNone(VersaoProntuario.objetos_todos.get().confirmada_em)
        self.assertEqual(self.client.post(self.escrever(), {"texto": "Registro final.", "acao": "confirmar"}).status_code, 302)
        versao = VersaoProntuario.objetos_todos.get()
        self.assertEqual((versao.texto, versao.confirmada_em is not None), ("Registro final.", True))

    def test_editar_nao_pede_motivo_e_guarda_a_versao_anterior(self):
        """ADR-075: a tela tem um botão "Editar" e nenhum campo de motivo; a versão antiga fica no histórico."""
        with contexto.como(self.ana.pk):
            servicos.confirmar(self.sessao, self.marcos, texto="Original.")
        self.entrar(self.ana)
        tela = self.client.get(self.escrever())
        self.assertContains(tela, "Editar")
        self.assertNotContains(tela, "Motivo da correção")

        resposta = self.client.post(self.escrever(), {"texto": "Editado.", "acao": "confirmar"})
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual([v.texto for v in VersaoProntuario.objetos_todos.order_by("numero")],
                         ["Original.", "Editado."])
        self.assertContains(self.client.get(self.escrever()), "Histórico")

    def test_abrir_prontuario_registra_visualizacao(self):
        with contexto.como(self.ana.pk):
            servicos.confirmar(self.sessao, self.marcos, texto="Original.")
        self.entrar(self.ana)
        self.assertContains(self.client.get(self.escrever()), "Original.")
        self.assertTrue(RegistroAuditoria.objetos_todos.filter(
            acao=RegistroAuditoria.Acao.VER, alvo="prontuarios.prontuario", titular_id=self.marcos.pk).exists())

    def test_ficha_e_painel_levam_ao_prontuario(self):
        self.entrar(self.ana)
        # A ficha leva à folha completa do prontuário (ADR-079); a lista por paciente continua existindo.
        self.assertContains(self.client.get(reverse("pacientes:detalhe", args=[self.marcos.pk])),
                            reverse("prontuarios:paciente", args=[self.marcos.pk]))
        self.assertContains(self.client.get(reverse("painel")), "Prontuários para escrever")
        self.assertContains(self.client.get(reverse("prontuarios:lista"), {"paciente": self.marcos.pk}), "Não escrito")
