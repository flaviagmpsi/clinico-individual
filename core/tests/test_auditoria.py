"""A trilha de auditoria (F-05, ADR-057): o que entra, o que nunca entra, e que ninguém a apaga.

- `OQueEntra` — criar, alterar e excluir pelo model; só os campos que mudaram.
- `OQueNuncaEntra` — valores e nomes. Paciente excluído por engano não sobrevive na trilha (ADR-048).
- `SoAcrescenta` — o model recusa regravar e apagar; o banco também, sob o papel da requisição.
- `PelaTela` — abrir a ficha e o formulário registra visualização; o histórico não atravessa a fronteira.

`TransactionTestCase` onde há papel de banco ou requisição, pelo motivo de sempre: `SET LOCAL` se prende à transação.
"""

import json

from django.db import connection, transaction
from django.db.utils import ProgrammingError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo
from core import contexto, db
from core.models import RegistroAuditoria, RegistroImutavel
from pacientes.models import Paciente, ResponsavelLegal
from pacientes.servicos import cadastrar_paciente, excluir_paciente

SENHA = "senha-de-teste-123"
Acao = RegistroAuditoria.Acao
TABELA = "core_registroauditoria"


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


def trilha(paciente):
    return list(RegistroAuditoria.objetos_todos.filter(titular="pacientes.paciente", titular_id=paciente.pk)
                .order_by("id"))


