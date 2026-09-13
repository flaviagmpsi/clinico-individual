"""Base de todo modelo de domínio.

ADR-001: o dono é explícito em cada tabela. Não há modelo de domínio sem dono — se algum
aparecer, é porque alguém esqueceu de herdar daqui, e o RLS (terceira camada) vai recusar
o acesso mesmo assim.
"""

from django.conf import settings
from django.db import models

from core import contexto
from core.managers import TenantManager, TodosManager


class ValidaAoSalvar(models.Model):
    """Roda os validadores do model em toda gravação, não só em formulário (P-69).

    Sem isto, `RegexValidator` de CPF e telefone só valia dentro de `ModelForm`: um comando de
    management, o shell ou uma view futura sem formulário gravavam `cpf="111.111.111"` sem
    reclamar. A regra tem de valer independentemente de por onde o dado entra.

    **Gravação parcial valida só o que grava.** O login do Django faz
    `save(update_fields=["last_login"])`; validar a linha inteira ali trancaria para fora do
    sistema qualquer psicólogo com um dado legado fora do formato — punindo o login por um
    campo que ele nem está alterando. Unicidade e constraints também ficam de fora nesse caso:
    o banco continua garantindo as duas.
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        campos_gravados = kwargs.get("update_fields")
        if campos_gravados is None:
            self.full_clean()
        else:
            nomes = set(campos_gravados)
            fora = [f.name for f in self._meta.concrete_fields
                    if f.name not in nomes and f.attname not in nomes]
            self.full_clean(exclude=fora, validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)


class TenantOwnedModel(ValidaAoSalvar):
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
        elif self.psicologo_id != contexto.exigir():
            raise contexto.EscopoNaoDefinido(
                f"Tentativa de gravar registro do psicólogo {self.psicologo_id} "
                f"dentro do escopo do psicólogo {contexto.atual()}."
            )
        super().save(*args, **kwargs)

    # `contexto.exigir()` em vez de comparar com `contexto.atual()` tolerando `None`: a versão
    # anterior pulava a checagem exatamente quando não havia escopo — comando de management,
    # tarefa agendada, shell —, que é onde não existe middleware para corrigir o engano. Gravar
    # para outro psicólogo passava em silêncio. Quem precisa mesmo gravar fora de requisição
    # declara para quem, com `contexto.como(psicologo_id)`.
