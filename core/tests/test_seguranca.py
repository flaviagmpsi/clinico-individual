"""Bateria adversarial sobre a fundação do passo 0.

O `test_isolamento.py` prova que o caminho feliz das três camadas funciona. Este arquivo
faz a pergunta oposta: **por onde ainda dá para passar?**

Cada teste aqui é escrito como a garantia *deveria* ser, no estilo TDD — um teste que falha
é um buraco real, não ruído. A docstring diz o que quebra e por quê importa.
"""

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.utils import IntegrityError, ProgrammingError
from django.http import HttpResponse

from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import path

from contas.models import Psicologo
from core import contexto, db
from pacientes.models import Paciente

SENHA = "senha-de-teste-123"


def criar_psicologo(email, cpf, crp_numero, **extra):
    return Psicologo.objects.create_user(
        email=email,
        password=SENHA,
        nome_completo=f"Psicologo {crp_numero}",
        cpf=cpf,
        telefone="31988887777",
        crp_regiao="04",
        crp_numero=crp_numero,
        **extra,
    )


def so_postgres(teste):
    if connection.vendor != "postgresql":
        teste.skipTest("Comportamento específico do PostgreSQL.")


# ---------------------------------------------------------------------------
# Views de apoio para os testes de middleware. `ROOT_URLCONF` aponta para este
# módulo nos testes que precisam de uma requisição HTTP de verdade.
# ---------------------------------------------------------------------------


def ver_pacientes(request):
    nomes = list(Paciente.objects.values_list("nome", flat=True))
    return HttpResponse("|".join(nomes))


def ver_escopo(request):
    return HttpResponse(f"py={contexto.atual()};pg={db.escopo_atual_no_banco()}")