class BaseAuditoria(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.auditoria@exemplo.com", "11111111111", "717171")
        cls.bruno = criar_psicologo("bruno.auditoria@exemplo.com", "22222222222", "727272")


class OQueEntra(BaseAuditoria):
    def test_cadastrar_registra_a_criacao(self):
        with contexto.como(self.ana.pk):
            maria = Paciente(nome="Maria Trilha")
            cadastrar_paciente(maria)
        self.assertEqual([(r.acao, r.alvo, r.alvo_id) for r in trilha(maria)],
                         [(Acao.CRIAR, "pacientes.paciente", maria.pk)])

    def test_alterar_registra_so_os_campos_que_mudaram(self):
        with contexto.como(self.ana.pk):
            maria = Paciente.objects.create(nome="Maria Trilha")
            maria.telefone = "31999998888"
            maria.medicamento = "Relata uso de sertralina."
            maria.save()
        alteracao = trilha(maria)[-1]
        self.assertEqual(alteracao.acao, Acao.ALTERAR)
        self.assertEqual(alteracao.campos, ["medicamento", "telefone"])
        self.assertEqual(alteracao.campos_legiveis, ["Medicamento em uso", "Telefone"])

    def test_gravar_sem_mudar_nada_nao_registra(self):
        with contexto.como(self.ana.pk):
            maria = Paciente.objects.create(nome="Maria Trilha")
            maria.save()
        self.assertEqual(len(trilha(maria)), 1)

    def test_responsavel_legal_entra_no_historico_do_paciente(self):
        with contexto.como(self.ana.pk):
            rafael = Paciente.objects.create(nome="Rafael Trilha")
            mae = ResponsavelLegal.objects.create(paciente=rafael, nome="Luciana")
            mae.delete()
        self.assertEqual([(r.acao, r.alvo) for r in trilha(rafael)[1:]],
                         [(Acao.CRIAR, "pacientes.responsavellegal"), (Acao.EXCLUIR, "pacientes.responsavellegal")])

    def test_excluir_registra_e_o_registro_sobrevive(self):
        with contexto.como(self.ana.pk):
            joao = Paciente(nome="João Engano")
            cadastrar_paciente(joao)
            pk = joao.pk
            excluir_paciente(joao)
        ultimo = RegistroAuditoria.objetos_todos.filter(titular_id=pk).order_by("id").last()
        self.assertEqual((ultimo.acao, ultimo.alvo_id), (Acao.EXCLUIR, pk))


class OQueNuncaEntra(BaseAuditoria):
    def test_nenhum_valor_nem_nome_vai_para_a_trilha(self):
        with contexto.como(self.ana.pk):
            joao = Paciente.objects.create(nome="João Sigiloso", cpf="52998224725")
            joao.observacoes = "Conteúdo clínico sensível."
            joao.save()
            joao.delete()
        guardado = json.dumps([
            [r.acao, r.alvo, r.titular, r.campos]
            for r in RegistroAuditoria.objetos_todos.filter(psicologo=self.ana)
        ])
        for valor in ["Sigiloso", "52998224725", "sensível"]:
            self.assertNotIn(valor, guardado)


class SoAcrescenta(BaseAuditoria):
    def test_o_model_recusa_regravar_e_apagar(self):
        with contexto.como(self.ana.pk):
            registro = trilha(Paciente.objects.create(nome="Maria Trilha"))[0]
            registro.acao = Acao.VER
            with self.assertRaises(RegistroImutavel):
                registro.save()
            with self.assertRaises(RegistroImutavel):
                registro.delete()

    def test_um_psicologo_nao_ve_a_trilha_do_outro(self):
        with contexto.como(self.bruno.pk):
            Paciente.objects.create(nome="Do Bruno")
        with contexto.como(self.ana.pk):
            self.assertFalse(RegistroAuditoria.objects.exists())


class NoBanco(TransactionTestCase):
    """A terceira camada: RLS e falta de permissão para mudar o passado."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("RLS e permissões exigem PostgreSQL.")
        self.ana = criar_psicologo("ana.auditbanco@exemplo.com", "33333333333", "737373")
        self.bruno = criar_psicologo("bruno.auditbanco@exemplo.com", "44444444444", "747474")
        for psicologo in (self.ana, self.bruno):
            with contexto.como(psicologo.pk):
                Paciente.objects.create(nome=f"Paciente {psicologo.pk}")

    def _como_ana(self, sql):
        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.ana.pk)
            with connection.cursor() as cursor:
                cursor.execute(sql)
                return cursor.fetchall() if cursor.description else None

    def test_sql_cru_so_devolve_a_propria_trilha(self):
        donos = {linha[0] for linha in self._como_ana(f"SELECT DISTINCT psicologo_id FROM {TABELA}")}
        self.assertEqual(donos, {self.ana.pk})

    def test_nem_a_requisicao_autenticada_altera_ou_apaga_o_passado(self):
        for sql in [f"UPDATE {TABELA} SET acao = 'VER'", f"DELETE FROM {TABELA}"]:
            with self.subTest(sql=sql):
                with self.assertRaises(ProgrammingError):
                    self._como_ana(sql)
        self.assertEqual(RegistroAuditoria.objetos_todos.filter(acao=Acao.CRIAR).count(), 2)

    def test_papel_anonimo_nao_le_a_trilha(self):
        with self.assertRaises(ProgrammingError):
            with transaction.atomic():
                db.assumir_papel_da_web()
                with connection.cursor() as cursor:
                    cursor.execute(f"SELECT 1 FROM {TABELA}")


class PelaTela(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.audittela@exemplo.com", "55555555555", "757575")
        self.bruno = criar_psicologo("bruno.audittela@exemplo.com", "66666666666", "767676")
        with contexto.como(self.ana.pk):
            self.maria = Paciente(nome="Maria Tela")
            cadastrar_paciente(self.maria)

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def test_historico_exige_login(self):
        resposta = self.client.get(reverse("pacientes:historico", args=[self.maria.pk]))
        self.assertEqual(resposta.status_code, 302)

    def test_abrir_a_ficha_e_o_formulario_registra_visualizacao(self):
        self.entrar(self.ana)
        self.client.get(reverse("pacientes:detalhe", args=[self.maria.pk]))
        self.client.get(reverse("pacientes:editar", args=[self.maria.pk]))
        self.assertEqual([r.acao for r in trilha(self.maria)], [Acao.CRIAR, Acao.VER, Acao.VER])

    def test_editar_pela_tela_registra_o_campo_e_o_historico_mostra(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("pacientes:editar", args=[self.maria.pk]),
                                    {"nome": "Maria Tela", "telefone": "31999998888"})
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(trilha(self.maria)[-1].campos, ["telefone"])

        historico = self.client.get(reverse("pacientes:historico", args=[self.maria.pk]))
        self.assertContains(historico, "Alterou")
        self.assertContains(historico, "Telefone")
        self.assertNotContains(historico, "31999998888")

    def test_outro_psicologo_nao_ve_o_historico_nem_deixa_rastro(self):
        self.entrar(self.bruno)
        self.assertEqual(self.client.get(reverse("pacientes:historico", args=[self.maria.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("pacientes:detalhe", args=[self.maria.pk])).status_code, 404)
        self.assertEqual([r.acao for r in trilha(self.maria)], [Acao.CRIAR])
