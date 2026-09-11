"""Como uma view declara que não precisa do escopo do psicólogo.

A ADR-046 revogou `django_session` de `hamilton_app`: ler essa tabela é se passar por qualquer
psicólogo logado, e a requisição autenticada não tem por que alcançá-la. O efeito colateral
apareceu na primeira tela: **o logout deixou de funcionar.** `logout()` chama
`session.flush()`, que apaga a linha da sessão *durante* a view — já sob `hamilton_app`, que
não tem mais permissão ali.

Sair do sistema é a única operação que um usuário autenticado faz sem tocar em dado de
domínio. Em vez de devolver a sessão a `hamilton_app` — desfazendo a ADR-046 por causa de uma
view —, a view declara que dispensa o escopo, e o middleware a deixa em `hamilton_web`.

É o mesmo padrão de `csrf_exempt`: explícito, visível no ponto de uso, e o custo de usá-lo
errado é perder acesso ao domínio, não ganhar acesso indevido. A falha é segura.
"""


def dispensa_escopo(view):
    """Roda a view sob `hamilton_web`, sem escopo de psicólogo.

    Use **apenas** em views que não tocam dado de domínio. Se a view precisar de um paciente,
    ela vai receber `permission denied` do Postgres — barulhento, e do lado certo do erro.
    """
    view.dispensa_escopo = True
    return view
