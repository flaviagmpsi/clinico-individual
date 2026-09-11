"""Verificação de arranque que recusa o único erro de infraestrutura capaz de anular a ADR-001.

O `SET LOCAL ROLE` do middleware protege a requisição. Ele **não** protege comando de
management, shell, nem uma injeção de SQL que emende um `RESET ROLE` — todos voltam ao papel
com que a aplicação *conectou*. Se esse papel tem `BYPASSRLS`, a terceira camada é decorativa
e o sistema *parece* protegido, que é o pior cenário possível (P-67, ADR-046).

Isto é um `check`, e não um teste, porque o erro não está no código: está na `DATABASE_URL`
do ambiente. Nenhum teste de repositório pega uma variável de ambiente errada no Render.

Marcado como `deploy=True`, então roda em `manage.py check --deploy` e **não** atrapalha
`migrate` — que precisa, por definição, do papel dono. O preço é que o comando tem de estar no
script de build; o ganho é que a verificação acontece onde o erro mora, no ambiente.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register


@register(deploy=True)
def papel_de_conexao_nao_pode_ignorar_rls(app_configs, **kwargs):
    from django.db import connection
    from django.db.utils import OperationalError, ProgrammingError

    from core import db

    if connection.vendor != "postgresql":
        return []

    try:
        privilegiado = db.papel_da_conexao_ignora_rls()
    except (OperationalError, ProgrammingError) as erro:
        # Não conseguir verificar **não** é o mesmo que aprovar. Uma primeira versão devolvia
        # lista vazia aqui, e com isso um banco fora do ar transformava o gate de segurança
        # num "nenhum problema encontrado" — que foi exatamente como ele passou em falso na
        # primeira vez que rodou. Avisar alto é o mínimo.
        return [
            Warning(
                f"Não foi possível verificar o papel de conexão ({erro}). O gate da ADR-046 "
                "não rodou: confirme à mão que a DATABASE_URL não tem BYPASSRLS.",
                id="core.W002",
            )
        ]

    if not privilegiado:
        return []

    recado = (
        "A aplicação conectou com um papel que tem BYPASSRLS (ou é superusuário). "
        "O Row-Level Security da ADR-001 não vale para ele: um RESET ROLE, um comando de "
        f"management ou um shell leem o banco inteiro. Aponte a DATABASE_URL para "
        f"`{db.PAPEL_WEB}` e reserve o papel dono às migrações."
    )
    if settings.DEBUG:
        return [Warning(recado, id="core.W001")]
    return [Error(recado, id="core.E001")]
