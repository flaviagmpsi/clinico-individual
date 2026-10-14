"""A escrita assistida se oferece onde serve, em vez de esperar ser procurada (ADR-127).

O que motivou: de três testadoras reais, **duas** estavam sem o recurso — não por escolha, mas por não saberem
que existia. Ele morava no fim de um cartão de Configurações, depois do controle de despesas, que não é lugar
onde alguém procura algo de prontuário.

A decisão da ADR-111 — nasce desligada, porque manda conteúdo de sessão para fora — continua inteira. Perguntar
não é inscrever, e é isso que os testes abaixo separam: o convite aparece, o estado só muda quando se clica.
"""

from unittest import mock

from django.test import TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo

SENHA = "senha-de-teste-123"


class Base(TransactionTestCase):
    """`TransactionTestCase` e não `TestCase`: estes testes fazem login, e o `SET LOCAL ROLE` do middleware vaza
    dentro da transação única do `TestCase` — o banco passa a responder "permission denied for table
    django_session", e o estrago alcança testes vizinhos. Armadilha conhecida deste projeto."""

    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.conviteia@exemplo.com", password=SENHA, nome_completo="Ana",
            crp_regiao="04", crp_numero="929292")
        self.assertTrue(self.client.login(username=self.ana.email, password=SENHA))


class ConviteNaListaDeProntuarios(Base):
    @mock.patch("prontuarios.ia.disponivel", return_value=True)
    def test_quem_nao_ligou_recebe_o_convite(self, _):
        resposta = self.client.get(reverse("prontuarios:lista"))
        self.assertContains(resposta, "Escrever o prontuário falando")
        self.assertContains(resposta, reverse("prontuarios:ativar_ia"))

    @mock.patch("prontuarios.ia.disponivel", return_value=True)
    def test_quem_ja_ligou_nao_e_convidado_de_novo(self, _):
        self.ana.usa_ia_no_prontuario = True
        self.ana.save(update_fields=["usa_ia_no_prontuario"])
        self.assertNotContains(self.client.get(reverse("prontuarios:lista")),
                               "Ligar a escrita assistida")

    @mock.patch("prontuarios.ia.disponivel", return_value=False)
    def test_sem_chave_no_servidor_nao_oferece(self, _):
        """Oferecer o que não funcionaria no clique é pior que não oferecer."""
        self.assertNotContains(self.client.get(reverse("prontuarios:lista")),
                               "Ligar a escrita assistida")


class LigarEmUmClique(Base):
    @mock.patch("prontuarios.ia.disponivel", return_value=True)
    def test_o_aviso_de_ligada_ensina_a_desligar_com_link(self, _):
        """Quem liga num clique precisa saber desligar no mesmo fôlego — e o caminho vai como link, não como
        instrução escrita, para não transformar "desligar" numa caça ao tesouro em Configurações."""
        resposta = self.client.post(reverse("prontuarios:ativar_ia"), follow=True)
        corpo = resposta.content.decode()
        self.assertIn("Para desligar, vá em", corpo)
        self.assertIn(f'href="{reverse("contas:configuracoes")}"', corpo)

    @mock.patch("prontuarios.ia.disponivel", return_value=True)
    def test_o_botao_liga_e_volta_para_onde_estava(self, _):
        destino = reverse("prontuarios:lista")
        resposta = self.client.post(reverse("prontuarios:ativar_ia"), {"voltar": destino})
        self.assertRedirects(resposta, destino)
        self.ana.refresh_from_db()
        self.assertTrue(self.ana.usa_ia_no_prontuario)

    def test_so_por_post(self):
        """Isto muda a conta: um link que ligasse a IA seria acionado por um prefetch do navegador."""
        self.assertEqual(self.client.get(reverse("prontuarios:ativar_ia")).status_code, 405)
        self.ana.refresh_from_db()
        self.assertFalse(self.ana.usa_ia_no_prontuario)

    def test_so_para_quem_entrou(self):
        self.client.logout()
        resposta = self.client.post(reverse("prontuarios:ativar_ia"))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("entrar", resposta["Location"])

    @mock.patch("prontuarios.ia.disponivel", return_value=True)
    def test_depois_de_ligar_o_convite_some_e_o_bloco_aparece(self, _):
        self.client.post(reverse("prontuarios:ativar_ia"))
        resposta = self.client.get(reverse("prontuarios:lista"))
        self.assertNotContains(resposta, "Ligar a escrita assistida")


class PerguntadaNoCadastro(TransactionTestCase):
    """ADR-127: a pergunta entra no quiz, para a escolha ser feita na entrada e não procurada depois.

    A conta nasce com nome, CPF e telefone já preenchidos de propósito: sem eles o `dispatch` do quiz manda de
    volta para o passo 1, que é o que ele deve mesmo fazer — ninguém conclui o cadastro pulando pergunta pela
    barra de endereço. O que se quer testar aqui é o passo 2, e para chegar nele o passo 1 precisa estar pronto.
    """

    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.quizia@exemplo.com", password=SENHA, crp_regiao="04", crp_numero="939393",
            nome_completo="Ana Quiz", cpf="11144477735", telefone="31988887777")
        self.assertTrue(self.client.login(username=self.ana.email, password=SENHA))

    def test_a_pergunta_aparece_no_passo_do_regime(self):
        resposta = self.client.get(reverse("contas:quiz", args=[2]))
        self.assertContains(resposta, "Quero escrever o prontuário falando")
        self.assertContains(resposta, "OpenAI")

    def test_nasce_desmarcada(self):
        """Perguntar não é inscrever (ADR-111)."""
        self.assertFalse(self.ana.usa_ia_no_prontuario)
        self.assertNotContains(self.client.get(reverse("contas:quiz", args=[2])),
                               'name="usa_ia_no_prontuario" checked')

    def test_marcar_no_quiz_liga(self):
        self.client.post(reverse("contas:quiz", args=[2]),
                         {"regime": "PF", "usa_ia_no_prontuario": "on"})
        self.ana.refresh_from_db()
        self.assertTrue(self.ana.usa_ia_no_prontuario)

    def test_nao_marcar_deixa_desligada(self):
        self.client.post(reverse("contas:quiz", args=[2]), {"regime": "PF"})
        self.ana.refresh_from_db()
        self.assertFalse(self.ana.usa_ia_no_prontuario)