def ver_papel(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        return HttpResponse(cursor.fetchone()[0])


def ler_cru(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT nome FROM pacientes_paciente")
        return HttpResponse("|".join(linha[0] for linha in cursor.fetchall()))


urlpatterns = [
    path("pacientes/", ver_pacientes),
    path("escopo/", ver_escopo),
    path("papel/", ver_papel),
    path("cru/", ler_cru),
]


class BaseDoisPsicologos(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.seg@exemplo.com", "11111111111", "111111")
        cls.bruno = criar_psicologo("bruno.seg@exemplo.com", "22222222222", "222222")
        with contexto.como(cls.ana.pk):
            cls.paciente_da_ana = Paciente.objects.create(nome="Paciente da Ana")
        with contexto.como(cls.bruno.pk):
            cls.paciente_do_bruno = Paciente.objects.create(nome="Paciente do Bruno")


# ===========================================================================
# 1. O tenant-raiz não está protegido
# ===========================================================================


class TabelasSemRLS(BaseDoisPsicologos):
    """As tabelas que **não** herdam `TenantOwnedModel` ficaram fora da terceira camada.

    `pacientes_paciente` tem policy. `contas_psicologo` e `django_session` não têm — e o
    papel `hamilton_app` recebeu `SELECT` em *todas* as tabelas do schema. Qualquer caminho
    que chegue a SQL cru dentro de uma requisição autenticada lê o banco inteiro dessas duas.
    """

    def setUp(self):
        so_postgres(self)

    def test_psicologo_nao_le_o_cadastro_de_outro_psicologo(self):
        """CPF, e-mail e **hash de senha** de todos os assinantes, num SELECT só."""
        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.ana.pk)
            with connection.cursor() as cursor:
                cursor.execute("SELECT email, password FROM contas_psicologo")
                linhas = cursor.fetchall()
        self.assertEqual(
            [linha[0] for linha in linhas],
            [self.ana.email],
            "A tabela do tenant-raiz devolveu o cadastro de outros psicólogos.",
        )

    def test_psicologo_nao_le_a_sessao_de_outro_psicologo(self):
        """`django_session` guarda o `session_key` em claro: lê-la é se passar por quem quiser.

        A policy não resolveria — a tabela não tem coluna de dono. O que resolve é a requisição
        autenticada não ter permissão nenhuma nela (ADR-046). Quem precisa da sessão é o
        `SessionMiddleware`, que roda fora da transação do escopo, sob `hamilton_web`.
        """
        Client().force_login(self.bruno)
        with self.assertRaises(ProgrammingError, msg="A sessão de outro psicólogo está legível."):
            with transaction.atomic():
                db.assumir_papel_da_aplicacao()
                db.aplicar_escopo(self.ana.pk)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT count(*) FROM django_session")

    def test_orm_do_psicologo_nao_lista_outros_psicologos(self):
        """`Psicologo.objects` é o manager do Django, sem escopo — `.all()` pediria o SaaS inteiro.

        Não dá para trocá-lo por um `TenantManager`: o backend de autenticação precisa procurar
        um usuário antes de existir escopo. Então quem filtra é a policy, e o teste roda sob o
        papel da requisição autenticada, que é onde a promessa da ADR-001 tem de valer.
        """
        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.ana.pk)
            with contexto.como(self.ana.pk):
                emails = list(get_user_model().objects.values_list("email", flat=True))
        self.assertEqual(emails, [self.ana.email])


# ===========================================================================
# 2. Escalada de privilégio de volta ao dono do banco
# ===========================================================================


class EscaladaDePapel(BaseDoisPsicologos):
    """`SET LOCAL ROLE` é reversível de dentro da própria sessão.

    A conexão continua *autenticada* como `hamilton_owner` (que tem `BYPASSRLS`); só o papel
    corrente foi rebaixado. Um `RESET ROLE` — uma linha a mais numa injeção de SQL, ou um
    `cursor.execute` distraído — devolve o privilégio e apaga a terceira camada inteira.
    """

    def setUp(self):
        so_postgres(self)

    def test_reset_role_nao_devolve_o_privilegio_de_ignorar_rls(self):
        # O `assertRaises` envolve o `atomic` inteiro: o erro de permissão aborta a transação,
        # e sair do bloco depois disso levantaria `TransactionManagementError` em vez do erro
        # que interessa.
        with self.assertRaises(ProgrammingError, msg="RESET ROLE ainda alcança o domínio."):
            with transaction.atomic():
                db.assumir_papel_da_aplicacao()
                db.aplicar_escopo(self.ana.pk)
                with connection.cursor() as cursor:
                    cursor.execute(f"SET LOCAL ROLE {db.PAPEL_WEB}")
                    cursor.execute("SELECT nome FROM pacientes_paciente")

    def test_injecao_de_sql_com_segunda_instrucao_nao_escapa(self):
        """psycopg aceita várias instruções num `execute`: a segunda delas pode ser a fuga.

        Simula o efeito de uma injeção que encerra a consulta e emenda um comando de sessão.
        O SELECT seguinte — legítimo, parametrizado, feito pelo ORM — já corre privilegiado.
        """
        with self.assertRaises(ProgrammingError):
            with transaction.atomic():
                db.assumir_papel_da_aplicacao()
                db.aplicar_escopo(self.ana.pk)
                with connection.cursor() as cursor:
                    cursor.execute(f"SELECT 1 WHERE false; SET LOCAL ROLE {db.PAPEL_WEB}")
                with connection.cursor() as cursor:
                    cursor.execute("SELECT nome FROM pacientes_paciente")


# ===========================================================================
# 3. A rede de segurança de `core/db.py` fora de transação
# ===========================================================================


class ForaDeTransacao(TransactionTestCase):
    """`SET LOCAL` e `set_config(is_local => true)` **não existem** fora de transação.

    A docstring de `limpar_escopo` promete o contrário: "o dia em que alguém rodar código fora
    de transação, esta chamada é o que impede o vazamento". Em autocommit, cada instrução é sua
    própria transação — o efeito morre no ponto e vírgula. A rede de segurança é pintada na parede.
    """

    def setUp(self):
        so_postgres(self)
        self.ana = criar_psicologo("ana.tx2@exemplo.com", "44444444444", "444444")

    def test_limpar_escopo_fora_de_transacao_recusa_em_vez_de_fingir(self):
        """Antes devolvia `None` e deixava o escopo intacto: a rede de segurança pintada na parede."""
        with self.assertRaises(db.ForaDeTransacao):
            db.limpar_escopo()

    def test_assumir_papel_fora_de_transacao_recusa_em_vez_de_fingir(self):
        with self.assertRaises(db.ForaDeTransacao):
            db.assumir_papel_da_aplicacao()

    def test_aplicar_escopo_fora_de_transacao_recusa_em_vez_de_fingir(self):
        with self.assertRaises(db.ForaDeTransacao):
            db.aplicar_escopo(self.ana.pk)

    def test_dentro_de_transacao_tudo_funciona_como_antes(self):
        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.ana.pk)
            self.assertEqual(db.papel_atual_no_banco(), db.PAPEL_APLICACAO)
            self.assertEqual(db.escopo_atual_no_banco(), str(self.ana.pk))


# ===========================================================================
# 4. Buracos na camada 1 (modelo) e na camada 2 (manager)
# ===========================================================================


