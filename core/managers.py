"""Manager que recusa consulta sem dono definido.

Segunda das três camadas da ADR-001. A primeira é o dono explícito no modelo; a terceira é o
RLS no Postgres. Esta camada existe para o erro aparecer **no teste do desenvolvedor**, com
stack trace apontando a linha, em vez de aparecer no banco como silêncio — ou, pior, como
dado de outro psicólogo.
"""

from django.db import models

from core import contexto


class TenantQuerySet(models.QuerySet):
    def sem_escopo(self) -> "TenantQuerySet":
        """Escapa do filtro de dono. Use com parcimônia e comente o porquê.

        Legítimo em: rotinas de descarte (ADR-038), migrações de dados e relatórios
        internos de operação. **Nunca** em código que responde a uma requisição de usuário.
        """
        return self


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Filtra por dono automaticamente, e explode se não souber quem é o dono."""

    def get_queryset(self) -> TenantQuerySet:
        psicologo_id = contexto.exigir()
        return super().get_queryset().filter(psicologo_id=psicologo_id)


class TodosManager(models.Manager.from_queryset(TenantQuerySet)):
    """Sem filtro de dono, para uso deliberado.

    Fica em atributo separado (`objetos_todos`) em vez de flag no manager padrão porque o
    caminho inseguro tem de ser **escrito de propósito** e ficar visível na revisão de código.
    Uma flag opcional seria esquecida ligada.
    """
