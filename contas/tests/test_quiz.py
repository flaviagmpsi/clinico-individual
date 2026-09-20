"""O cadastro do psicólogo (ADR-094, que refaz a ADR-071): conta curta, escolha do plano, e o quiz já dentro.

- `CriarConta` — só login e CRP; a conta nasce, já loga e vai escolher entre assinar e testar.
- `PerguntasDoQuiz` — cada pergunta grava o que coletou; a última libera o sistema; as regras de cada uma.
- `SistemaTrancado` — enquanto o quiz não termina, qualquer tela volta para ele — menos sair.

`TransactionTestCase` pelo motivo de sempre nas telas: o middleware troca o papel do banco com `SET LOCAL ROLE`.
"""

from django.test import TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo

SENHA = "senha-de-teste-123"


def dados_da_conta(**ajustes):
    dados = {"email": "ana.quiz@exemplo.com", "crp_regiao": "04", "crp_numero": "123456",
             "password1": "uma-senha-bem-longa-123", "password2": "uma-senha-bem-longa-123"}
    dados.update(ajustes)
    return dados


def criar_conta_e_comecar_o_teste(cliente, **ajustes):
    """O caminho de quem chega: cria a conta e escolhe o teste grátis. Daqui em diante, o que o espera é o quiz."""
    cliente.post(reverse("contas:criar_conta"), dados_da_conta(**ajustes))
    cliente.post(reverse("assinaturas:plano"), {"acao": "teste"})


class CriarConta(TransactionTestCase):
    def criar(self, **ajustes):
        return self.client.post(reverse("contas:criar_conta"), dados_da_conta(**ajustes))

    def test_pede_so_login_e_crp(self):
        resposta = self.client.get(reverse("contas:criar_conta"))
        for campo in ["email", "password1", "password2", "crp_regiao", "crp_numero"]:
            self.assertContains(resposta, f'name="{campo}"')
        for campo in ["nome_completo", "cpf", "telefone"]:
            self.assertNotContains(resposta, f'name="{campo}"')

    def test_cria_a_conta_loga_e_leva_a_escolha_do_plano(self):
        resposta = self.criar()
        self.assertRedirects(resposta, reverse("assinaturas:plano"), fetch_redirect_response=False)
        psicologo = Psicologo.objects.get(email="ana.quiz@exemplo.com")
        self.assertEqual((psicologo.crp, psicologo.nome_completo, psicologo.cpf), ("04/123456", "", None))
        self.assertFalse(psicologo.cadastro_completo)
        self.assertEqual(self.client.session.get("_auth_user_id"), str(psicologo.pk))

    def test_duas_contas_a_meio_caminho_nao_colidem_no_cpf_vazio(self):
        self.criar()
        self.client.logout()
        self.assertEqual(self.criar(email="bia.quiz@exemplo.com", crp_numero="654321").status_code, 302)
        self.assertEqual(Psicologo.objects.filter(cpf__isnull=True).count(), 2)

    def test_senhas_diferentes_nao_criam_conta(self):
        resposta = self.criar(password2="outra-senha-qualquer-123")
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(Psicologo.objects.filter(email="ana.quiz@exemplo.com").exists())

    def test_email_repetido_e_recusado(self):
        self.criar()
        self.client.logout()
        resposta = self.criar(crp_numero="654321")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(Psicologo.objects.filter(email="ana.quiz@exemplo.com").count(), 1)

    def test_crp_repetido_e_recusado_com_mensagem_no_campo(self):
        self.criar()
        self.client.logout()
        resposta = self.criar(email="outra@exemplo.com")
        self.assertContains(resposta, "Já existe uma conta com este CRP")
        self.assertFalse(Psicologo.objects.filter(email="outra@exemplo.com").exists())

    def test_quem_ja_esta_logado_nao_cria_outra_conta(self):
        self.criar()
        self.assertRedirects(self.client.get(reverse("contas:criar_conta")), reverse("painel"),
                             fetch_redirect_response=False)


