"""O `Caso` e o que pende dele: participação, cobrança, pagador e responsável legal.

Cada classe protege uma decisão registrada, e o nome dela diz qual:

- `CadastroCriaCasoEmSilencio` — ADR-026: todo paciente tem caso, sem a palavra aparecer.
- `CasoColetivo` — ADR-026: a mesma pessoa em dois vínculos, sem um sobrescrever o outro.
- `NaoMisturaPsicologos` — a checagem de chave estrangeira do Postgres **ignora RLS**; sem
  `_exigir_mesmo_dono`, o caso de um psicólogo aceitaria o paciente de outro.
- `Pagador` — ADR-009: participante ou pessoa de fora, nunca os dois.
- `CondicaoDeCobranca` — ADR-002: trocar cria condição nova com vigência, nunca sobrescreve.
- `RLSNasTabelasDoCaso` — as quatro tabelas novas sob a terceira camada da ADR-001.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.utils import ProgrammingError
from django.test import TestCase, TransactionTestCase

from contas.models import Psicologo
from core import contexto, db
from pacientes.models import Caso, CondicaoCobranca, Paciente, Participacao, ResponsavelLegal
from pacientes.servicos import cadastrar_paciente, caso_individual_de, criar_caso_coletivo

SENHA = "senha-de-teste-123"

TABELAS_DO_CASO = [
    "pacientes_caso",
    "pacientes_participacao",
    "pacientes_condicaocobranca",
    "pacientes_responsavellegal",
]


def criar_psicologo(email, cpf, crp_numero):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp_numero)


class BaseCaso(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.caso@exemplo.com", "11111111111", "515151")
        cls.bruno = criar_psicologo("bruno.caso@exemplo.com", "22222222222", "525252")
        with contexto.como(cls.ana.pk):
            cls.maria = Paciente(nome="Maria")
            cls.caso_maria = cadastrar_paciente(cls.maria, valor=Decimal("200"))
            cls.joao = Paciente(nome="João")
            cls.caso_joao = cadastrar_paciente(cls.joao)
        with contexto.como(cls.bruno.pk):
            cls.carla = Paciente(nome="Carla")
            cls.caso_carla = cadastrar_paciente(cls.carla)


class CadastroCriaCasoEmSilencio(BaseCaso):
    def test_todo_paciente_cadastrado_tem_caso_individual(self):
        with contexto.como(self.ana.pk):
            caso = caso_individual_de(self.maria)
            self.assertEqual(caso, self.caso_maria)
            self.assertTrue(caso.individual)
            self.assertEqual(list(caso.pacientes.all()), [self.maria])

    def test_pagador_padrao_e_o_proprio_paciente(self):
        """ADR-009: o caso comum — adulto pagando a própria terapia — não pede campo nenhum."""
        self.assertEqual(self.caso_maria.pagador_paciente_id, self.maria.pk)

    def test_cobranca_e_opcional_no_cadastro(self):
        """ADR-012: quem ainda não combinou valor não pode ser barrado no cadastro."""
        with contexto.como(self.ana.pk):
            self.assertIsNone(self.caso_joao.condicao_vigente())

    def test_valor_informado_vale_a_partir_de_hoje(self):
        with contexto.como(self.ana.pk):
            condicao = self.caso_maria.condicao_vigente()
        self.assertEqual(condicao.valor, Decimal("200"))
        self.assertEqual(condicao.modalidade, CondicaoCobranca.Modalidade.POR_SESSAO)
        self.assertEqual(condicao.vigente_desde, date.today())


class CasoColetivo(BaseCaso):
    def test_a_mesma_pessoa_participa_de_dois_casos(self):
        """Maria individual e Maria no casal são o mesmo cadastro, e o individual continua dela."""
        with contexto.como(self.ana.pk):
            casal = criar_caso_coletivo([self.maria, self.joao], descricao="Maria e João")
            self.assertEqual(self.maria.casos.count(), 2)
            self.assertFalse(casal.individual)
            self.assertEqual(caso_individual_de(self.maria), self.caso_maria)

    def test_caso_coletivo_exige_dois_participantes(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                criar_caso_coletivo([self.maria])

    def test_paciente_nao_entra_duas_vezes_no_mesmo_caso(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                Participacao.objects.create(caso=self.caso_maria, paciente=self.maria)


class NaoMisturaPsicologos(BaseCaso):
    """A policy de RLS olha o `psicologo_id` da **própria linha**; a chave estrangeira não passa por
    ela. Estes testes provam que a validação do model fecha a porta que o banco deixa aberta."""

    def test_nao_poe_paciente_de_outro_psicologo_no_proprio_caso(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                Participacao.objects.create(caso=self.caso_maria, paciente=self.carla)

    def test_nao_poe_paciente_proprio_no_caso_de_outro(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                Participacao.objects.create(caso=self.caso_carla, paciente=self.maria)

    def test_responsavel_nao_se_liga_a_paciente_de_outro(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                ResponsavelLegal.objects.create(paciente=self.carla, nome="Intrusa")

    def test_pagador_nao_pode_ser_paciente_de_outro(self):
        with contexto.como(self.ana.pk):
            self.caso_maria.pagador_paciente = self.carla
            with self.assertRaises(ValidationError):
                self.caso_maria.save()

    def test_condicao_nao_se_liga_a_caso_de_outro(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                CondicaoCobranca.objects.create(
                    caso=self.caso_carla, valor=Decimal("100"), vigente_desde=date.today())

    def test_caso_de_outro_nao_aparece(self):
        with contexto.como(self.ana.pk):
            self.assertFalse(Caso.objects.filter(pk=self.caso_carla.pk).exists())


class Pagador(BaseCaso):
    def test_participante_e_pessoa_de_fora_ao_mesmo_tempo_e_recusado(self):
        with contexto.como(self.ana.pk):
            self.caso_maria.pagador_nome = "Pai da Maria"
            with self.assertRaises(ValidationError):
                self.caso_maria.save()

    def test_pagador_de_fora_precisa_de_nome(self):
        with contexto.como(self.ana.pk):
            self.caso_maria.pagador_paciente = None
            self.caso_maria.pagador_cpf = "52998224725"
            with self.assertRaises(ValidationError):
                self.caso_maria.save()

    def test_pagador_de_fora_com_nome_e_aceito(self):
        with contexto.como(self.ana.pk):
            self.caso_maria.pagador_paciente = None
            self.caso_maria.pagador_nome = "Pai da Maria"
            self.caso_maria.pagador_cpf = "52998224725"
            self.caso_maria.save()
        self.caso_maria.refresh_from_db()
        self.assertEqual(self.caso_maria.pagador_nome, "Pai da Maria")


class CondicaoDeCobranca(BaseCaso):
    def test_mensalidade_exige_vencimento(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                CondicaoCobranca.objects.create(
                    caso=self.caso_joao, modalidade=CondicaoCobranca.Modalidade.MENSAL,
                    valor=Decimal("700"), vigente_desde=date.today())

    def test_valor_negativo_e_recusado(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                CondicaoCobranca.objects.create(
                    caso=self.caso_joao, valor=Decimal("-1"), vigente_desde=date.today())

    def test_trocar_cria_condicao_nova_sem_apagar_a_anterior(self):
        """A condição de hoje continua valendo até a data da nova — o passado não é reescrito."""
        daqui_a_um_mes = date.today() + timedelta(days=31)
        with contexto.como(self.ana.pk):
            CondicaoCobranca.objects.create(
                caso=self.caso_maria, modalidade=CondicaoCobranca.Modalidade.MENSAL,
                dia_vencimento=10,
                valor=Decimal("700"), vigente_desde=daqui_a_um_mes)
            self.assertEqual(self.caso_maria.condicoes.count(), 2)
            self.assertEqual(self.caso_maria.condicao_vigente().valor, Decimal("200"))
            self.assertEqual(self.caso_maria.condicao_vigente(daqui_a_um_mes).valor, Decimal("700"))


class RLSNasTabelasDoCaso(TransactionTestCase):
    """As quatro tabelas novas sob a terceira camada. `TransactionTestCase` pelo mesmo motivo de
    `core.tests`: `SET LOCAL` se prende à transação, e o `TestCase` embrulharia tudo numa só."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("RLS exige PostgreSQL.")
        self.ana = criar_psicologo("ana.rls@exemplo.com", "33333333333", "535353")
        self.bruno = criar_psicologo("bruno.rls@exemplo.com", "44444444444", "545454")
        for psicologo, nome in [(self.ana, "Da Ana"), (self.bruno, "Do Bruno")]:
            with contexto.como(psicologo.pk):
                paciente = Paciente(nome=nome)
                cadastrar_paciente(paciente, valor=Decimal("150"))
                ResponsavelLegal.objects.create(paciente=paciente, nome=f"Responsável {nome}")

    def test_sql_cru_nas_tabelas_do_caso_so_devolve_o_proprio_dono(self):
        for tabela in TABELAS_DO_CASO:
            with self.subTest(tabela=tabela):
                with transaction.atomic():
                    db.assumir_papel_da_aplicacao()
                    db.aplicar_escopo(self.ana.pk)
                    with connection.cursor() as cursor:
                        cursor.execute(f"SELECT DISTINCT psicologo_id FROM {tabela}")
                        donos = {linha[0] for linha in cursor.fetchall()}
                self.assertEqual(donos, {self.ana.pk})

    def test_papel_anonimo_nao_le_nenhuma_tabela_do_caso(self):
        """A superfície pública (login, cadastro) roda sob `hamilton_web`, que não pode ter grant
        em tabela clínica (ADR-046) — nem nas criadas depois daquela ADR."""
        for tabela in TABELAS_DO_CASO:
            with self.subTest(tabela=tabela):
                with self.assertRaises(ProgrammingError):
                    with transaction.atomic():
                        db.assumir_papel_da_web()
                        with connection.cursor() as cursor:
                            cursor.execute(f"SELECT 1 FROM {tabela}")
