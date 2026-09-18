"""O quiz de cadastro (C-10, ADR-071): a conta nasce e só entra quando o sistema sabe o bastante.

- `CriarConta` — o passo 1 cria a conta, já loga e leva ao passo 2; máscara limpa; e-mail repetido é recusado.
- `PassosDoQuiz` — cada passo grava o que coletou; o último libera o sistema; as regras de cada pergunta.
- `SistemaTrancado` — enquanto o quiz não termina, qualquer tela volta para ele — menos sair.

`TransactionTestCase` pelo motivo de sempre nas telas: o middleware troca o papel do banco com `SET LOCAL ROLE`.
"""

from django.test import TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo

SENHA = "senha-de-teste-123"


def conta_do_passo_1(**ajustes):
    dados = {
        "nome_completo": "Ana Ribeiro", "email": "ana.quiz@exemplo.com", "cpf": "529.982.247-25",
        "telefone": "(31) 98888-7777", "crp_regiao": "04", "crp_numero": "123456",
        "password1": "uma-senha-bem-longa-123", "password2": "uma-senha-bem-longa-123",
    }
    dados.update(ajustes)
    return dados


class CriarConta(TransactionTestCase):
    def criar(self, **ajustes):
        return self.client.post(reverse("contas:criar_conta"), conta_do_passo_1(**ajustes))

    def test_cria_a_conta_loga_e_leva_ao_passo_seguinte(self):
        resposta = self.criar()
        self.assertRedirects(resposta, reverse("contas:quiz", args=[1]), fetch_redirect_response=False)
        psicologo = Psicologo.objects.get(email="ana.quiz@exemplo.com")
        # ADR-066: a tela manda com máscara, o banco guarda número puro.
        self.assertEqual((psicologo.cpf, psicologo.telefone), ("52998224725", "31988887777"))
        self.assertFalse(psicologo.cadastro_completo)
        self.assertEqual(self.client.session.get("_auth_user_id"), str(psicologo.pk))

    def test_senhas_diferentes_nao_criam_conta(self):
        resposta = self.criar(password2="outra-senha-qualquer-123")
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(Psicologo.objects.filter(email="ana.quiz@exemplo.com").exists())

    def test_email_repetido_e_recusado(self):
        self.criar()
        self.client.logout()
        resposta = self.criar(cpf="15350946056", crp_numero="654321")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(Psicologo.objects.filter(email="ana.quiz@exemplo.com").count(), 1)

    def test_quem_ja_esta_logado_nao_cria_outra_conta(self):
        self.criar()
        self.assertRedirects(self.client.get(reverse("contas:criar_conta")), reverse("painel"),
                             fetch_redirect_response=False)


