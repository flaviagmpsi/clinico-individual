"""Ponte entre o contexto Python e a sessão do Postgres.

Aqui mora a resposta ao impeditivo I-01, o único que podia derrubar a fundação do projeto:
o *pooling* do Neon reaproveita conexões entre requisições, então uma variável de sessão
deixada para trás faria a requisição seguinte herdar o psicólogo da anterior.

**A solução é não deixar nada para trás.** `set_config(..., is_local => true)` amarra o valor
à **transação**, e o Postgres o descarta no COMMIT ou no ROLLBACK. Não existe janela em que a
conexão volte ao pool carregando o tenant: o banco limpa, não nós.

Consequência: **toda requisição precisa rodar dentro de uma transação.** É o middleware quem
garante isso.

⚠️ `SET LOCAL` e `set_config(is_local => true)` **não existem fora de transação**. Em
autocommit cada instrução é a própria transação e o efeito morre no ponto e vírgula. Por isso
as funções daqui recusam-se a rodar fora de uma — falhar alto é melhor que devolver um
silêncio que parece sucesso. (Era o caso da antiga `limpar_escopo`, que prometia ser a rede
de segurança justamente no cenário em que não fazia nada.)
"""

from django.db import connection

from core.rls import PAPEL_APLICACAO, PAPEL_WEB, VARIAVEL_SESSAO


class ForaDeTransacao(RuntimeError):
    """Alguém chamou um comando de escopo em autocommit, onde ele não tem efeito."""


def _exigir_transacao(o_que: str) -> None:
    if connection.get_autocommit():
        raise ForaDeTransacao(
            f"{o_que} usa SET LOCAL, que só vale dentro de uma transação. "
            "Em autocommit a chamada seria descartada em silêncio e o código seguiria "
            "com o papel e o escopo errados. Envolva em `transaction.atomic()`."
        )


def _assumir(papel: str) -> None:
    _exigir_transacao(f"Assumir o papel {papel}")
    with connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL ROLE {papel}")


def assumir_papel_da_aplicacao() -> None:
    """Papel da requisição **autenticada**: enxerga o domínio, filtrado pelo RLS.

    Descoberto ao rodar o passo 0: o papel dono do banco no Neon tem o atributo `BYPASSRLS`,
    que passa por cima da policy e até do `FORCE ROW LEVEL SECURITY`. Conectar como dono e
    confiar no RLS é confiar em nada.

    `SET LOCAL` — e não `SET` — pela mesma razão do `set_config` abaixo: o papel volta ao
    original quando a transação fecha, sem depender de alguém lembrar de resetar.
    """
    _assumir(PAPEL_APLICACAO)


def assumir_papel_da_web() -> None:
    """Papel da requisição **anônima**: login, cadastro, healthcheck, webhook.

    Existe porque devolver a requisição anônima cedo deixava a superfície pública inteira
    rodando como dono do banco — com `BYPASSRLS`, portanto sem a terceira camada (ADR-046).
    Este papel lê a tabela de login e a de sessão, e **nada mais**: não tem grant em tabela
    clínica, então nem um `SELECT *` escrito à mão alcança prontuário.

    É também o papel que a aplicação usa para **conectar** em produção. Como `hamilton_app` é
    concedido a ele, `SET LOCAL ROLE` funciona; e como ele não tem `BYPASSRLS`, um `RESET ROLE`
    — a fuga clássica de uma injeção de SQL — devolve o processo a um papel sem permissão
    alguma no domínio, em vez de devolver o banco inteiro.
    """
    _assumir(PAPEL_WEB)


def aplicar_escopo(psicologo_id: int) -> None:
    """Define o dono da sessão, válido só até o fim da transação corrente."""
    _exigir_transacao("Aplicar o escopo do psicólogo")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config(%s, %s, true)",
            [VARIAVEL_SESSAO, str(psicologo_id)],
        )


def limpar_escopo() -> None:
    """Zera o dono da sessão dentro da transação corrente.

    Redundante quando a transação fecha — o Postgres já descarta a variável. Serve a quem
    precisa trocar de escopo no meio de uma transação longa (rotina de descarte, comando de
    management que percorre psicólogos).
    """
    _exigir_transacao("Limpar o escopo do psicólogo")
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, '', true)", [VARIAVEL_SESSAO])


def escopo_atual_no_banco() -> str:
    """O que o Postgres acha que é o dono agora. Existe para os testes poderem afirmar."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting(%s, true)", [VARIAVEL_SESSAO])
        return cursor.fetchone()[0] or ""


def papel_atual_no_banco() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        return cursor.fetchone()[0]


def papel_da_conexao_ignora_rls() -> bool:
    """O papel com que a aplicação **conectou** consegue passar por cima do RLS?

    Perguntado ao `session_user`, não ao `current_user`: o que interessa é o privilégio que
    um `RESET ROLE` recupera, não o papel rebaixado do momento.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = session_user"
        )
        linha = cursor.fetchone()
    return bool(linha and linha[0])
