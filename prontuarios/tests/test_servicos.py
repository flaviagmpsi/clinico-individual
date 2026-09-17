"""O prontuário por dentro: pendência, rascunho, confirmação, correção e as travas (ADR-064).

- `Pendencia` — sessão realizada gera um por participante; falta não gera; rascunho continua pendente.
- `CicloDeVida` — rascunho se edita; confirmada não muda; correção cria versão nova com motivo.
- `Protecao` — sessão com prontuário não vira falta nem é excluída; auditoria sem o texto.
- `Isolamento` — ADR-001.
- `NoBanco` — o gatilho recusa alterar versão confirmada, até para o dono do banco; RLS nas duas tabelas.

Datas de setembro de 2026, anteriores ao dia em que o teste roda: consulta só se cadastra no passado.
"""

import json
from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.db.utils import ProgrammingError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from atendimentos import servicos as agenda
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto, db
from core.models import RegistroAuditoria
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente, criar_caso_coletivo
from prontuarios import servicos
from prontuarios.models import Prontuario, VersaoCongelada, VersaoProntuario

REALIZADA = Consulta.Estado.REALIZADA
FALTOU = Consulta.Estado.FALTOU


def momento(dia, hora=10):
    return timezone.make_aware(datetime(2026, 9, dia, hora))


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password="senha-de-teste-123", nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


