"""Entrar, sair e editar o próprio perfil."""

from django.test import TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo

SENHA = "senha-de-teste-123"


class BaseConta(TransactionTestCase):
    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.conta@exemplo.com", password=SENHA, nome_completo="Ana Ribeiro",
            cpf="11111111111", telefone="31988887777", crp_regiao="04", crp_numero="303030")
        self.bruno = Psicologo.objects.create_user(
            email="bruno.conta@exemplo.com", password=SENHA, nome_completo="Bruno Carvalho",
            cpf="22222222222", telefone="31988887777", crp_regiao="04", crp_numero="404040")


class EntrarESair(BaseConta):
    def test_login_leva_ao_painel(self):
        resposta = self.client.post(reverse("contas:entrar"),
                                    {"username": self.ana.email, "password": SENHA})
        self.assertRedirects(resposta, reverse("painel"), fetch_redirect_response=False)

    def test_senha_errada_nao_entra(self):
        resposta = self.client.post(reverse("contas:entrar"),
                                    {"username": self.ana.email, "password": "errada"})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "incorretos")

    def test_sair_funciona(self):
        """Regressão da ADR-046.

        Revogar `django_session` de `hamilton_app` quebrou o logout: `session.flush()` apaga a
        linha da sessão *durante* a view, já sob o papel que perdeu a permissão. A resposta era
        500. A correção foi `@dispensa_escopo` (ver `core/escopo.py`), e este teste é o que
        impede o conserto de se perder na próxima mexida no middleware.
        """
        self.client.login(username=self.ana.email, password=SENHA)
        resposta = self.client.post(reverse("contas:sair"))
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(self.client.get(reverse("painel")).status_code, 302)

    def test_sair_nao_deixa_a_sessao_para_tras(self):
        from django.contrib.sessions.models import Session

        self.client.login(username=self.ana.email, password=SENHA)
        self.client.get(reverse("painel"))
        self.assertEqual(Session.objects.count(), 1)
        self.client.post(reverse("contas:sair"))
        self.assertEqual(Session.objects.count(), 0, "A sessão sobreviveu ao logout.")


class Perfil(BaseConta):
    def test_o_perfil_carrega_o_proprio_psicologo(self):
        self.client.login(username=self.ana.email, password=SENHA)
        resposta = self.client.get(reverse("contas:perfil"))
        self.assertContains(resposta, "Ana Ribeiro")
        self.assertNotContains(resposta, "Bruno Carvalho")

    def test_editar_o_perfil_grava(self):
        self.client.login(username=self.ana.email, password=SENHA)
        # Os padrões de atendimento (C-03) vão junto: o perfil é um formulário só, e um POST sem
        # eles seria recusado por campo obrigatório — o teste acusaria um defeito que não existe.
        self.client.post(reverse("contas:perfil"), {
            "nome_completo": "Ana Ribeiro Souza", "email": self.ana.email, "cpf": "11111111111",
            "telefone": "31999990000", "crp_regiao": "04", "crp_numero": "303030",
            "atende_presencial": "on", "regime": "PF", "cnpj": "", "crp_empresa": "",
            "duracao_sessao": "50", "tipo_vencimento_mensalidade": "DIA_FIXO", "dia_vencimento_mensalidade": "10"})
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.nome_completo, "Ana Ribeiro Souza")

    def test_cpf_de_outra_conta_vira_mensagem_no_campo_e_nao_erro(self):
        # Sob o escopo da Ana, o RLS esconde o Bruno: o formulário não tem como saber. Quem recusa é o banco.
        self.client.login(username=self.ana.email, password=SENHA)
        resposta = self.client.post(reverse("contas:perfil"), {
            "nome_completo": "Ana Ribeiro", "email": self.ana.email, "cpf": "22222222222",
            "telefone": "31999990000", "crp_regiao": "04", "crp_numero": "303030",
            "atende_presencial": "on", "regime": "PF", "cnpj": "", "crp_empresa": "",
            "duracao_sessao": "50", "tipo_vencimento_mensalidade": "DIA_FIXO", "dia_vencimento_mensalidade": "10"})
        self.assertContains(resposta, "Já existe uma conta com este CPF")
        self.assertNotContains(resposta, "Perfil atualizado")
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.cpf, "11111111111")

    def test_pessoa_juridica_sem_cnpj_e_recusada(self):
        """ADR-067: o regime decide os recursos fiscais adiante. PJ sem CNPJ deixaria a escolha no ar."""
        self.client.login(username=self.ana.email, password=SENHA)
        resposta = self.client.post(reverse("contas:perfil"), {
            "nome_completo": "Ana", "email": self.ana.email, "cpf": "11111111111",
            "telefone": "31999990000", "crp_regiao": "04", "crp_numero": "303030",
            "atende_presencial": "on", "regime": "PJ", "cnpj": "", "crp_empresa": "",
            "duracao_sessao": "50", "tipo_vencimento_mensalidade": "DIA_FIXO", "dia_vencimento_mensalidade": "10"})
        self.assertContains(resposta, "precisa do CNPJ")

    def test_dados_da_clinica_gravam_com_a_mascara_que_a_tela_manda(self):
        """ADR-066: o navegador manda formatado; o banco guarda número puro."""
        self.client.login(username=self.ana.email, password=SENHA)
        self.client.post(reverse("contas:perfil"), {
            "nome_completo": "Ana", "email": self.ana.email, "cpf": "111.111.111-11",
            "telefone": "(31) 99999-0000", "crp_regiao": "04", "crp_numero": "303030",
            "atende_presencial": "on", "regime": "PJ", "cnpj": "11.222.333/0001-81", "razao_social": "Ana Ribeiro Psicologia Ltda",
            "crp_empresa": "", "nome_clinica": "Consultório da Ana", "telefone_clinica": "(31) 3333-4444",
            "cep": "30140-071", "logradouro": "Rua da Bahia", "numero": "1200", "complemento": "sala 5",
            "bairro": "Lourdes", "cidade": "Belo Horizonte", "uf": "MG",
            "duracao_sessao": "50", "tipo_vencimento_mensalidade": "DIA_FIXO", "dia_vencimento_mensalidade": "10"})
        self.ana.refresh_from_db()
        self.assertEqual(
            (self.ana.cpf, self.ana.telefone, self.ana.cnpj, self.ana.cep, self.ana.telefone_clinica),
            ("11111111111", "31999990000", "11222333000181", "30140071", "3133334444"))
        self.assertEqual((self.ana.nome_clinica, self.ana.cidade), ("Consultório da Ana", "Belo Horizonte"))

    def test_pessoa_fisica_com_cnpj_e_recusado(self):
        self.client.login(username=self.ana.email, password=SENHA)
        resposta = self.client.post(reverse("contas:perfil"), {
            "nome_completo": "Ana", "email": self.ana.email, "cpf": "11111111111",
            "telefone": "31999990000", "crp_regiao": "04", "crp_numero": "303030",
            "atende_presencial": "on", "regime": "PF", "cnpj": "11222333000181", "crp_empresa": "",
            "duracao_sessao": "50", "tipo_vencimento_mensalidade": "DIA_FIXO", "dia_vencimento_mensalidade": "10"})
        self.assertContains(resposta, "não tem CNPJ")
