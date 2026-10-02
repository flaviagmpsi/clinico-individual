"""A administradora da plataforma atravessa o isolamento; o psicólogo comum, não (ADR-115).

Os dois lados importam igualmente, e um teste só não serve. Uma policy que negasse tudo passaria no segundo e
falharia no primeiro; uma que liberasse tudo passaria no primeiro e falharia no segundo. É o par que prova.

SQL cru de propósito: o manager e o `contexto` são as duas primeiras camadas, e o que se verifica aqui é a
terceira — a que vale mesmo quando o código erra.
"""

from django.db import connection, transaction
from django.test import TransactionTestCase

from contas.models import Psicologo
from core import contexto, db
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente

SENHA = "hamilton-teste-123"


def contar(tabela: str, como, administradora=None) -> int:
    """Quantas linhas esta sessão enxerga, perguntando ao banco sem passar por manager nenhum.

    `administradora` sai do próprio psicólogo quando não é dito — é o que o middleware faz.
    """
    if administradora is None:
        administradora = como.is_superuser
    with transaction.atomic():
        db.assumir_papel_da_aplicacao()
        db.aplicar_escopo(como.pk, administradora=administradora)
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {tabela}")
            return cursor.fetchone()[0]


class Base(TransactionTestCase):
    def setUp(self):
        self.ana = Psicologo.objects.create_user(email="ana.adm@t.com", password=SENHA, nome_completo="Ana",
                                                 crp_regiao="04", crp_numero="9001")
        self.bruno = Psicologo.objects.create_user(email="bruno.adm@t.com", password=SENHA, nome_completo="Bruno",
                                                   crp_regiao="04", crp_numero="9002")
        with contexto.como(self.ana.pk):
            cadastrar_paciente(Paciente(nome="Paciente da Ana"))
        with contexto.como(self.bruno.pk):
            cadastrar_paciente(Paciente(nome="Paciente do Bruno"))


class PsicologoComum(Base):
    def test_continua_vendo_so_o_proprio_paciente(self):
        """Se este teste cair, o isolamento que protege os pacientes caiu junto."""
        self.assertEqual(contar("pacientes_paciente", como=self.ana), 1)
        self.assertEqual(contar("pacientes_paciente", como=self.bruno), 1)

    def test_continua_vendo_so_a_propria_conta(self):
        self.assertEqual(contar("contas_psicologo", como=self.ana), 1)


class Administradora(Base):
    def setUp(self):
        super().setUp()
        self.chefe = Psicologo.objects.create_user(email="chefe@t.com", password=SENHA, nome_completo="Chefe",
                                                   crp_regiao="04", crp_numero="9003",
                                                   is_staff=True, is_superuser=True)

    def test_enxerga_o_paciente_de_todo_mundo(self):
        """O que a ADR-115 abriu — e o que ela custa, dito em forma de teste."""
        self.assertEqual(contar("pacientes_paciente", como=self.chefe), 2)

    def test_enxerga_todas_as_contas(self):
        """É o que a tela de administração precisa para listar quem se cadastrou."""
        self.assertEqual(contar("contas_psicologo", como=self.chefe), 3)

    def test_quem_nao_declara_ser_administradora_nao_e(self):
        """A trava é a declaração da transação, não a conta: sem ela, nem a chefe atravessa.

        É o que garante que uma requisição anônima — que nunca chama `aplicar_escopo` — não ganhe nada aqui.
        """
        self.assertEqual(contar("pacientes_paciente", como=self.chefe, administradora=False), 0)

    def test_a_declaracao_sozinha_nao_basta_para_um_psicologo_comum(self):
        """E a recíproca: declarar "sim" é o que o middleware faz a partir de `is_superuser`.

        Este teste existe para deixar explícito onde mora a decisão — no Django, não no banco. Se alguém um dia
        mover essa decisão para outro lugar, é aqui que se vê.
        """
        self.assertEqual(contar("pacientes_paciente", como=self.ana, administradora=True), 2)
