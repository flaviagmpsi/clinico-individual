"""O duplo clique no botão de criar conta (ADR-126).

Aconteceu com uma psicóloga de verdade, e o registro de acesso do servidor mostrou os dois envios com **um
segundo** de diferença: o primeiro criou a conta e o segundo devolveu "e-mail já cadastrado" e "CRP já
cadastrado". As duas mensagens eram verdadeiras sobre o banco e mentirosas sobre o que tinha acontecido — a
conta existia porque ela mesma a criara um segundo antes. Ela concluiu que o cadastro tinha falhado duas vezes.

O segundo envio chega **sem o cookie de sessão** do primeiro, e é por isso que o atalho de "já está logado" do
`dispatch` não a resgatava. É esse detalhe que os testes aqui reproduzem: um cliente novo, sem sessão nenhuma.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from contas.models import Psicologo

SENHA = "Senha-De-Teste-123"
DADOS = {"email": "nova.conta@exemplo.com", "crp_regiao": "04", "crp_numero": "616161",
         "password1": SENHA, "password2": SENHA}


class DuploEnvio(TestCase):
    def criar(self, cliente=None, **mudancas):
        return (cliente or self.client).post(reverse("contas:criar_conta"), {**DADOS, **mudancas})

    def test_o_primeiro_envio_cria_a_conta(self):
        self.assertEqual(self.criar().status_code, 302)
        self.assertTrue(Psicologo.objects.filter(email=DADOS["email"]).exists())

    def test_o_segundo_envio_entra_em_vez_de_recusar(self):
        """O coração da ADR-126: mesmo gesto, mesmo dono, e o sistema deixa de dizer que deu errado."""
        self.criar()
        from django.test import Client
        sem_sessao = Client()          # como o segundo POST chega: sem o cookie do primeiro
        resposta = self.criar(sem_sessao)
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Psicologo.objects.filter(email=DADOS["email"]).count(), 1)
        self.assertIn("_auth_user_id", sem_sessao.session)   # entrou

    def test_nao_duplica_a_conta(self):
        self.criar()
        self.criar()
        self.assertEqual(Psicologo.objects.count(), 1)

    def test_com_a_senha_errada_nao_entra(self):
        """A recuperação é para o dono. Senha diferente é outra pessoa tentando o mesmo e-mail."""
        self.criar()
        from django.test import Client
        resposta = self.criar(Client(), password1="Outra-Senha-456", password2="Outra-Senha-456")
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Este e-mail já tem uma conta")

    def test_conta_antiga_nao_e_resgatada(self):
        """Fora da janela, isto seria um login sem o freio contra tentativa em massa (ADR-114).

        O lugar de entrar é a tela de entrar, que tem o freio. Aqui a conta é envelhecida à mão.
        """
        self.criar()
        conta = Psicologo.objects.get(email=DADOS["email"])
        conta.date_joined = timezone.now() - timedelta(hours=2)
        conta.save(update_fields=["date_joined"])
        from django.test import Client
        resposta = self.criar(Client())
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Este e-mail já tem uma conta")


    def test_crp_diferente_nao_e_resgatado(self):
        """CRP diferente não é duplo clique: é correção, e entrar jogaria fora o que a pessoa acabou de digitar."""
        self.criar()
        from django.test import Client
        resposta = self.criar(Client(), crp_numero="626262")
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Este e-mail já tem uma conta")


class MensagensQueAjudam(TestCase):
    """As duas mensagens deixam de ser fato de banco e viram saída (ADR-126)."""

    def setUp(self):
        self.client.post(reverse("contas:criar_conta"), DADOS)
        self.client.logout()

    def test_e_mail_repetido_diz_o_que_fazer(self):
        from django.test import Client
        resposta = Client().post(reverse("contas:criar_conta"),
                                 {**DADOS, "password1": "Outra-Senha-456", "password2": "Outra-Senha-456"})
        self.assertContains(resposta, "Esqueci minha senha")
        self.assertContains(resposta, "Se você acabou de se cadastrar, deu certo")

    def test_crp_repetido_diz_o_que_fazer(self):
        from django.test import Client
        resposta = Client().post(reverse("contas:criar_conta"),
                                 {**DADOS, "email": "outra@exemplo.com"})
        self.assertContains(resposta, "Já existe uma conta com este CRP")
        self.assertContains(resposta, "Esqueci minha senha")
