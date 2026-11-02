"""O registro de que um lembrete já saiu — a prova de idempotência do cron (ADR-144, RF08)."""

from django.db import models

from core.models import TenantOwnedModel


class LembreteEnviado(TenantOwnedModel):
    """Um lembrete que já foi enviado (ou simulado), para o cron não repetir.

    `assunto` é a chave do envio único: `agenda_do_dia:2026-11-02`, `pendencias:2026-11-02`, `sessao:1234`,
    `pagamento:567`. A constraint de unicidade por (psicólogo, assunto) garante que o mesmo lembrete não sai duas
    vezes, mesmo que o cron dispare em paralelo. `simulado` marca os que não tocaram a Meta (sem cartão/ativação).
    """

    assunto = models.CharField("Assunto", max_length=80)
    simulado = models.BooleanField("Simulado", default=False)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Lembrete enviado"
        verbose_name_plural = "Lembretes enviados"
        ordering = ["-criado_em"]
        constraints = [
            models.UniqueConstraint(fields=["psicologo", "assunto"], name="um_lembrete_por_assunto"),
        ]

    def __str__(self) -> str:
        return self.assunto