class CamadaDeAplicacaoAdversarial(BaseDoisPsicologos):
    def test_o_caminho_deliberado_de_ignorar_o_dono_e_objetos_todos(self):
        """Só existe uma porta para sair do escopo, e ela tem nome próprio (ADR-047).

        O antigo `sem_escopo()` prometia isso e era `return self` sobre um queryset já
        filtrado: quem seguisse a mensagem de erro continuava tomando exceção. Quem precisa
        mesmo atravessar usa `objetos_todos`, que é legível no diff.
        """
        with contexto.como(self.ana.pk):
            nomes = sorted(Paciente.objetos_todos.values_list("nome", flat=True))
            self.assertFalse(
                hasattr(Paciente.objects.none(), "sem_escopo"),
                "sem_escopo() voltou a existir prometendo o que não faz.",
            )
        self.assertEqual(nomes, ["Paciente da Ana", "Paciente do Bruno"])

    def test_salvar_com_dono_explicito_sem_escopo_definido_e_recusado(self):
        """O `elif` do `save()` desarma a checagem justamente quando não há escopo.

        `... and contexto.atual() is not None` faz a comparação ser pulada fora de requisição —
        que é exatamente onde não há middleware para corrigir o engano. Comando de management,
        tarefa agendada e shell gravam para qualquer psicólogo, em silêncio.
        """
        with self.assertRaises(contexto.EscopoNaoDefinido):
            Paciente.objetos_todos.create(nome="Sem dono declarado", psicologo_id=self.bruno.pk)

    def test_bulk_create_sem_dono_falha_alto(self):
        """`bulk_create` não chama `save()`: a camada 1 não roda (ADR-047).

        Aceito, porque quem protege é o RLS — e porque a falha é barulhenta. O que este teste
        garante é que ela continue barulhenta: se um dia `psicologo_id` virar nulável, este
        caminho passa a gravar paciente órfão em silêncio.
        """
        with contexto.como(self.ana.pk):
            with self.assertRaises(IntegrityError):
                Paciente.objects.bulk_create([Paciente(nome="Em lote")])

    def test_update_nao_transfere_registro_para_outro_psicologo(self):
        """`.update()` não passa por `save()`: a camada 1 não vê, a camada 2 não impede.

        Dentro de uma requisição o RLS ainda barra. Fora dela — comando de management, shell,
        tarefa agendada — a transferência de um paciente para outro psicólogo é um one-liner
        que ninguém revisa como perigoso.
        """
        so_postgres(self)
        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.ana.pk)
            with contexto.como(self.ana.pk):
                with self.assertRaises(Exception):
                    Paciente.objects.filter(pk=self.paciente_da_ana.pk).update(
                        psicologo_id=self.bruno.pk
                    )
        self.assertEqual(
            Paciente.objetos_todos.get(pk=self.paciente_da_ana.pk).psicologo_id,
            self.ana.pk,
            "O paciente trocou de dono por um .update().",
        )

    def test_contexto_e_banco_podem_divergir_fora_do_middleware(self):
        """⚠️ Caracterização, não garantia: hoje **nada** obriga os dois a andarem juntos.

        `contexto.como()` mexe só no Python; `db.aplicar_escopo()` mexe só no Postgres. Dentro de
        uma requisição o middleware seta os dois — fora dela, um serviço que use só um fica com o
        ORM enxergando um psicólogo e o SQL cru enxergando outro. Não é exploração remota: é uma
        armadilha para quem escrever o primeiro comando de management. Falta um ponto de entrada
        único que sete os dois (pendente de decisão — ver P-68).
        """
        so_postgres(self)
        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.bruno.pk)
            with contexto.como(self.ana.pk):
                self.assertNotEqual(str(contexto.atual()), db.escopo_atual_no_banco())


# ===========================================================================
# 5. Validação de dados de cadastro
# ===========================================================================



class ValidacaoDoCadastro(TestCase):
    """`claude.md` §6 manda `full_clean()` no `save()` "para que a regra valha independentemente
    de onde o dado entra". Até a P-69, nenhum model fazia isso — os validadores só rodavam em
    `ModelForm`, e um shell ou comando de management gravava qualquer coisa.

    Estes três testes descreviam o comportamento **desejado** e ficaram pulados até a P-69 ser
    resolvida. Hoje `core.models.ValidaAoSalvar` roda `full_clean()` em toda gravação, e eles
    guardam a regra: se alguém desligar a validação, voltam a falhar.
    """

    def test_cpf_com_pontuacao_e_recusado(self):
        with self.assertRaises(Exception):
            criar_psicologo("cpf.ruim@exemplo.com", "111.111.111", "555555")

    def test_cpf_de_um_digito_e_recusado(self):
        """`max_length=11` limita o teto, não o piso. "1" é um CPF aceito pelo banco."""
        with self.assertRaises(Exception):
            criar_psicologo("cpf.curto@exemplo.com", "1", "666666")

    def test_telefone_com_mascara_e_recusado(self):
        with self.assertRaises(Exception):
            Psicologo.objects.create_user(
                email="tel2@exemplo.com",
                password=SENHA,
                nome_completo="Teste",
                cpf="88888888888",
                telefone="(31) 98888-7777",
                crp_regiao="04",
                crp_numero="888888",
            )


# ===========================================================================
# 6. O middleware — o código que roda em produção e não tinha teste nenhum
# ===========================================================================


