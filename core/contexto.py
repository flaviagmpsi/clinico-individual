"""Quem é o psicólogo desta requisição.

Usa `ContextVar` em vez de uma variável de módulo porque o Django serve requisições
concorrentes na mesma thread sob ASGI, e uma global viraria vazamento entre requisições —
exatamente o que a ADR-001 proíbe. `ContextVar` isola por contexto de execução.

Este módulo não conhece Django nem banco. Ele responde uma pergunta só: *de quem é o dado
que estou manipulando agora?*
"""

from contextlib import contextmanager
from contextvars import ContextVar

_psicologo_atual: ContextVar[int | None] = ContextVar("psicologo_atual", default=None)


class EscopoNaoDefinido(Exception):
    """Alguém tentou tocar dado de domínio sem dizer de quem ele é.

    Isto **não** é um erro de borda: é a rede de proteção da ADR-001. Se esta exceção
    aparece, existe uma consulta que rodaria sem filtro de dono — e em produção ela
    devolveria dado de outro psicólogo. Quebrar aqui é o comportamento desejado.
    """


def definir(psicologo_id: int | None) -> None:
    _psicologo_atual.set(psicologo_id)


def atual() -> int | None:
    return _psicologo_atual.get()


def exigir() -> int:
    psicologo_id = _psicologo_atual.get()
    if psicologo_id is None:
        raise EscopoNaoDefinido(
            "Consulta a dado de domínio sem escopo de psicólogo definido. "
            "Use `core.contexto.como(psicologo_id)` ou deixe o middleware defini-lo. "
            "Se a intenção é realmente ignorar o dono, use `.sem_escopo()` e explique por quê."
        )
    return psicologo_id


@contextmanager
def como(psicologo_id: int | None):
    """Executa um bloco no escopo de um psicólogo.

    Serve a testes, comandos de management e tarefas fora do ciclo de requisição —
    os três lugares onde o middleware não roda e o esquecimento é fácil.
    """
    token = _psicologo_atual.set(psicologo_id)
    try:
        yield
    finally:
        _psicologo_atual.reset(token)
