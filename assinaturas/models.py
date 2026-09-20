"""A assinatura do psicólogo: se a conta pode usar o sistema — e nada sobre o que há dentro dela.

`assinaturas` **não toca dado clínico** (S-03): sabe em que estado a conta está, não lê paciente, sessão nem
prontuário. Depende só de `core` e de `contas`.

ADR-094 (revoga a parte "sem teste gratuito" da ADR-036): a conta pode começar por um **teste grátis de 7 dias**,
sem dado de pagamento, ou assinar de uma vez. O teste é um por conta — e conta é um CRP, que é único.

Os estados daqui são os dois que já existem no produto. `TOLERANCIA`, `SOMENTE_LEITURA`, `ARQUIVADA` e
`DESCARTADA` (ADR-038) entram junto com a cobrança de verdade (S-01), que é quem os aciona.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import TenantOwnedModel

DIAS_DE_TESTE = 7


class Assinatura(TenantOwnedModel):
    class Estado(models.TextChoices):
        TESTE = "TESTE", "Teste grátis"
        ATIVA = "ATIVA", "Ativa"

    class Meio(models.TextChoices):
        # ADR-036: só meios que cobram sozinhos. Boleto fica de fora.
        CARTAO = "CARTAO", "Cartão de crédito"
        PIX_AUTOMATICO = "PIX_AUTOMATICO", "PIX Automático"

    estado = models.CharField("Estado", max_length=20, choices=Estado.choices)
    teste_termina_em = models.DateTimeField("Teste termina em", null=True, blank=True)
    ativa_desde = models.DateTimeField("Ativa desde", null=True, blank=True)
    meio = models.CharField("Meio de pagamento", max_length=20, choices=Meio.choices, blank=True)
    # O identificador da assinatura no Asaas, quando houver (S-01). Dado de cartão **nunca** passa por aqui nem
    # por lugar nenhum do Hamilton: ele é digitado na página do Asaas.
    id_no_gateway = models.CharField("Identificador no gateway", max_length=64, blank=True)

    class Meta:
        verbose_name = "Assinatura"
        verbose_name_plural = "Assinaturas"
        constraints = [
            models.UniqueConstraint(fields=["psicologo"], name="uma_assinatura_por_psicologo"),
        ]

    def __str__(self) -> str:
        return f"{self.get_estado_display()} · psicólogo {self.psicologo_id}"

    def clean(self):
        super().clean()
        if self.estado == self.Estado.TESTE and self.teste_termina_em is None:
            raise ValidationError({"teste_termina_em": "O teste precisa de data para terminar."})
        if self.estado == self.Estado.ATIVA and (self.ativa_desde is None or not self.meio):
            raise ValidationError("Assinatura ativa tem data de início e meio de pagamento.")

    # O fim do teste é **calculado**, e não um estado gravado por tarefa agendada: na hora em que o prazo passa, a
    # conta já está com o teste encerrado, sem depender de nada ter rodado.
    def teste_encerrado(self, agora=None) -> bool:
        return self.estado == self.Estado.TESTE and (agora or timezone.now()) >= self.teste_termina_em

    def em_teste(self, agora=None) -> bool:
        return self.estado == self.Estado.TESTE and not self.teste_encerrado(agora)

    def libera_o_sistema(self, agora=None) -> bool:
        return self.estado == self.Estado.ATIVA or self.em_teste(agora)

    def dias_de_teste_restantes(self, agora=None) -> int:
        """Dias **cheios ou começados** que faltam: faltando 6 dias e 3 horas, a tela diz 7."""
        if not self.em_teste(agora):
            return 0
        falta = self.teste_termina_em - (agora or timezone.now())
        return falta.days + (1 if falta - timedelta(days=falta.days) > timedelta(0) else 0)
