"""O que a rodada aberta de testes exige para cada pessoa usar a própria conta com segurança (ADR-114).

Três coisas, e cada uma é bloqueante à sua maneira: a porta não pode trancar no oitavo dia, quem esquece a senha
precisa de saída, e quem tenta adivinhar senha precisa encontrar resistência.
"""

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from contas import freio
from contas.models import Psicologo

SENHA = "hamilton-teste-123"


def criar(email="ana@t.com", crp="4001") -> Psicologo:
    return Psicologo.objects.create_user(email=email, password=SENHA, nome_completo="Ana",
                                         crp_regiao="04", crp_numero=crp)


@override_settings(FREIO_DE_LOGIN_DESLIGADO=True)
class AcessoLiberado(TransactionTestCase):
    """`TransactionTestCase` porque o middleware troca o papel do banco com `SET LOCAL ROLE`."""

    def test_sem_a_chave_ligada_a_conta_nova_vai_para_o_plano(self):
        """O comportamento de sempre (ADR-094) continua intacto quando a rodada aberta está desligada."""
        resposta = self.client.post(reverse("contas:criar_conta"), {
            "email": "nova@t.com", "password1": SENHA, "password2": SENHA,
            "crp_regiao": "04", "crp_numero": "4002"})
        self.assertRedirects(resposta, reverse("assinaturas:plano"), fetch_redirect_response=False)

    @override_settings(ACESSO_LIBERADO=True)
    def test_com_a_chave_ligada_a_conta_nova_vai_direto_ao_quiz(self):
        resposta = self.client.post(reverse("contas:criar_conta"), {
            "email": "nova2@t.com", "password1": SENHA, "password2": SENHA,
            "crp_regiao": "04", "crp_numero": "4003"})
        self.assertRedirects(resposta, reverse("contas:quiz", args=[1]), fetch_redirect_response=False)

    @override_settings(ACESSO_LIBERADO=True)
    def test_conta_sem_assinatura_nenhuma_usa_o_sistema(self):
        """Sem isto, o testador seria mandado à tela de plano — que, em produção, não vende nada."""
        psicologo = criar(email="usa@t.com", crp="4004")
        psicologo.nome_completo, psicologo.cpf = "Ana Usa", "52998224725"
        psicologo.save()
        self.client.login(username=psicologo.email, password=SENHA)
        self.assertEqual(self.client.get(reverse("painel")).status_code, 200)

    @override_settings(ACESSO_LIBERADO=True)
    def test_a_faixa_diz_que_e_rodada_de_testes(self):
        """Quem está testando precisa saber que está testando — e que o que escreve ali é de verdade."""
        psicologo = criar(email="faixa@t.com", crp="4005")
        self.client.login(username=psicologo.email, password=SENHA)
        self.assertContains(self.client.get(reverse("painel")), "Rodada aberta de testes")


@override_settings(FREIO_DE_LOGIN_DESLIGADO=True)
class RecuperarSenha(TransactionTestCase):
    def test_pedir_manda_e_mail_com_link_que_troca_a_senha(self):
        psicologo = criar(email="esqueceu@t.com", crp="4010")
        self.client.post(reverse("contas:senha_pedir"), {"email": "esqueceu@t.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/conta/senha/trocar/", mail.outbox[0].body)

        uid = urlsafe_base64_encode(force_bytes(psicologo.pk))
        token = default_token_generator.make_token(psicologo)
        # O Django troca o token da URL por `set-password` e redireciona; é esse endereço que aceita o POST.
        self.client.get(reverse("contas:senha_trocar", args=[uid, token]))
        nova = "outra-senha-boa-456"
        self.client.post(reverse("contas:senha_trocar", args=[uid, "set-password"]),
                         {"new_password1": nova, "new_password2": nova})
        self.assertTrue(self.client.login(username="esqueceu@t.com", password=nova))

    def test_e_mail_que_nao_existe_responde_igual_e_nao_manda_nada(self):
        """Dizer "não há conta com este e-mail" entregaria a quem pergunta a lista de quem usa o sistema."""
        resposta = self.client.post(reverse("contas:senha_pedir"), {"email": "ninguem@t.com"})
        self.assertRedirects(resposta, reverse("contas:senha_enviada"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_entrada_mostra_o_caminho(self):
        self.assertContains(self.client.get(reverse("contas:entrar")), "Esqueci a minha senha")


class FreioDeLogin(TransactionTestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.psicologo = criar(email="alvo@t.com", crp="4020")

    def errar(self, vezes=1):
        for _ in range(vezes):
            self.client.post(reverse("contas:entrar"), {"username": "alvo@t.com", "password": "errada"})

    def test_depois_de_muitas_tentativas_a_porta_trava(self):
        """Com a porta travada, **a senha certa também é recusada** — é isso que faz o freio valer alguma coisa.

        O teste passa pela tela (`post`), e não por `client.login`: este último fala direto com o backend de
        autenticação e não atravessa a view, então não veria o freio.
        """
        self.errar(freio.TENTATIVAS_ATE_TRAVAR)
        resposta = self.client.post(reverse("contas:entrar"), {"username": "alvo@t.com", "password": SENHA})
        self.assertEqual(resposta.status_code, 200, "a senha certa deveria ter sido recusada pelo freio")
        self.assertContains(resposta, "Muitas tentativas")

    def test_antes_do_limite_a_senha_certa_continua_entrando(self):
        self.errar(freio.TENTATIVAS_ATE_TRAVAR - 1)
        resposta = self.client.post(reverse("contas:entrar"), {"username": "alvo@t.com", "password": SENHA})
        self.assertEqual(resposta.status_code, 302)

    def test_entrar_zera_a_contagem(self):
        """Quem sabe a senha não deve ser punido por ter errado antes."""
        self.errar(3)
        self.client.post(reverse("contas:entrar"), {"username": "alvo@t.com", "password": SENHA})
        self.assertFalse(freio.travado(self._pedido(), "alvo@t.com"))

    def test_a_recusa_nao_revela_se_a_conta_existe(self):
        """Travado ou não, a primeira linha é sempre a mesma."""
        self.errar(freio.TENTATIVAS_ATE_TRAVAR)
        resposta = self.client.post(reverse("contas:entrar"), {"username": "alvo@t.com", "password": "errada"})
        self.assertContains(resposta, "E-mail ou senha incorretos")

    @staticmethod
    def _pedido():
        from django.test import RequestFactory
        return RequestFactory().post("/")
