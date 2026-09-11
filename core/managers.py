"""Manager que recusa consulta sem dono definido.

Segunda das três camadas da ADR-001. A primeira é o dono explícito no modelo; a terceira é o
RLS no Postgres. Esta camada existe para o erro aparecer **no teste do desenvolvedor**, com
stack trace apontando a linha, em vez de aparecer no banco como silêncio — ou, pior, como
dado de outro psicólogo.

**Ela é cinto de segurança, não blindagem** (ADR-047). `bulk_create`, `update()` e
`QuerySet.delete()` não passam por `Model.save()`, e perseguir cada saída do ORM é uma corrida
que o Django sempre ganha. Quem protege de verdade é o RLS. O que esta camada não pode fazer é
**prometer** mais do que entrega: foi o caso do antigo `sem_escopo()`, que anunciava escapar do
filtro de dono e era um `return self` sobre um queryset já filtrado.
"""

from django.db import models

from core import contexto


class TenantManager(models.Manager):
    """Filtra por dono automaticamente, e explode se não souber quem é o dono."""

    def get_queryset(self) -> models.QuerySet:
        psicologo_id = contexto.exigir()
        return super().get_queryset().filter(psicologo_id=psicologo_id)


class TodosManager(models.Manager):
    """Sem filtro de dono, para uso deliberado.

    Fica em atributo separado (`objetos_todos`) em vez de flag no manager padrão porque o
    caminho inseguro tem de ser **escrito de propósito** e ficar visível na revisão de código.
    Uma flag opcional seria esquecida ligada.

    Legítimo em: rotinas de descarte (ADR-038), migrações de dados e relatórios internos de
    operação. **Nunca** em código que responde a uma requisição de usuário — e, de todo modo,
    dentro de uma requisição o RLS continua filtrando o que ele devolve.
    """
