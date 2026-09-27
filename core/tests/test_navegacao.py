"""A navegação (ADR-088): a barra com os nomes das abas, o caminho no topo e as sub-abas que acompanham o paciente."""

from django.test import TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo
from core import contexto
from core.templatetags.navegacao import raiz_da_secao
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente

class Rota:
    """Uma rota resolvida de mentira, para exercitar `raiz_da_secao` sem passar por uma view."""

    def __init__(self, app_name, url_name):
        self.app_name, self.url_name = app_name, url_name


class Pedido:
    def __init__(self, rota):
        self.resolver_match = rota


SENHA = "senha-de-teste-123"


class Navegacao(TransactionTestCase):
    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.nav@exemplo.com", password=SENHA, nome_completo="Ana Nav", cpf="11111111111",
            telefone="31988887777", crp_regiao="04", crp_numero="121212")
        with contexto.como(self.ana.pk):
            self.marcos = Paciente(nome="Marcos Nav")
            cadastrar_paciente(self.marcos)
        self.assertTrue(self.client.login(username=self.ana.email, password=SENHA))

    def test_a_barra_tem_o_nome_de_cada_aba_e_marca_a_secao(self):
        resposta = self.client.get(reverse("financeiro:mes"))
        for nome in ["Painel", "Pacientes", "Agenda", "Horários", "Prontuários", "Financeiro", "Estatísticas",
                     "Documentos", "Meu perfil", "Sair"]:
            with self.subTest(nome=nome):
                self.assertContains(resposta, f'<span class="nome">{nome}</span>')
        self.assertContains(resposta, 'title="Financeiro"\n     class="ativo"')

    def test_o_caminho_no_topo_leva_a_raiz_da_secao_e_nomeia_a_pagina(self):
        resposta = self.client.get(reverse("pacientes:detalhe", args=[self.marcos.pk]))
        self.assertContains(resposta, f'<a href="{reverse("pacientes:lista")}">Pacientes</a>')
        self.assertContains(resposta, '<span class="separa">›</span>Marcos Nav')
        self.assertContains(self.client.get(reverse("financeiro:fluxo")), '<span class="separa">›</span>Fluxo de caixa')

    def test_raiz_de_cada_secao(self):
        self.assertEqual(raiz_da_secao(Pedido(Rota("pacientes", "detalhe"))), reverse("pacientes:lista"))
        self.assertEqual(raiz_da_secao(Pedido(Rota("", "estatisticas"))), reverse("estatisticas"))
        self.assertEqual(raiz_da_secao(Pedido(Rota("", "painel"))), reverse("painel"))
        self.assertEqual(raiz_da_secao(Pedido(Rota("desconhecido", "x"))), "")
        self.assertEqual(raiz_da_secao(Pedido(None)), "")

    def test_as_sub_abas_do_paciente_acompanham_o_paciente(self):
        abas = [reverse("pacientes:detalhe", args=[self.marcos.pk]),
                reverse("prontuarios:anamnese", args=[self.marcos.pk]),
                reverse("prontuarios:lista") + f"?paciente={self.marcos.pk}",
                reverse("documentos:prontuario", args=[self.marcos.pk]),
                reverse("documentos:aba") + f"?paciente={self.marcos.pk}"]
        for rota in abas:
            with self.subTest(rota=rota):
                resposta = self.client.get(rota)
                self.assertEqual(resposta.status_code, 200)
                for outra in abas:
                    self.assertContains(resposta, f'href="{outra}"')
                self.assertContains(resposta, "Registros de sessão")
                self.assertContains(resposta, "Prontuário geral")
        # Sem paciente, a lista de registros e a aba de documentos não mostram as sub-abas de ninguém.
        self.assertNotContains(self.client.get(reverse("prontuarios:lista")), '<ul class="nav nav-tabs">')
        self.assertNotContains(self.client.get(reverse("documentos:aba")), '<ul class="nav nav-tabs">')

    def test_agenda_e_horarios_sao_uma_secao_so(self):
        """ADR-098: a barra tem uma entrada, e as duas telas trazem as mesmas sub-abas."""
        agenda, horarios = reverse("atendimentos:agenda"), reverse("agenda:horarios")
        for rota in (agenda, horarios):
            with self.subTest(rota=rota):
                resposta = self.client.get(rota)
                self.assertEqual(resposta.status_code, 200)
                self.assertContains(resposta, f'href="{agenda}"')
                self.assertContains(resposta, f'href="{horarios}"')
                self.assertContains(resposta, "Meus horários")
        # a barra lateral não tem mais a entrada separada, e os horários ficam dentro da agenda
        self.assertTrue(horarios.startswith(agenda))
        self.assertEqual(self.client.get(agenda).content.decode().count('<span class="nome">Horários</span>'), 0)
        # quem está nos horários tem a agenda como raiz da seção
        self.assertEqual(raiz_da_secao(Pedido(Rota("agenda", "horarios"))), agenda)

    def test_a_rota_antiga_dos_horarios_continua_levando_la(self):
        self.assertRedirects(self.client.get("/horarios/"), reverse("agenda:horarios"))

    def test_interacao_e_global_e_a_pagina_nao_depende_dela(self):
        """ADR-091: os três refinamentos moram no tema e no base — toda tela os herda, e nenhum esconde conteúdo."""
        resposta = self.client.get(reverse("pacientes:lista"))
        html = resposta.content.decode()
        for trecho in ["@keyframes entrar", "prefers-reduced-motion: reduce", "--tinta-fundo-leve", "linha-clicavel",
                       ".card:has(.stretched-link)"]:
            with self.subTest(trecho=trecho):
                self.assertIn(trecho, html)
        # A entrada é animação CSS com `backwards`: o estado normal do conteúdo é visível, com ou sem JavaScript.
        self.assertIn("animation: entrar var(--t-entrada) backwards", html)
        # A linha do paciente continua tendo um link de verdade: o clique na linha é conforto, não requisito.
        self.assertContains(resposta, f'<a href="{reverse("pacientes:detalhe", args=[self.marcos.pk])}"')

    def test_os_cards_de_documentos_sao_de_navegacao(self):
        resposta = self.client.get(reverse("documentos:aba"))
        self.assertGreaterEqual(resposta.content.decode().count("stretched-link\">Abrir"), 9)

