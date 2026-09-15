"""As telas do caso, vistas por dois psicólogos ao mesmo tempo.

`test_caso.py` prova que o **modelo** não mistura psicólogos. Este arquivo prova que as **telas**
usam o modelo — outra coisa. Uma view nova que buscasse o responsável pelo id sem passar pelo
manager do dono passaria em todos os testes de modelo e vazaria aqui.

`TransactionTestCase` pelo mesmo motivo de `test_telas.py`: o middleware troca o papel do banco
com `SET LOCAL ROLE`, que se prende à transação.
"""

from decimal import Decimal

from django.test import TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo
from core import contexto
from pacientes.models import Caso, CondicaoCobranca, Paciente, ResponsavelLegal
from pacientes.servicos import cadastrar_paciente, caso_individual_de, criar_caso_coletivo

SENHA = "senha-de-teste-123"


class BaseTelasCaso(TransactionTestCase):
    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.telacaso@exemplo.com", password=SENHA, nome_completo="Ana",
            cpf="11111111111", telefone="31988887777", crp_regiao="04", crp_numero="616161")
        self.bruno = Psicologo.objects.create_user(
            email="bruno.telacaso@exemplo.com", password=SENHA, nome_completo="Bruno",
            cpf="22222222222", telefone="31988887777", crp_regiao="04", crp_numero="626262")
        with contexto.como(self.ana.pk):
            self.maria = Paciente(nome="Maria Ana")
            cadastrar_paciente(self.maria, valor=Decimal("200"))
            self.joao = Paciente(nome="João Ana")
            cadastrar_paciente(self.joao)
            self.responsavel = ResponsavelLegal.objects.create(paciente=self.maria, nome="Mãe da Maria")
        with contexto.como(self.bruno.pk):
            self.carla = Paciente(nome="Carla Bruno")
            cadastrar_paciente(self.carla)
            self.pedro = Paciente(nome="Pedro Bruno")
            cadastrar_paciente(self.pedro)
            self.casal_do_bruno = criar_caso_coletivo([self.carla, self.pedro], descricao="Carla e Pedro")

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))


class RotasNovasExigemLogin(BaseTelasCaso):
    def test_nenhuma_rota_do_caso_abre_sem_login(self):
        for nome, args in [
            ("pacientes:atendimento", [self.maria.pk]),
            ("pacientes:responsavel_novo", [self.maria.pk]),
            ("pacientes:responsavel_editar", [self.responsavel.pk]),
            ("pacientes:responsavel_excluir", [self.responsavel.pk]),
            ("pacientes:caso_novo", []),
            ("pacientes:caso", [self.casal_do_bruno.pk]),
            ("pacientes:caso_excluir", [self.casal_do_bruno.pk]),
        ]:
            with self.subTest(tela=nome):
                resposta = self.client.get(reverse(nome, args=args))
                self.assertEqual(resposta.status_code, 302)
                self.assertIn(reverse("contas:entrar"), resposta["Location"])


class RotasNovasNaoAtravessamAFronteira(BaseTelasCaso):
    def test_ana_nao_alcanca_nada_do_bruno_pela_url(self):
        self.entrar(self.ana)
        for nome, args in [
            ("pacientes:atendimento", [self.carla.pk]),
            ("pacientes:responsavel_novo", [self.carla.pk]),
            ("pacientes:caso", [self.casal_do_bruno.pk]),
            ("pacientes:caso_excluir", [self.casal_do_bruno.pk]),
        ]:
            with self.subTest(tela=nome):
                self.assertEqual(self.client.get(reverse(nome, args=args)).status_code, 404)

    def test_bruno_nao_edita_nem_remove_responsavel_da_ana(self):
        self.entrar(self.bruno)
        editar = reverse("pacientes:responsavel_editar", args=[self.responsavel.pk])
        excluir = reverse("pacientes:responsavel_excluir", args=[self.responsavel.pk])
        self.assertEqual(self.client.get(editar).status_code, 404)
        self.assertEqual(self.client.post(editar, {"nome": "Trocado", "guarda": "NAO_INFORMADA"}).status_code, 404)
        self.assertEqual(self.client.post(excluir).status_code, 404)
        self.assertEqual(ResponsavelLegal.objetos_todos.get(pk=self.responsavel.pk).nome, "Mãe da Maria")

    def test_bruno_nao_apaga_o_casal_pelo_post_da_ana(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("pacientes:caso_excluir", args=[self.casal_do_bruno.pk]))
        self.assertEqual(resposta.status_code, 404)
        self.assertTrue(Caso.objetos_todos.filter(pk=self.casal_do_bruno.pk).exists())

    def test_formulario_de_casal_so_oferece_os_proprios_pacientes(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("pacientes:caso_novo"))
        self.assertContains(resposta, "Maria Ana")
        self.assertNotContains(resposta, "Carla Bruno")

    def test_nao_da_para_por_paciente_alheio_no_casal(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("pacientes:caso_novo"),
                                    {"descricao": "Invasão", "pacientes": [self.maria.pk, self.carla.pk]})
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(Caso.objetos_todos.filter(descricao="Invasão").exists())


