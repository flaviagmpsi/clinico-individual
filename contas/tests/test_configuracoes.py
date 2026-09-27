"""Configurações da conta (ADR-100): despesas ligáveis, e a troca de regime com data."""

from datetime import date, timedelta

from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from contas.models import MudancaDeRegime, Psicologo
from core import contexto

SENHA = "senha-de-teste-123"


class Base(TransactionTestCase):
    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.config@exemplo.com", password=SENHA, nome_completo="Ana Ribeiro", cpf="11111111111",
            telefone="31988887777", crp_regiao="04", crp_numero="515151")
        self.assertTrue(self.client.login(username=self.ana.email, password=SENHA))
        self.rota = reverse("contas:configuracoes")
        self.hoje = timezone.localdate()


class Despesas(Base):
    def test_desligar_esconde_as_abas_e_tranca_as_telas_sem_apagar_nada(self):
        self.client.post(self.rota, {})  # sem o campo marcado = desligado
        self.ana.refresh_from_db()
        self.assertFalse(self.ana.usa_despesas)

        mes = self.client.get(reverse("financeiro:mes"))
        self.assertNotContains(mes, reverse("financeiro:despesas"))
        self.assertContains(mes, "Controlar despesas")  # o caminho de volta fica à vista
        for nome in ["financeiro:despesas", "financeiro:fluxo", "financeiro:despesa_nova"]:
            with self.subTest(tela=nome):
                self.assertRedirects(self.client.get(reverse(nome)), self.rota, fetch_redirect_response=False)

    def test_religar_devolve_as_abas(self):
        self.client.post(self.rota, {})
        self.client.post(self.rota, {"usa_despesas": "on"})
        self.ana.refresh_from_db()
        self.assertTrue(self.ana.usa_despesas)
        self.assertContains(self.client.get(reverse("financeiro:mes")), reverse("financeiro:despesas"))
        self.assertEqual(self.client.get(reverse("financeiro:despesas")).status_code, 200)


class TrocaDeRegime(Base):
    def virar_pj(self, **ajustes):
        dados = {"acao": "regime", "vigente_desde": self.hoje.isoformat(), "cnpj": "11.222.333/0001-81",
                 "razao_social": "Ana Ribeiro Psicologia Ltda", "crp_empresa": ""}
        dados.update(ajustes)
        return self.client.post(self.rota, dados)

    def test_de_pf_para_pj_pede_cnpj_e_razao_social(self):
        resposta = self.client.get(self.rota)
        self.assertContains(resposta, "Mudar para pessoa jurídica")
        self.assertContains(resposta, 'name="cnpj"')

        self.assertEqual(self.virar_pj(cnpj="", razao_social="").status_code, 200)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.regime, "PF")

        self.assertEqual(self.virar_pj().status_code, 302)
        self.ana.refresh_from_db()
        self.assertEqual((self.ana.regime, self.ana.cnpj, self.ana.razao_social),
                         ("PJ", "11222333000181", "Ana Ribeiro Psicologia Ltda"))

    def test_a_troca_guarda_a_data_e_o_passado_continua_como_era(self):
        amanha = self.hoje + timedelta(days=1)
        self.virar_pj(vigente_desde=amanha.isoformat())
        with contexto.como(self.ana.pk):
            mudanca = MudancaDeRegime.objects.get()
        self.assertEqual((mudanca.regime_anterior, mudanca.regime_novo, mudanca.vigente_desde), ("PF", "PJ", amanha))
        self.ana.refresh_from_db()
        # o que aconteceu antes da data continua sendo pessoa física; do dia em diante, jurídica
        self.assertEqual(self.ana.regime_em(self.hoje), "PF")
        self.assertEqual(self.ana.regime_em(self.hoje - timedelta(days=30)), "PF")
        self.assertEqual(self.ana.regime_em(amanha), "PJ")

    def test_sem_mudanca_nenhuma_o_regime_de_hoje_vale_para_todo_o_passado(self):
        self.assertEqual(self.ana.regime_em(date(2020, 1, 1)), "PF")

    def test_a_troca_nao_vale_para_tras(self):
        resposta = self.virar_pj(vigente_desde=(self.hoje - timedelta(days=1)).isoformat())
        self.assertContains(resposta, "vale de hoje em diante")
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.regime, "PF")

    def test_voltar_para_pf_limpa_os_dados_da_empresa(self):
        self.virar_pj()
        resposta = self.client.get(self.rota)
        self.assertContains(resposta, "Mudar para pessoa física")
        self.assertNotContains(resposta, 'name="cnpj"')  # não há o que pedir para voltar

        self.client.post(self.rota, {"acao": "regime", "vigente_desde": self.hoje.isoformat()})
        self.ana.refresh_from_db()
        self.assertEqual((self.ana.regime, self.ana.cnpj, self.ana.razao_social), ("PF", "", ""))
        with contexto.como(self.ana.pk):
            self.assertEqual(MudancaDeRegime.objects.count(), 2)

    def test_o_historico_aparece_na_tela_e_nao_se_altera(self):
        self.virar_pj()
        self.assertContains(self.client.get(self.rota), "Pessoa física → Pessoa jurídica")
        with contexto.como(self.ana.pk):
            mudanca = MudancaDeRegime.objects.get()
            for acao in (lambda: mudanca.save(), lambda: mudanca.delete()):
                with self.subTest(acao=acao):
                    with self.assertRaises(Exception):
                        acao()
            self.assertEqual(MudancaDeRegime.objects.count(), 1)

    def test_a_mudanca_de_um_nao_aparece_para_outro(self):
        self.virar_pj()
        bruno = Psicologo.objects.create_user(
            email="bruno.config@exemplo.com", password=SENHA, nome_completo="Bruno", cpf="22222222222",
            telefone="31988887777", crp_regiao="04", crp_numero="525252")
        with contexto.como(bruno.pk):
            self.assertEqual(MudancaDeRegime.objects.count(), 0)
        self.assertEqual(bruno.regime_em(self.hoje), "PF")