class PerguntasDoQuiz(TransactionTestCase):
    def setUp(self):
        criar_conta_e_comecar_o_teste(self.client)
        self.psicologo = Psicologo.objects.get(email="ana.quiz@exemplo.com")

    def passo(self, numero):
        return reverse("contas:quiz", args=[numero])

    def responder_quem_e(self, **ajustes):
        dados = {"nome_completo": "Ana Ribeiro", "cpf": "529.982.247-25", "telefone": "(31) 98888-7777"}
        dados.update(ajustes)
        return self.client.post(self.passo(1), dados)

    def responder_regime(self, **ajustes):
        dados = {"regime": "PF", "cnpj": "", "razao_social": ""}
        dados.update(ajustes)
        return self.client.post(self.passo(2), dados)

    def responder_atendimento(self, **ajustes):
        dados = {"abordagens": ["Psicanálise"], "outras_areas": [""], "atende_presencial": "on"}
        dados.update(ajustes)
        return self.client.post(self.passo(3), dados)

    def responder_clinica(self, **ajustes):
        dados = {"nome_clinica": "Consultório da Ana", "telefone_clinica": "(31) 3333-4444",
                 "cep": "30140-071", "logradouro": "Rua da Bahia", "numero": "1200", "complemento": "",
                 "bairro": "Lourdes", "cidade": "Belo Horizonte", "uf": "MG"}
        dados.update(ajustes)
        return self.client.post(self.passo(4), dados)

    def test_cada_pergunta_grava_o_que_coletou_e_a_ultima_libera_o_sistema(self):
        self.assertRedirects(self.responder_quem_e(), self.passo(2), fetch_redirect_response=False)
        self.assertRedirects(self.responder_regime(), self.passo(3), fetch_redirect_response=False)
        self.assertRedirects(self.responder_atendimento(), self.passo(4), fetch_redirect_response=False)
        self.psicologo.refresh_from_db()
        # ADR-066: a tela manda com máscara, o banco guarda número puro.
        self.assertEqual((self.psicologo.cpf, self.psicologo.telefone), ("52998224725", "31988887777"))
        self.assertEqual((self.psicologo.regime, self.psicologo.abordagens), ("PF", ["Psicanálise"]))
        self.assertFalse(self.psicologo.cadastro_completo)  # ainda falta o endereço do presencial

        self.assertRedirects(self.responder_clinica(), reverse("painel"), fetch_redirect_response=False)
        self.psicologo.refresh_from_db()
        self.assertTrue(self.psicologo.cadastro_completo)
        self.assertEqual((self.psicologo.cep, self.psicologo.cidade), ("30140071", "Belo Horizonte"))

    def test_nome_cpf_e_telefone_sao_obrigatorios_no_quiz(self):
        resposta = self.responder_quem_e(nome_completo="", cpf="", telefone="")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.context["form"].errors), 3)

    def test_cpf_de_outra_conta_e_recusado(self):
        Psicologo.objects.create_user(email="dona@exemplo.com", password=SENHA, nome_completo="Dona do CPF",
                                      cpf="52998224725", telefone="31988887777", crp_regiao="04", crp_numero="9")
        self.assertContains(self.responder_quem_e(), "Já existe uma conta com este CPF")

    def test_varias_abordagens_escritas_a_mao_e_outra_area(self):
        self.responder_quem_e()
        self.responder_regime()
        self.responder_atendimento(abordagens=["  Psicanálise ", "Esquizoanálise", "", "psicanálise"],
                                   outras_areas=["Avaliação neuropsicológica"])
        self.psicologo.refresh_from_db()
        # Espaço sobrando, caixa vazia e repetição saem; a ordem em que ele escreveu fica.
        self.assertEqual(self.psicologo.abordagens, ["Psicanálise", "Esquizoanálise"])
        self.assertEqual(self.psicologo.outras_areas, ["Avaliação neuropsicológica"])
        self.assertEqual(self.psicologo.abordagem_descrita, "Psicanálise, Esquizoanálise")

    def test_a_abordagem_e_escrita_e_nao_escolhida_de_lista(self):
        self.responder_quem_e()
        self.responder_regime()
        resposta = self.client.get(self.passo(3))
        self.assertContains(resposta, 'name="abordagens"')
        self.assertNotContains(resposta, "<select")

    def test_sem_nenhuma_abordagem_nao_passa(self):
        self.responder_quem_e()
        self.responder_regime()
        resposta = self.responder_atendimento(abordagens=["", "  "])
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("abordagens", resposta.context["form"].errors)

    def test_pessoa_juridica_sem_cnpj_e_recusada(self):
        self.responder_quem_e()
        resposta = self.responder_regime(regime="PJ")
        self.assertContains(resposta, "precisa do CNPJ")
        self.psicologo.refresh_from_db()
        self.assertEqual(self.psicologo.regime, "PF")  # o padrão do model, intacto

    def test_pessoa_juridica_e_quem_tem_a_nota_fiscal(self):
        self.responder_quem_e()
        self.assertContains(self.client.get(self.passo(2)), "nota fiscal")
        self.responder_regime(regime="PJ", cnpj="11.222.333/0001-81", razao_social="Ana Psicologia Ltda")
        self.psicologo.refresh_from_db()
        self.assertTrue(self.psicologo.emite_nota_fiscal)

    def test_precisa_de_pelo_menos_uma_forma_de_atendimento(self):
        self.responder_quem_e()
        self.responder_regime()
        resposta = self.responder_atendimento(atende_presencial="")
        self.assertContains(resposta, "pelo menos uma forma")

    def test_quem_atende_presencialmente_precisa_do_endereco(self):
        self.responder_quem_e()
        self.responder_regime()
        self.responder_atendimento()
        resposta = self.responder_clinica(cep="", logradouro="", numero="", bairro="", cidade="", uf="")
        self.assertContains(resposta, "precisa informar o endereço")
        self.psicologo.refresh_from_db()
        self.assertFalse(self.psicologo.cadastro_completo)

    def test_quem_atende_so_online_termina_sem_a_pergunta_do_endereco(self):
        self.responder_quem_e()
        self.responder_regime()
        resposta = self.responder_atendimento(atende_presencial="", atende_online="on")
        self.assertRedirects(resposta, reverse("painel"), fetch_redirect_response=False)
        self.psicologo.refresh_from_db()
        self.assertTrue(self.psicologo.cadastro_completo)

    def test_ninguem_conclui_pulando_pergunta_pela_barra_de_endereco(self):
        self.assertRedirects(self.responder_clinica(), self.passo(1), fetch_redirect_response=False)
        self.responder_quem_e()
        self.assertRedirects(self.responder_clinica(), self.passo(3), fetch_redirect_response=False)
        self.psicologo.refresh_from_db()
        self.assertFalse(self.psicologo.cadastro_completo)

    def test_passo_inexistente_da_404(self):
        self.assertEqual(self.client.get(self.passo(9)).status_code, 404)


class SistemaTrancado(TransactionTestCase):
    def setUp(self):
        criar_conta_e_comecar_o_teste(self.client)

    def test_qualquer_tela_volta_para_o_quiz(self):
        for nome in ["painel", "pacientes:lista", "atendimentos:agenda", "financeiro:mes", "contas:perfil"]:
            with self.subTest(tela=nome):
                self.assertRedirects(self.client.get(reverse(nome)), reverse("contas:quiz", args=[1]),
                                     fetch_redirect_response=False)

    def test_sair_continua_funcionando(self):
        self.assertEqual(self.client.post(reverse("contas:sair")).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_cadastro_concluido_libera_as_telas(self):
        self.client.post(reverse("contas:quiz", args=[1]),
                         {"nome_completo": "Ana Ribeiro", "cpf": "52998224725", "telefone": "31988887777"})
        self.client.post(reverse("contas:quiz", args=[2]), {"regime": "PF", "cnpj": "", "razao_social": ""})
        self.client.post(reverse("contas:quiz", args=[3]), {"abordagens": ["Gestalt-terapia"], "atende_online": "on"})
        resposta = self.client.get(reverse("painel"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Teste grátis")  # o aviso de prazo, no alto das telas
