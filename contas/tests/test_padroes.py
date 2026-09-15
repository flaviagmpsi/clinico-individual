"""Padrões de atendimento no perfil (C-03) e a herança visível no cadastro (C-04).

ADR-025, "configura uma vez, ajusta na exceção": o psicólogo responde uma vez quanto dura a sessão e em que dia
vence a mensalidade (ADR-059), e o sistema propõe esses valores dali em diante. "Cobro falta" saiu com a
ADR-060: a escolha agora é feita em cada falta. Estes testes guardam os padrões de fábrica, a gravação pela tela
e — o que é fácil de perder numa refatoração — que o valor herdado **diz de onde veio**.

`TransactionTestCase` pelo motivo de sempre nas telas: o middleware usa `SET LOCAL ROLE`.
"""

from django.test import TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo

SENHA = "senha-de-teste-123"


class PadroesDoPerfil(TransactionTestCase):
    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.padroes@exemplo.com", password=SENHA, nome_completo="Ana Padrões",
            cpf="11111111111", telefone="31988887777", crp_regiao="04", crp_numero="818181")

    def dados_do_perfil(self, **mudancas):
        dados = {
            "nome_completo": "Ana Padrões", "email": self.ana.email, "cpf": "11111111111",
            "telefone": "31988887777", "crp_regiao": "04", "crp_numero": "818181",
            "regime": "PF", "cnpj": "", "crp_empresa": "",
            "duracao_sessao": "50", "dia_vencimento_mensalidade": "10",
        }
        dados.update(mudancas)
        return dados

    def test_padroes_de_fabrica(self):
        self.assertEqual(self.ana.duracao_sessao, 50)
        self.assertEqual(self.ana.dia_vencimento_mensalidade, 10)

    def test_editar_os_padroes_pela_tela_grava(self):
        self.client.login(username=self.ana.email, password=SENHA)
        self.client.post(reverse("contas:perfil"), self.dados_do_perfil(duracao_sessao="45", dia_vencimento_mensalidade="5"))
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.duracao_sessao, 45)
        self.assertEqual(self.ana.dia_vencimento_mensalidade, 5)

    def test_valores_fora_da_faixa_sao_recusados(self):
        self.client.login(username=self.ana.email, password=SENHA)
        for campo, valor in [("duracao_sessao", "5"), ("dia_vencimento_mensalidade", "32")]:
            with self.subTest(campo=campo):
                resposta = self.client.post(reverse("contas:perfil"), self.dados_do_perfil(**{campo: valor}))
                self.assertEqual(resposta.status_code, 200)
        self.ana.refresh_from_db()
        self.assertEqual((self.ana.duracao_sessao, self.ana.dia_vencimento_mensalidade), (50, 10))

    def test_cadastro_de_paciente_herda_o_dia_e_diz_de_onde_veio(self):
        """C-04: o campo vem preenchido com o padrão do perfil **e** explica por quê."""
        self.ana.dia_vencimento_mensalidade = 20
        self.ana.save()
        self.client.login(username=self.ana.email, password=SENHA)
        resposta = self.client.get(reverse("pacientes:novo"))
        self.assertContains(resposta, "Padrão do seu perfil: dia 20")
        self.assertContains(resposta, 'value="20"')
