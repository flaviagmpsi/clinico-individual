"""As telas de paciente, vistas por dois psicólogos ao mesmo tempo.

Os testes de `core` provam que a fundação isola. Estes provam que **a tela usa a fundação** —
que é outra coisa. Uma view que chamasse `objetos_todos` por descuido passaria por todos os
testes de `core` e vazaria aqui.

`TransactionTestCase` e não `TestCase`: o middleware troca o papel do Postgres com `SET LOCAL
ROLE`, que se prende à transação. Dentro de um `TestCase` ele se prenderia à transação externa
do teste e sobreviveria de uma requisição para a outra — exatamente o que estes testes existem
para desmentir.
"""

from django.test import TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo
from core import contexto
from pacientes.models import Paciente

SENHA = "senha-de-teste-123"


class BaseTelas(TransactionTestCase):
    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.tela@exemplo.com", password=SENHA, nome_completo="Ana",
            cpf="11111111111", telefone="31988887777", crp_regiao="04", crp_numero="101010")
        self.bruno = Psicologo.objects.create_user(
            email="bruno.tela@exemplo.com", password=SENHA, nome_completo="Bruno",
            cpf="22222222222", telefone="31988887777", crp_regiao="04", crp_numero="202020")
        with contexto.como(self.ana.pk):
            self.da_ana = Paciente.objects.create(nome="Paciente da Ana")
        with contexto.como(self.bruno.pk):
            self.do_bruno = Paciente.objects.create(nome="Paciente do Bruno")

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))


class SemLogin(BaseTelas):
    def test_toda_tela_de_dominio_exige_login(self):
        """Nenhuma tela pode ser alcançada por quem não entrou — nem para ver um 404 revelador."""
        for nome, args in [
            ("painel", []), ("pacientes:lista", []), ("pacientes:novo", []),
            ("pacientes:detalhe", [self.da_ana.pk]), ("pacientes:editar", [self.da_ana.pk]),
            ("pacientes:excluir", [self.da_ana.pk]), ("contas:perfil", []),
        ]:
            with self.subTest(tela=nome):
                resposta = self.client.get(reverse(nome, args=args))
                self.assertEqual(resposta.status_code, 302)
                self.assertIn(reverse("contas:entrar"), resposta["Location"])


class ListaEBusca(BaseTelas):
    def test_a_lista_mostra_so_os_proprios_pacientes(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("pacientes:lista"))
        self.assertContains(resposta, "Paciente da Ana")
        self.assertNotContains(resposta, "Paciente do Bruno")

    def test_a_busca_nao_atravessa_a_fronteira(self):
        """Buscar pelo nome exato do paciente alheio não o encontra.

        A asserção é sobre o **resultado**, não sobre o texto da página: o termo buscado é
        ecoado no campo de busca e na mensagem de vazio, então procurar a string no HTML
        acusaria um vazamento que não existe.
        """
        self.entrar(self.ana)
        resposta = self.client.get(reverse("pacientes:lista"), {"q": "Paciente do Bruno"})
        self.assertEqual(list(resposta.context["pacientes"]), [])
        self.assertContains(resposta, "Nenhum paciente encontrado")


class AcessoPorIdAlheio(BaseTelas):
    """Adivinhar o id é a tentativa mais óbvia, e a que a maioria dos CRUDs de Django deixa passar."""

    def test_ver_editar_e_excluir_paciente_de_outro_da_404(self):
        self.entrar(self.ana)
        for nome in ["pacientes:detalhe", "pacientes:editar", "pacientes:excluir"]:
            with self.subTest(tela=nome):
                resposta = self.client.get(reverse(nome, args=[self.do_bruno.pk]))
                self.assertEqual(resposta.status_code, 404)

    def test_post_de_edicao_em_paciente_alheio_nao_grava(self):
        self.entrar(self.ana)
        resposta = self.client.post(
            reverse("pacientes:editar", args=[self.do_bruno.pk]), {"nome": "Renomeado", "uf": ""})
        self.assertEqual(resposta.status_code, 404)
        self.do_bruno.refresh_from_db()
        self.assertEqual(self.do_bruno.nome, "Paciente do Bruno")

    def test_post_de_exclusao_em_paciente_alheio_nao_apaga(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("pacientes:excluir", args=[self.do_bruno.pk]))
        self.assertEqual(resposta.status_code, 404)
        self.assertTrue(Paciente.objetos_todos.filter(pk=self.do_bruno.pk).exists())


class Cadastro(BaseTelas):
    def test_cadastrar_preenche_o_dono_sem_campo_na_tela(self):
        """O formulário não tem campo de psicólogo — o dono vem do contexto da requisição."""
        self.entrar(self.ana)
        resposta = self.client.post(reverse("pacientes:novo"),
                                    {"nome": "Novo Paciente", "uf": "", "horario-frequencia": "AVULSO"}, follow=True)
        self.assertEqual(resposta.status_code, 200)
        novo = Paciente.objetos_todos.get(nome="Novo Paciente")
        self.assertEqual(novo.psicologo_id, self.ana.pk)

    def test_mandar_psicologo_no_post_nao_muda_o_dono(self):
        """Quem editar o HTML e injetar `psicologo` não consegue cadastrar para outro."""
        self.entrar(self.ana)
        self.client.post(reverse("pacientes:novo"),
                         {"nome": "Injetado", "uf": "", "psicologo": self.bruno.pk, "horario-frequencia": "AVULSO"}, follow=True)
        self.assertEqual(Paciente.objetos_todos.get(nome="Injetado").psicologo_id, self.ana.pk)

    def test_cpf_com_pontuacao_e_recusado_pelo_formulario(self):
        """O formulário mostra a mensagem do validador do model — o mesmo que o `save()` aplica
        desde a P-69 em qualquer caminho de gravação."""
        self.entrar(self.ana)
        resposta = self.client.post(reverse("pacientes:novo"), {"nome": "X", "cpf": "111.111", "uf": ""})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "CPF tem 11 números")
        self.assertFalse(Paciente.objetos_todos.filter(nome="X").exists())