class CadastroComCobranca(BaseTelasCaso):
    def test_cadastro_com_valor_cria_caso_e_condicao(self):
        self.entrar(self.ana)
        self.client.post(reverse("pacientes:novo"), {
            "nome": "Nova Paciente", "uf": "",
            "cobranca-modalidade": "MENSAL", "cobranca-valor": "700", "cobranca-dia_vencimento": "10",
        }, follow=True)
        with contexto.como(self.ana.pk):
            nova = Paciente.objects.get(nome="Nova Paciente")
            condicao = caso_individual_de(nova).condicao_vigente()
        self.assertEqual(condicao.modalidade, CondicaoCobranca.Modalidade.MENSAL)
        self.assertEqual(condicao.valor, Decimal("700"))

    def test_mensalidade_sem_vencimento_nao_cadastra_e_explica(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("pacientes:novo"), {
            "nome": "Sem Vencimento", "uf": "",
            "cobranca-modalidade": "MENSAL", "cobranca-valor": "700",
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Mensalidade precisa do dia de vencimento")
        self.assertFalse(Paciente.objetos_todos.filter(nome="Sem Vencimento").exists())

    def test_cadastro_sem_cobranca_continua_funcionando(self):
        """ADR-012: quem ainda não combinou valor não é barrado."""
        self.entrar(self.ana)
        self.client.post(reverse("pacientes:novo"), {"nome": "Sem Valor", "uf": ""}, follow=True)
        with contexto.como(self.ana.pk):
            caso = caso_individual_de(Paciente.objects.get(nome="Sem Valor"))
            self.assertIsNotNone(caso)
            self.assertIsNone(caso.condicao_vigente())


class PagadorPelaTela(BaseTelasCaso):
    def test_marcar_outra_pessoa_registra_o_pagador_de_fora(self):
        self.entrar(self.ana)
        self.client.post(reverse("pacientes:atendimento", args=[self.maria.pk]), {
            "outra_pessoa": "on", "pagador_nome": "Pai da Maria", "pagador_cpf": "52998224725"})
        with contexto.como(self.ana.pk):
            caso = caso_individual_de(self.maria)
        self.assertIsNone(caso.pagador_paciente_id)
        self.assertEqual(caso.pagador_nome, "Pai da Maria")

    def test_desmarcar_volta_para_o_proprio_paciente(self):
        self.entrar(self.ana)
        rota = reverse("pacientes:atendimento", args=[self.maria.pk])
        self.client.post(rota, {"outra_pessoa": "on", "pagador_nome": "Pai da Maria"})
        self.client.post(rota, {"pagador_nome": "Pai da Maria"})
        with contexto.como(self.ana.pk):
            caso = caso_individual_de(self.maria)
        self.assertEqual(caso.pagador_paciente_id, self.maria.pk)
        self.assertEqual(caso.pagador_nome, "")


class ExclusaoComCaso(BaseTelasCaso):
    def test_excluir_paciente_leva_o_caso_individual_junto(self):
        self.entrar(self.ana)
        with contexto.como(self.ana.pk):
            caso_id = caso_individual_de(self.joao).pk
        resposta = self.client.post(reverse("pacientes:excluir", args=[self.joao.pk]))
        self.assertEqual(resposta.status_code, 302)
        self.assertFalse(Paciente.objetos_todos.filter(pk=self.joao.pk).exists())
        self.assertFalse(Caso.objetos_todos.filter(pk=caso_id).exists())

    def test_paciente_em_atendimento_de_casal_nao_e_excluido(self):
        """Apagá-lo alteraria em silêncio o vínculo do outro participante."""
        self.entrar(self.bruno)
        resposta = self.client.post(reverse("pacientes:excluir", args=[self.carla.pk]), follow=True)
        self.assertContains(resposta, "atendimento de casal ou família")
        self.assertTrue(Paciente.objetos_todos.filter(pk=self.carla.pk).exists())


class CasalPelaTela(BaseTelasCaso):
    def test_criar_casal_mantem_os_casos_individuais(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("pacientes:caso_novo"),
                                    {"descricao": "Maria e João", "pacientes": [self.maria.pk, self.joao.pk]})
        self.assertEqual(resposta.status_code, 302)
        with contexto.como(self.ana.pk):
            self.assertEqual(self.maria.casos.count(), 2)
            self.assertIsNotNone(caso_individual_de(self.maria))

    def test_casal_com_um_participante_so_e_recusado(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("pacientes:caso_novo"), {"pacientes": [self.maria.pk]})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "pelo menos dois participantes")

    def test_a_ficha_mostra_o_atendimento_coletivo(self):
        self.entrar(self.bruno)
        resposta = self.client.get(reverse("pacientes:detalhe", args=[self.carla.pk]))
        self.assertContains(resposta, "Carla e Pedro")

    def test_caso_individual_nao_tem_tela_propria(self):
        """ADR-026: a palavra "caso" não aparece no atendimento individual."""
        self.entrar(self.ana)
        with contexto.como(self.ana.pk):
            caso_id = caso_individual_de(self.maria).pk
        resposta = self.client.get(reverse("pacientes:caso", args=[caso_id]))
        self.assertRedirects(resposta, reverse("pacientes:detalhe", args=[self.maria.pk]),
                             fetch_redirect_response=False)
