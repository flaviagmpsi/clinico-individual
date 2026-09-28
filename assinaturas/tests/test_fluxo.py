"""A assinatura (ADR-094): assinar de cara ou testar grátis por 7 dias.

- `EscolhaDoPlano` — a conta recém-criada só tem um lugar para ir; as duas portas; o teste é um por conta.
- `PrazoDoTeste` — o fim do teste é calculado; encerrado, o sistema tranca e o dado fica; assinar destranca.
- `PagamentoSimulado` — só existe fora de produção, e nunca pede dado de cartão.
- `Isolamento` — cada psicólogo enxerga a própria assinatura; conta criada por código não é trancada.
"""

from datetime import timedelta

from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assinaturas import servicos
from assinaturas.models import Assinatura
from contas.models import Psicologo
from core import contexto

SENHA = "senha-de-teste-123"
CONTA = {"email": "cora@exemplo.com", "crp_regiao": "06", "crp_numero": "55555",
         "password1": "uma-senha-bem-longa-123", "password2": "uma-senha-bem-longa-123"}


class ContaNova(TransactionTestCase):
    def setUp(self):
        self.client.post(reverse("contas:criar_conta"), CONTA)
        self.psicologo = Psicologo.objects.get(email=CONTA["email"])

    def assinatura(self):
        with contexto.como(self.psicologo.pk):
            return servicos.assinatura_atual()

    def concluir_quiz(self):
        Psicologo.objects.filter(pk=self.psicologo.pk).update(
            nome_completo="Cora Lima", cpf="52998224725", telefone="11988887777", abordagens=["PSICANALISE"],
            atende_online=True, quiz_concluido_em=timezone.now())


class EscolhaDoPlano(ContaNova):
    def test_conta_recem_criada_so_tem_a_escolha_do_plano_para_ir(self):
        for nome, args in [("painel", []), ("pacientes:lista", []), ("contas:perfil", []), ("contas:quiz", [1])]:
            with self.subTest(tela=nome):
                self.assertRedirects(self.client.get(reverse(nome, args=args)), reverse("assinaturas:plano"),
                                     fetch_redirect_response=False)

    def test_a_tela_oferece_as_duas_portas_e_nao_inventa_preco(self):
        resposta = self.client.get(reverse("assinaturas:plano"))
        self.assertContains(resposta, "Testar grátis por 7 dias")
        self.assertContains(resposta, "Assinar agora")
        self.assertNotContains(resposta, "R$")

    @override_settings(ASSINATURA_VALOR_MENSAL="89,90")
    def test_com_preco_definido_a_tela_mostra(self):
        self.assertContains(self.client.get(reverse("assinaturas:plano")), "R$ 89,90")

    def test_teste_gratis_comeca_sem_dado_de_pagamento_e_leva_ao_quiz(self):
        resposta = self.client.post(reverse("assinaturas:plano"), {"acao": "teste"})
        self.assertRedirects(resposta, reverse("painel"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("painel")), reverse("contas:quiz", args=[1]),
                             fetch_redirect_response=False)
        assinatura = self.assinatura()
        self.assertEqual((assinatura.estado, assinatura.meio), ("TESTE", ""))
        self.assertEqual(assinatura.dias_de_teste_restantes(), 7)

    def test_assinar_agora_leva_ao_pagamento_sem_criar_nada(self):
        resposta = self.client.post(reverse("assinaturas:plano"), {"acao": "assinar"})
        self.assertRedirects(resposta, reverse("assinaturas:pagamento"), fetch_redirect_response=False)
        self.assertIsNone(self.assinatura())

    def test_o_teste_e_um_por_conta(self):
        self.client.post(reverse("assinaturas:plano"), {"acao": "teste"})
        fim = self.assinatura().teste_termina_em
        self.client.post(reverse("assinaturas:plano"), {"acao": "teste"})
        self.assertEqual(self.assinatura().teste_termina_em, fim)
        with contexto.como(self.psicologo.pk):
            self.assertEqual(Assinatura.objects.count(), 1)

    def test_sair_funciona_antes_de_escolher(self):
        self.assertEqual(self.client.post(reverse("contas:sair")).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)


