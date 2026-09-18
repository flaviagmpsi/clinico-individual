"""A anamnese: sub-aba opcional da ficha do paciente (ADR-085).

Opcional de verdade — abrir e salvar em branco não grava nada —, editável, auditada sem o conteúdo, isolada por
psicólogo, e protege o paciente contra exclusão.
"""

import json

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo
from core import contexto, db
from core.models import RegistroAuditoria
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente, excluir_paciente
from prontuarios.models import Anamnese

SENHA = "senha-de-teste-123"


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


class AnamneseDoPaciente(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.anamnese@exemplo.com", "11111111111", "707070")
        self.bruno = criar_psicologo("bruno.anamnese@exemplo.com", "22222222222", "717171")
        with contexto.como(self.ana.pk):
            self.marcos = Paciente(nome="Marcos Anamnese")
            cadastrar_paciente(self.marcos)
        with contexto.como(self.bruno.pk):
            self.carla = Paciente(nome="Carla Anamnese")
            cadastrar_paciente(self.carla)
            Anamnese.objects.create(paciente=self.carla, queixa_principal="Queixa da Carla.")

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def rota(self, paciente=None):
        return reverse("prontuarios:anamnese", args=[(paciente or self.marcos).pk])

    def test_exige_login_e_nao_abre_a_de_outro_psicologo(self):
        self.assertEqual(self.client.get(self.rota()).status_code, 302)
        self.entrar(self.ana)
        self.assertEqual(self.client.get(self.rota(self.carla)).status_code, 404)
        self.assertEqual(self.client.post(self.rota(self.carla), {"queixa_principal": "Intrusão."}).status_code, 404)
        self.assertEqual(Anamnese.objetos_todos.get(paciente=self.carla).queixa_principal, "Queixa da Carla.")

    def test_e_opcional_abrir_e_salvar_em_branco_nao_grava_nada(self):
        self.entrar(self.ana)
        resposta = self.client.get(self.rota())
        self.assertContains(resposta, "opcional")
        self.assertContains(resposta, "Queixa principal")
        self.assertContains(resposta, "não entra no prontuário")
        self.client.post(self.rota(), {"queixa_principal": "   "})
        self.assertFalse(Anamnese.objetos_todos.filter(paciente=self.marcos).exists())

    def test_salva_edita_e_a_trilha_nao_guarda_o_conteudo(self):
        self.entrar(self.ana)
        self.client.post(self.rota(), {"queixa_principal": "Conteúdo sigiloso da queixa.", "expectativas": "Dormir."})
        anamnese = Anamnese.objetos_todos.get(paciente=self.marcos)
        self.assertEqual((anamnese.preenchidos, anamnese.psicologo_id), (2, self.ana.pk))
        self.client.post(self.rota(), {"queixa_principal": "Queixa revista.", "expectativas": "Dormir."})
        anamnese.refresh_from_db()
        self.assertEqual(anamnese.queixa_principal, "Queixa revista.")  # edita-se, ao contrário do registro de sessão
        self.assertEqual(Anamnese.objetos_todos.filter(paciente=self.marcos).count(), 1)
        self.assertContains(self.client.get(self.rota()), "Queixa revista.")
        trilha = RegistroAuditoria.objetos_todos.filter(alvo="prontuarios.anamnese", titular_id=self.marcos.pk)
        self.assertEqual({r.acao for r in trilha}, {"CRIAR", "ALTERAR", "VER"})
        self.assertNotIn("sigiloso", json.dumps([r.campos for r in trilha]))

    def test_paciente_com_anamnese_nao_e_apagado(self):
        with contexto.como(self.ana.pk):
            excluir_paciente(Paciente.objects.get(pk=cadastrar_e_devolver("Sem Anamnese")))
            Anamnese.objects.create(paciente=self.marcos, queixa_principal="Queixa.")
            with self.assertRaises(ValidationError):
                excluir_paciente(self.marcos)

    def test_sql_cru_so_devolve_a_anamnese_do_dono(self):
        if connection.vendor != "postgresql":
            self.skipTest("RLS exige PostgreSQL.")
        with contexto.como(self.ana.pk):
            Anamnese.objects.create(paciente=self.marcos, queixa_principal="Queixa do Marcos.")
        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.ana.pk)
            with connection.cursor() as cursor:
                cursor.execute("SELECT queixa_principal FROM prontuarios_anamnese")
                self.assertEqual(cursor.fetchall(), [("Queixa do Marcos.",)])


def cadastrar_e_devolver(nome: str) -> int:
    paciente = Paciente(nome=nome)
    cadastrar_paciente(paciente)
    return paciente.pk
