"""Versão mínima, só o necessário para o passo 0 provar o isolamento.

O modelo completo — `Caso`, `ResponsavelLegal`, `Pagador`, endereço, medicamento — vem no
passo 2 (ADR-026, ADR-009, ADR-014). Aqui basta *um* modelo de domínio real com dono, para
que o teste tenha o que tentar vazar.
"""

from django.db import models

from core.models import TenantOwnedModel


class Paciente(TenantOwnedModel):
    nome = models.CharField("Nome", max_length=255)

    class Meta:
        verbose_name = "Paciente"
        verbose_name_plural = "Pacientes"
        ordering = ["nome"]

    def __str__(self) -> str:
        return self.nome