class PassosDoQuiz(TransactionTestCase):
    def setUp(self):
        self.client.post(reverse("contas:criar_conta"), conta_do_passo_1())
        self.psicologo = Psicologo.objects.get(email="ana.quiz@exemplo.com")

    def passo(self, numero):
        return reverse("contas:quiz", args=[numero])

    def responder_regime(self, **ajustes):
        dados = {"regime": "PF", "cnpj": "", "razao_social": ""}
        dados.update(ajustes)
        return self.client.post(self.passo(1), dados)

    def responder_atendimento(self, **ajustes):
        dados = {"abordagem": "TCC", "abordagem_outra": "", "atende_presencial": "on"}
        dados.update(ajustes)
        return self.client.post(self.passo(2), dados)

    def responder_clinica(self, **ajustes):
        dados = {"nome_clinica": "Consultório da Ana", "telefone_clinica": "(31) 3333-4444",
                 "cep": "30140-071", "logradouro": "Rua da Bahia", "numero": "1200", "complemento": "",
                 "bairro": "Lourdes", "cidade": "Belo Horizonte", "uf": "MG"}
        dados.update(ajustes)
        return self.client.post(self.passo(3), dados)

    def test_cada_passo_grava_o_que_coletou_e_o_ultimo_libera_o_sistema(self):
        self.assertRedirects(self.responder_regime(), self.passo(2), fetch_redirect_response=False)
        self.assertRedirects(self.responder_atendimento(), self.passo(3), fetch_redirect_response=False)
        self.psicologo.refresh_from_db()
        self.assertEqual((self.psicologo.regime, self.psicologo.abordagem), ("PF", "TCC"))
        self.assertFalse(self.psicologo.cadastro_completo)  # ainda falta a clínica

        self.assertRedirects(self.responder_clinica(), reverse("painel"), fetch_redirect_response=False)
        self.psicologo.refresh_from_db()
        self.assertTrue(self.psicologo.cadastro_completo)
        self.assertEqual((self.psicologo.cep, self.psicologo.cidade), ("30140071", "Belo Horizonte"))

    def test_pessoa_juridica_sem_cnpj_e_recusada(self):
        resposta = self.responder_regime(regime="PJ")
        self.assertContains(resposta, "precisa do CNPJ")
        self.psicologo.refresh_from_db()
        self.assertEqual(self.psicologo.regime, "PF")  # o padrão do model, intacto

    def test_precisa_de_pelo_menos_uma_forma_de_atendimento(self):
        self.responder_regime()
        resposta = self.client.post(self.passo(2), {"abordagem": "TCC", "abordagem_outra": ""})
        self.assertContains(resposta, "pelo menos uma forma")

    def test_abordagem_outra_pede_qual(self):
        self.responder_regime()
        resposta = self.responder_atendimento(abordagem="OUTRA")
        self.assertContains(resposta, "Diga qual é a abordagem")

    def test_quem_atende_presencialmente_precisa_do_endereco(self):
        self.responder_regime()
        self.responder_atendimento()
        resposta = self.responder_clinica(cep="", logradouro="", numero="", bairro="", cidade="", uf="")
        self.assertContains(resposta, "precisa informar o endereço")
        self.psicologo.refresh_from_db()
        self.assertFalse(self.psicologo.cadastro_completo)

    def test_quem_atende_so_online_conclui_sem_endereco(self):
        self.responder_regime()
        self.responder_atendimento(atende_presencial="", atende_online="on")
        resposta = self.responder_clinica(cep="", logradouro="", numero="", bairro="", cidade="", uf="")
        self.assertRedirects(resposta, reverse("painel"), fetch_redirect_response=False)
        self.psicologo.refresh_from_db()
        self.assertTrue(self.psicologo.cadastro_completo)

    def test_passo_inexistente_da_404(self):
        self.assertEqual(self.client.get(self.passo(9)).status_code, 404)


class SistemaTrancado(TransactionTestCase):
    def setUp(self):
        self.client.post(reverse("contas:criar_conta"), conta_do_passo_1())

    def test_qualquer_tela_volta_para_o_quiz(self):
        for nome in ["painel", "pacientes:lista", "atendimentos:agenda", "financeiro:mes", "contas:perfil"]:
            with self.subTest(tela=nome):
                self.assertRedirects(self.client.get(reverse(nome)), reverse("contas:quiz", args=[1]),
                                     fetch_redirect_response=False)

    def test_sair_continua_funcionando(self):
        self.assertEqual(self.client.post(reverse("contas:sair")).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_cadastro_concluido_libera_as_telas(self):
        self.client.post(reverse("contas:quiz", args=[1]), {"regime": "PF", "cnpj": "", "razao_social": ""})
        self.client.post(reverse("contas:quiz", args=[2]),
                         {"abordagem": "TCC", "abordagem_outra": "", "atende_online": "on"})
        self.client.post(reverse("contas:quiz", args=[3]),
                         {"nome_clinica": "", "telefone_clinica": "", "cep": "", "logradouro": "", "numero": "",
                          "complemento": "", "bairro": "", "cidade": "", "uf": ""})
        self.assertEqual(self.client.get(reverse("painel")).status_code, 200)
