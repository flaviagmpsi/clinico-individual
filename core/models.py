"""Base de todo modelo de domínio.

ADR-001: o dono é explícito em cada tabela. Não há modelo de domínio sem dono — se algum
aparecer, é porque alguém esqueceu de herdar daqui, e o RLS (terceira camada) vai recusar
o acesso mesmo assim.
"""

from django.conf import settings
from django.db import models

from core import contexto
from core.managers import TenantManager, TodosManager


class TenantOwnedModel(models.Model):
    """Modelo que pertence a um psicólogo.

    O FK aponta para `settings.TENANT_MODEL` em vez de para `contas.Psicologo` porque
    `core` não pode depender de app de domínio (regra 1 de dependência). O mesmo padrão que
    o Django usa em `AUTH_USER_MODEL`.
    """

    psicologo = models.ForeignKey(
        settings.TENANT_MODEL,
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s",
        editable=False,
        verbose_name="Psicólogo",
    )

    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    objects = TenantManager()
    objetos_todos = TodosManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Preencher o dono a partir do contexto, e não pedir a quem chama, elimina a classe
        # inteira de bug "salvei sem dono" e a de "salvei com o dono errado por copiar e colar".
        if self.psicologo_id is None:
            self.psicologo_id = contexto.exigir()
        elif self.psicologo_id != contexto.atual() and contexto.atual() is not None:
            raise contexto.EscopoNaoDefinido(
                f"Tentativa de gravar registro do psicólogo {self.psicologo_id} "
                f"dentro do escopo do psicólogo {contexto.atual()}."
            )
        super().save(*args, **kwargs)
