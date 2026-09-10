"""Ponte entre o contexto Python e a sessão do Postgres.

Aqui mora a resposta ao impeditivo I-01, o único que podia derrubar a fundação do projeto:
o *pooling* do Neon reaproveita conexões entre requisições, então uma variável de sessão
deixada para trás faria a requisição seguinte herdar o psicólogo da anterior.

**A solução é não deixar nada para trás.** `set_config(..., is_local => true)` amarra o valor
à **transação**, e o Postgres o descarta no COMMIT ou no ROLLBACK. Não existe janela em que a
conexão volte ao pool carregando o tenant: o banco limpa, não nós. Limpeza explícita é rede
de segurança, não o mecanismo.

Consequência: **toda requisição precisa rodar dentro de uma transação.** É o middleware quem
garante isso.
"""

from django.db import connection

from core.rls import VARIAVEL_SESSAO


def aplicar_escopo(psicologo_id: int) -> None:
    """Define o dono da sessão, válido só até o fim da transação corrente."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config(%s, %s, true)",
            [VARIAVEL_SESSAO, str(psicologo_id)],
        )


def limpar_escopo() -> None:
    """Zera o dono da sessão.

    Redundante quando a transação fecha — e é justamente por isso que fica aqui: o dia em
    que alguém rodar código fora de transação, esta chamada é o que impede o vazamento.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, '', true)", [VARIAVEL_SESSAO])


def escopo_atual_no_banco() -> str:
    """O que o Postgres acha que é o dono agora. Existe para os testes poderem afirmar."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting(%s, true)", [VARIAVEL_SESSAO])
        return cursor.fetchone()[0] or ""