class BaseProntuario(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.prontuario@exemplo.com", "11111111111", "616161")
        cls.bruno = criar_psicologo("bruno.prontuario@exemplo.com", "22222222222", "626262")
        with contexto.como(cls.ana.pk):
            cls.marcos = Paciente(nome="Marcos")
            caso_marcos = cadastrar_paciente(cls.marcos)
            cls.maria = Paciente(nome="Maria")
            cadastrar_paciente(cls.maria)
            cls.joao = Paciente(nome="João")
            cadastrar_paciente(cls.joao)
            cls.sessao_marcos = agenda.cadastrar_avulsa(caso_marcos, estado=REALIZADA, inicio=momento(3))
            cls.falta_marcos = agenda.cadastrar_avulsa(caso_marcos, estado=FALTOU, inicio=momento(4))
            casal = criar_caso_coletivo([cls.maria, cls.joao], descricao="Maria e João")
            cls.sessao_casal = agenda.cadastrar_avulsa(casal, estado=REALIZADA, inicio=momento(5))
        with contexto.como(cls.bruno.pk):
            cls.carla = Paciente(nome="Carla")
            caso_carla = cadastrar_paciente(cls.carla)
            cls.sessao_carla = agenda.cadastrar_avulsa(caso_carla, estado=REALIZADA, inicio=momento(3))

    def pendentes(self):
        with contexto.como(self.ana.pk):
            return {(r.consulta.pk, r.paciente.pk) for r in servicos.prontuarios_pendentes()}


class Pendencia(BaseProntuario):
    def test_sessao_realizada_gera_um_por_participante_e_falta_nao(self):
        self.assertEqual(self.pendentes(), {
            (self.sessao_marcos.pk, self.marcos.pk),
            (self.sessao_casal.pk, self.maria.pk),
            (self.sessao_casal.pk, self.joao.pk),
        })

    def test_confirmar_um_participante_nao_tira_o_outro(self):
        with contexto.como(self.ana.pk):
            servicos.confirmar(self.sessao_casal, self.maria, texto="Registro da Maria.")
        self.assertEqual(self.pendentes(), {(self.sessao_marcos.pk, self.marcos.pk),
                                            (self.sessao_casal.pk, self.joao.pk)})

    def test_rascunho_continua_pendente(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_rascunho(self.sessao_marcos, self.marcos, texto="Começo do registro.")
            situacao = servicos.registro_de(self.sessao_marcos, self.marcos).situacao
        self.assertIn((self.sessao_marcos.pk, self.marcos.pk), self.pendentes())
        self.assertEqual(situacao, "rascunho")


class CicloDeVida(BaseProntuario):
    def test_rascunho_se_edita_sem_criar_versao(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_rascunho(self.sessao_marcos, self.marcos, texto="Primeiro.")
            servicos.salvar_rascunho(self.sessao_marcos, self.marcos, texto="Segundo.")
            versoes = list(VersaoProntuario.objects.all())
        self.assertEqual([(v.numero, v.texto) for v in versoes], [(1, "Segundo.")])

    def test_confirmada_nao_se_altera_nem_se_apaga(self):
        with contexto.como(self.ana.pk):
            versao = servicos.confirmar(self.sessao_marcos, self.marcos, texto="Registro.")
            versao.texto = "Adulterado."
            with self.assertRaises(VersaoCongelada):
                versao.save()
            with self.assertRaises(VersaoCongelada):
                versao.delete()

    def test_correcao_cria_versao_nova_com_motivo_e_guarda_a_anterior(self):
        with contexto.como(self.ana.pk):
            servicos.confirmar(self.sessao_marcos, self.marcos, texto="Primeira.")
            with self.assertRaises(ValidationError):
                servicos.salvar_rascunho(self.sessao_marcos, self.marcos, texto="Corrigida.")
            servicos.confirmar(self.sessao_marcos, self.marcos, texto="Corrigida.", motivo="Troquei o nome do remédio.")
            registro = servicos.registro_de(self.sessao_marcos, self.marcos)
        self.assertEqual([(v.numero, v.texto) for v in registro.confirmadas], [(1, "Primeira."), (2, "Corrigida.")])
        self.assertEqual((registro.vigente.motivo, registro.situacao), ("Troquei o nome do remédio.", "confirmado"))

    def test_texto_vazio_e_recusado_sem_criar_prontuario(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.salvar_rascunho(self.sessao_marcos, self.marcos, texto="   ")
            self.assertFalse(Prontuario.objects.exists())

    def test_descartar_rascunho(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_rascunho(self.sessao_marcos, self.marcos, texto="Rascunho.")
            servicos.descartar_rascunho(self.sessao_marcos, self.marcos)
            self.assertFalse(Prontuario.objects.exists())

            servicos.confirmar(self.sessao_marcos, self.marcos, texto="Confirmado.")
            servicos.salvar_rascunho(self.sessao_marcos, self.marcos, texto="Correção.", motivo="Engano.")
            servicos.descartar_rascunho(self.sessao_marcos, self.marcos)
            self.assertEqual(VersaoProntuario.objects.count(), 1)

    def test_so_sessao_realizada_e_so_quem_participou(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.salvar_rascunho(self.falta_marcos, self.marcos, texto="Não houve sessão.")
            with self.assertRaises(ValidationError):
                servicos.salvar_rascunho(self.sessao_marcos, self.maria, texto="Não participou.")


class Protecao(BaseProntuario):
    def test_sessao_com_prontuario_nao_vira_falta_nem_e_excluida(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_rascunho(self.sessao_marcos, self.marcos, texto="Registro.")
            with self.assertRaises(ValidationError):
                agenda.alterar_situacao(self.sessao_marcos, FALTOU)
            with self.assertRaises(ValidationError):
                agenda.excluir_consulta(self.sessao_marcos)

    def test_auditoria_registra_sem_guardar_o_texto(self):
        with contexto.como(self.ana.pk):
            servicos.confirmar(self.sessao_marcos, self.marcos, texto="Conteúdo sigiloso da sessão.")
        registros = RegistroAuditoria.objetos_todos.filter(titular="pacientes.paciente", titular_id=self.marcos.pk,
                                                           alvo__startswith="prontuarios.")
        self.assertIn("prontuarios.versaoprontuario", {r.alvo for r in registros})
        self.assertNotIn("sigiloso", json.dumps([r.campos for r in registros]))


class Isolamento(BaseProntuario):
    def test_nao_ve_nem_escreve_prontuario_de_outro_psicologo(self):
        self.assertNotIn(self.sessao_carla.pk, {consulta for consulta, _ in self.pendentes()})
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.salvar_rascunho(self.sessao_carla, self.carla, texto="Intrusão.")


class NoBanco(TransactionTestCase):
    TABELAS = ["prontuarios_prontuario", "prontuarios_versaoprontuario"]

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Gatilho e RLS exigem PostgreSQL.")
        self.ana = criar_psicologo("ana.prontbanco@exemplo.com", "33333333333", "636363")
        self.bruno = criar_psicologo("bruno.prontbanco@exemplo.com", "44444444444", "646464")
        for psicologo, nome in [(self.ana, "Da Ana"), (self.bruno, "Do Bruno")]:
            with contexto.como(psicologo.pk):
                paciente = Paciente(nome=nome)
                caso = cadastrar_paciente(paciente)
                sessao = agenda.cadastrar_avulsa(caso, estado=REALIZADA, inicio=momento(3))
                servicos.confirmar(sessao, paciente, texto="Registro original.")

    def test_gatilho_recusa_alterar_versao_confirmada_pela_requisicao(self):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                db.assumir_papel_da_aplicacao()
                db.aplicar_escopo(self.ana.pk)
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE prontuarios_versaoprontuario SET texto = 'adulterado'")
        self.assertFalse(VersaoProntuario.objetos_todos.filter(texto="adulterado").exists())

    def test_gatilho_recusa_ate_o_dono_do_banco(self):
        """O papel dono ignora o RLS, mas não o gatilho: nem uma migração mal escrita reescreve o prontuário."""
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE prontuarios_versaoprontuario SET texto = 'adulterado'")

    def test_sql_cru_so_devolve_o_proprio_dono(self):
        for tabela in self.TABELAS:
            with self.subTest(tabela=tabela):
                with transaction.atomic():
                    db.assumir_papel_da_aplicacao()
                    db.aplicar_escopo(self.ana.pk)
                    with connection.cursor() as cursor:
                        cursor.execute(f"SELECT DISTINCT psicologo_id FROM {tabela}")
                        donos = {linha[0] for linha in cursor.fetchall()}
                self.assertEqual(donos, {self.ana.pk})

    def test_papel_anonimo_nao_le_prontuario(self):
        for tabela in self.TABELAS:
            with self.subTest(tabela=tabela):
                with self.assertRaises(ProgrammingError):
                    with transaction.atomic():
                        db.assumir_papel_da_web()
                        with connection.cursor() as cursor:
                            cursor.execute(f"SELECT 1 FROM {tabela}")
