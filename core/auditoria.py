"""Trilha de auditoria de dado clínico (F-05, ADR-057).

Duas portas:

- **`Auditado`**, mixin de model: criar, alterar e excluir entram na trilha sozinhos, por qualquer caminho
  que grave pelo model — tela, serviço, comando. Esquecer de registrar deixa de ser possível.
- **`registrar`**, para o que o model não enxerga: **visualizar** e **exportar** acontecem na view.

O que fica fora, de propósito: `QuerySet.update()`, `bulk_create` e a exclusão em cascata não passam pelo
`save()`/`delete()` da instância. Dado clínico não deve ser gravado por esses caminhos; a exclusão em cascata
do paciente fica coberta pelo registro de exclusão do próprio paciente.
"""

from django.db import models

from core.models import RegistroAuditoria

Acao = RegistroAuditoria.Acao

# O que não é dado do paciente: chave, dono e carimbos de data que mudam a cada gravação.
_FORA_DA_TRILHA = {"id", "psicologo", "criado_em", "atualizado_em"}


def _referencia(objeto) -> tuple[str, int]:
    return objeto._meta.label_lower, objeto.pk


def _gravar(acao: str, alvo: tuple[str, int], titular: tuple[str, int], campos=()) -> RegistroAuditoria:
    return RegistroAuditoria.objects.create(
        acao=acao, alvo=alvo[0], alvo_id=alvo[1], titular=titular[0], titular_id=titular[1], campos=sorted(campos))


def registrar(acao: str, objeto, campos=()) -> RegistroAuditoria:
    """Registra uma ação sobre um objeto auditado. Nas views: `registrar(Acao.VER, paciente)`."""
    return _gravar(acao, _referencia(objeto), _referencia(objeto.auditoria_titular()), campos)


class Auditado(models.Model):
    """Model de dado clínico: criar, alterar e excluir entram na trilha.

    Herde **antes** de `TenantOwnedModel` — `class Paciente(Auditado, TenantOwnedModel)` —, para o registro ser
    gravado depois que o dono foi preenchido.
    """

    class Meta:
        abstract = True

    def auditoria_titular(self):
        """De quem é o dado. O padrão é o próprio registro; o responsável legal devolve o paciente."""
        return self

    def save(self, *args, **kwargs):
        criando = self._state.adding
        alterados = [] if criando else self._campos_alterados(kwargs.get("update_fields"))
        super().save(*args, **kwargs)
        if criando:
            registrar(Acao.CRIAR, self)
        elif alterados:
            registrar(Acao.ALTERAR, self, alterados)

    def delete(self, *args, **kwargs):
        # Capturados antes: depois do `delete()` o Django zera a chave da instância.
        alvo = _referencia(self)
        titular = _referencia(self.auditoria_titular())
        resultado = super().delete(*args, **kwargs)
        _gravar(Acao.EXCLUIR, alvo, titular)
        return resultado

    def _campos_alterados(self, update_fields) -> list[str]:
        """Nomes dos campos que diferem do que está no banco — nunca os valores (ADR-057)."""
        campos = [f for f in self._meta.concrete_fields if f.name not in _FORA_DA_TRILHA]
        if update_fields is not None:
            nomes = set(update_fields)
            campos = [f for f in campos if f.name in nomes or f.attname in nomes]
        anterior = type(self).objects.filter(pk=self.pk).values(*[f.attname for f in campos]).first()
        if anterior is None:
            return [f.name for f in campos]
        return [f.name for f in campos if anterior[f.attname] != getattr(self, f.attname)]