@override_settings(ROOT_URLCONF=__name__)
class MiddlewareDeEscopo(TransactionTestCase):
    """⚠️ `TransactionTestCase`, e não `TestCase`, pelo mesmo motivo que a própria autora
    documentou em `test_isolamento.py`: dentro de um `TestCase` o `transaction.atomic()` do
    middleware vira savepoint, e o `SET LOCAL ROLE` se prende à transação **externa** do teste.
    O papel da primeira requisição sobreviveria até o fim do método, e a segunda requisição
    correria sob ele — o oposto do que estes testes existem para provar.
    """

    def setUp(self):
        self.ana = criar_psicologo("ana.mw@exemplo.com", "55555555555", "551111")
        self.bruno = criar_psicologo("bruno.mw@exemplo.com", "66666666666", "661111")
        with contexto.como(self.ana.pk):
            Paciente.objects.create(nome="Paciente da Ana")
        with contexto.como(self.bruno.pk):
            Paciente.objects.create(nome="Paciente do Bruno")
    def test_requisicao_autenticada_ve_apenas_o_proprio_paciente(self):
        cliente = Client()
        cliente.force_login(self.ana)
        resposta = cliente.get("/pacientes/")
        self.assertEqual(resposta.content.decode(), "Paciente da Ana")

    def test_duas_requisicoes_seguidas_nao_misturam_psicologos(self):
        """O I-01 visto de fora: mesma conexão, dois usuários, em sequência."""
        cliente = Client()
        cliente.force_login(self.ana)
        self.assertEqual(cliente.get("/pacientes/").content.decode(), "Paciente da Ana")
        cliente.force_login(self.bruno)
        self.assertEqual(cliente.get("/pacientes/").content.decode(), "Paciente do Bruno")

    def test_requisicao_anonima_nao_roda_como_dono_do_banco(self):
        """Anônimo não recebe escopo — mas também não perde o `BYPASSRLS`.

        O middleware devolve cedo e a requisição inteira corre sob o papel dono. Qualquer view
        pública (login, cadastro, healthcheck, webhook do Asaas) opera sem a terceira camada.
        """
        so_postgres(self)
        papel = Client().get("/papel/").content.decode()
        self.assertEqual(
            papel,
            db.PAPEL_WEB,
            "Requisição anônima roda com o papel que ignora o RLS.",
        )

    def test_requisicao_anonima_nao_le_dado_clinico_por_sql_cru(self):
        """Não por filtro: por falta de permissão. `hamilton_web` não tem grant no domínio."""
        so_postgres(self)
        with self.assertRaises(ProgrammingError, msg="View anônima leu a tabela de pacientes."):
            Client().get("/cru/")

    def test_escopo_e_zerado_depois_da_resposta(self):
        cliente = Client()
        cliente.force_login(self.ana)
        cliente.get("/escopo/")
        self.assertIsNone(contexto.atual())

    def test_usuario_inativo_nao_recebe_escopo(self):
        """`is_authenticated` é `True` para qualquer instância de usuário carregada da sessão.

        Desativar a conta (ADR-038: `SOMENTE_LEITURA`, `ARQUIVADA`) precisa cortar o acesso ao
        dado, e o corte natural é aqui — o middleware é o único ponto por onde todo mundo passa.
        """
        self.ana.is_active = False
        self.ana.save()
        cliente = Client()
        cliente.force_login(self.ana)
        resposta = cliente.get("/escopo/")
        self.assertEqual(resposta.content.decode(), "py=None;pg=")


# ===========================================================================
# 7. O gate de produção
# ===========================================================================


class CheckDePapelDeConexao(TestCase):
    """`manage.py check --deploy` precisa reprovar o arranjo que anula a ADR-001.

    A suíte roda conectada como dono, porque criar o banco de teste exige DDL. Isso significa
    que o cenário errado está sempre montado aqui — é de graça verificar que o check o pega.
    """

    def test_check_reprova_conexao_privilegiada(self):
        so_postgres(self)
        from core.checks import papel_de_conexao_nao_pode_ignorar_rls

        with override_settings(DEBUG=False):
            problemas = papel_de_conexao_nao_pode_ignorar_rls(None)
        self.assertEqual([p.id for p in problemas], ["core.E001"])

    def test_check_aprova_conexao_sem_bypassrls(self):
        so_postgres(self)
        from core.checks import papel_de_conexao_nao_pode_ignorar_rls

        # `session_user` não muda com SET ROLE — é justamente o ponto do check. Para simular a
        # produção, perguntamos o que ele perguntaria sobre `hamilton_web`.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = %s",
                [db.PAPEL_WEB],
            )
            privilegiado = cursor.fetchone()[0]
        self.assertFalse(privilegiado, "hamilton_web ganhou BYPASSRLS; a ADR-046 caiu.")