class PrazoDoTeste(ContaNova):
    def setUp(self):
        super().setUp()
        self.client.post(reverse("assinaturas:plano"), {"acao": "teste"})
        self.concluir_quiz()

    def encerrar_o_teste(self):
        Assinatura.objetos_todos.filter(psicologo=self.psicologo).update(
            teste_termina_em=timezone.now() - timedelta(minutes=1))

    def test_o_prazo_e_calculado(self):
        assinatura = self.assinatura()
        agora = timezone.now()
        self.assertTrue(assinatura.em_teste(agora + timedelta(days=6, hours=23)))
        self.assertTrue(assinatura.teste_encerrado(agora + timedelta(days=7, minutes=1)))
        self.assertEqual(assinatura.dias_de_teste_restantes(agora + timedelta(days=6, hours=12)), 1)
        self.assertEqual(assinatura.dias_de_teste_restantes(agora + timedelta(days=8)), 0)

    def test_durante_o_teste_o_sistema_abre_e_o_prazo_fica_a_vista(self):
        resposta = self.client.get(reverse("painel"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "faltam <strong>7 dias</strong>")

    def test_teste_encerrado_tranca_tudo_menos_a_assinatura_e_a_saida(self):
        self.encerrar_o_teste()
        for nome in ["painel", "pacientes:lista", "prontuarios:lista", "contas:perfil"]:
            with self.subTest(tela=nome):
                self.assertRedirects(self.client.get(reverse(nome)), reverse("assinaturas:plano"),
                                     fetch_redirect_response=False)
        resposta = self.client.get(reverse("assinaturas:plano"))
        self.assertContains(resposta, "Seu teste grátis terminou")
        self.assertContains(resposta, "continua guardado")
        self.assertEqual(self.client.post(reverse("contas:sair")).status_code, 302)

    def test_teste_encerrado_nao_da_direito_a_outro(self):
        self.encerrar_o_teste()
        self.client.post(reverse("assinaturas:plano"), {"acao": "teste"})
        self.assertTrue(self.assinatura().teste_encerrado())

    @override_settings(ASSINATURA_SIMULADA=True)
    def test_assinar_depois_do_fim_destranca(self):
        self.encerrar_o_teste()
        self.client.post(reverse("assinaturas:pagamento"), {"meio": "PIX_AUTOMATICO"})
        self.assertEqual(self.client.get(reverse("painel")).status_code, 200)
        self.assertEqual(self.assinatura().estado, "ATIVA")


class PagamentoSimulado(ContaNova):
    @override_settings(ASSINATURA_SIMULADA=True)
    def test_a_tela_so_pergunta_o_meio_e_nunca_pede_cartao(self):
        resposta = self.client.get(reverse("assinaturas:pagamento"))
        self.assertContains(resposta, "Cartão de crédito")
        self.assertContains(resposta, "PIX Automático")
        self.assertContains(resposta, "Ambiente de teste")
        conteudo = resposta.content.decode().lower()
        for proibido in ['name="numero', 'name="cartao', 'name="cvv', "cc-number", 'autocomplete="cc-']:
            self.assertNotIn(proibido, conteudo)

    @override_settings(ASSINATURA_SIMULADA=True)
    def test_pagamento_confirmado_ativa_e_segue_para_o_quiz(self):
        resposta = self.client.post(reverse("assinaturas:pagamento"), {"meio": "CARTAO"})
        self.assertRedirects(resposta, reverse("painel"), fetch_redirect_response=False)
        assinatura = self.assinatura()
        self.assertEqual((assinatura.estado, assinatura.meio), ("ATIVA", "CARTAO"))
        self.assertIsNotNone(assinatura.ativa_desde)
        self.assertRedirects(self.client.get(reverse("painel")), reverse("contas:quiz", args=[1]),
                             fetch_redirect_response=False)

    @override_settings(ASSINATURA_SIMULADA=True)
    def test_meio_desconhecido_nao_ativa(self):
        self.client.post(reverse("assinaturas:pagamento"), {"meio": "BOLETO"})
        self.assertIsNone(self.assinatura())

    @override_settings(ASSINATURA_SIMULADA=False)
    def test_em_producao_o_botao_de_simular_nao_existe_nem_funciona(self):
        self.assertNotContains(self.client.get(reverse("assinaturas:pagamento")), "Simular pagamento")
        self.assertEqual(self.client.post(reverse("assinaturas:pagamento"), {"meio": "CARTAO"}).status_code, 404)
        self.assertIsNone(self.assinatura())


class Isolamento(TransactionTestCase):
    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.assina@exemplo.com", password=SENHA, nome_completo="Ana Ribeiro", cpf="11111111111",
            telefone="31988887777", crp_regiao="04", crp_numero="717171")
        self.bruno = Psicologo.objects.create_user(
            email="bruno.assina@exemplo.com", password=SENHA, nome_completo="Bruno Carvalho", cpf="22222222222",
            telefone="31988887777", crp_regiao="04", crp_numero="727272")

    def test_conta_criada_por_codigo_nao_e_trancada(self):
        self.client.login(username=self.ana.email, password=SENHA)
        self.assertEqual(self.client.get(reverse("painel")).status_code, 200)

    def test_cada_um_enxerga_so_a_propria_assinatura(self):
        with contexto.como(self.ana.pk):
            servicos.comecar_teste()
        with contexto.como(self.bruno.pk):
            self.assertIsNone(servicos.assinatura_atual())
            servicos.ativar(Assinatura.Meio.CARTAO)
        with contexto.como(self.ana.pk):
            self.assertEqual(servicos.assinatura_atual().estado, "TESTE")

    def test_o_teste_vencido_de_um_nao_tranca_o_outro(self):
        with contexto.como(self.ana.pk):
            servicos.comecar_teste(agora=timezone.now() - timedelta(days=8))
        self.client.login(username=self.bruno.email, password=SENHA)
        self.assertEqual(self.client.get(reverse("painel")).status_code, 200)
        self.client.logout()
        self.client.login(username=self.ana.email, password=SENHA)
        self.assertRedirects(self.client.get(reverse("painel")), reverse("assinaturas:plano"),
                             fetch_redirect_response=False)
