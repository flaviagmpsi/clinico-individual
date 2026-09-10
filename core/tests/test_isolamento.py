"""O teste que sustenta o projeto inteiro.

A ADR-001 promete que um psicólogo **não alcança** dado de outro. Promessa em documento não
protege ninguém; o que protege é este arquivo falhando quando alguém quebrar a garantia.

São três camadas independentes, e cada uma é testada como se as outras não existissem —
porque em produção uma delas pode ser contornada por um caminho que ninguém previu.
"""

from django.db import connection, transaction
from django.db.utils import ProgrammingError
from django.test import TestCase

from contas.models import Psicologo
from core import contexto, db
from pacientes.models import Paciente


def criar_psicologo(email: str, cpf: str, crp_numero: str) -> Psicologo:
    return Psicologo.objects.create_user(
        email=email,
        password="senha-de-teste-123",
        nome_completo=f"Psicólogo {crp_numero}",
        cpf=cpf,
        telefone="31988887777",
        crp_regiao="04",
        crp_numero=crp_numero,
    )


class BaseIsolamento(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana@exemplo.com", "11111111111", "111111")
        cls.bruno = criar_psicologo("bruno@exemplo.com", "22222222222", "222222")

        with contexto.como(cls.ana.pk):
            cls.paciente_da_ana = Paciente.objects.create(nome="Paciente da Ana")
        with contexto.como(cls.bruno.pk):
            cls.paciente_do_bruno = Paciente.objects.create(nome="Paciente do Bruno")


class CamadaAplicacao(BaseIsolamento):
    """Camada 2 da ADR-001: o manager recusa consulta sem escopo e filtra por dono."""

    def test_consulta_sem_escopo_levanta_excecao(self):
        """A garantia mais importante: esquecer o escopo **quebra**, não devolve tudo."""
        with self.assertRaises(contexto.EscopoNaoDefinido):
            list(Paciente.objects.all())

    def test_cada_psicologo_ve_apenas_o_proprio_paciente(self):
        with contexto.como(self.ana.pk):
            nomes = list(Paciente.objects.values_list("nome", flat=True))
        self.assertEqual(nomes, ["Paciente da Ana"])

        with contexto.como(self.bruno.pk):
            nomes = list(Paciente.objects.values_list("nome", flat=True))
        self.assertEqual(nomes, ["Paciente do Bruno"])

    def test_buscar_pelo_id_do_outro_nao_encontra(self):
        """Adivinhar o id não ajuda: o filtro de dono entra antes da busca por chave."""
        with contexto.como(self.ana.pk):
            with self.assertRaises(Paciente.DoesNotExist):
                Paciente.objects.get(pk=self.paciente_do_bruno.pk)

    def test_dono_e_preenchido_a_partir_do_contexto(self):
        with contexto.como(self.ana.pk):
            paciente = Paciente.objects.create(nome="Novo")
        self.assertEqual(paciente.psicologo_id, self.ana.pk)

    def test_gravar_registro_de_outro_psicologo_e_recusado(self):
        """Copiar e colar um `psicologo_id` alheio não passa."""
        with contexto.como(self.ana.pk):
            with self.assertRaises(contexto.EscopoNaoDefinido):
                Paciente.objects.create(nome="Intruso", psicologo_id=self.bruno.pk)

    def test_escopo_nao_vaza_para_fora_do_bloco(self):
        with contexto.como(self.ana.pk):
            self.assertEqual(contexto.atual(), self.ana.pk)
        self.assertIsNone(contexto.atual())


class CamadaBanco(BaseIsolamento):
    """Camada 3 da ADR-001: o RLS barra até quem escapa do ORM.

    ⚠️ Estes testes só têm sentido em **PostgreSQL**. Em SQLite eles passam sem provar nada,
    e por isso avisam alto em vez de fingir sucesso.
    """

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest(
                "RLS exige PostgreSQL. Rodar este teste em SQLite daria falsa segurança: "
                "a camada que protege contra SQL cru simplesmente não existiria."
            )

    def test_sql_cru_nao_atravessa_a_fronteira(self):
        """O caminho que o ORM não cobre — e o motivo de o RLS existir."""
        with transaction.atomic():
            db.aplicar_escopo(self.ana.pk)
            with connection.cursor() as cursor:
                cursor.execute("SELECT nome FROM pacientes_paciente")
                linhas = [linha[0] for linha in cursor.fetchall()]
        self.assertEqual(linhas, ["Paciente da Ana"])

    def test_raw_do_orm_tambem_e_barrado(self):
        with transaction.atomic():
            db.aplicar_escopo(self.bruno.pk)
            nomes = [p.nome for p in Paciente.objetos_todos.raw("SELECT * FROM pacientes_paciente")]
        self.assertEqual(nomes, ["Paciente do Bruno"])

    def test_sem_escopo_no_banco_nao_volta_linha_nenhuma(self):
        """Negar por omissão: sem variável de sessão, a policy não casa com nada."""
        with transaction.atomic():
            db.limpar_escopo()
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM pacientes_paciente")
                self.assertEqual(cursor.fetchone()[0], 0)

    def test_escopo_nao_sobrevive_ao_fim_da_transacao(self):
        """A resposta ao impeditivo I-01, verificada.

        Com o *pooling* do Neon, a conexão volta ao pool e é reaproveitada por outra
        requisição. Se a variável sobrevivesse, a requisição seguinte herdaria este
        psicólogo. `set_config(is_local => true)` faz o Postgres descartá-la no fim da
        transação — não dependemos de lembrar de limpar.
        """
        with transaction.atomic():
            db.aplicar_escopo(self.ana.pk)
            self.assertEqual(db.escopo_atual_no_banco(), str(self.ana.pk))

        self.assertEqual(db.escopo_atual_no_banco(), "")

    def test_gravar_para_outro_psicologo_e_barrado_pelo_banco(self):
        """`WITH CHECK` na policy: o RLS também impede escrita fora do escopo."""
        with self.assertRaises((ProgrammingError, Exception)):
            with transaction.atomic():
                db.aplicar_escopo(self.ana.pk)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO pacientes_paciente "
                        "(psicologo_id, nome, criado_em, atualizado_em) "
                        "VALUES (%s, %s, NOW(), NOW())",
                        [self.bruno.pk, "Contrabando"],
                    )
