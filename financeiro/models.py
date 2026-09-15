"""O pagamento — registrado pelo psicólogo, sempre (ADR-035, ADR-062, ADR-063).

O que é **devido** não é gravado: é calculado da condição de cobrança e das consultas cobradas
(`financeiro.servicos`). Gravado é só o que o psicólogo informa — quanto recebeu, quando e como. Assim, corrigir
uma consulta ou uma condição de cobrança muda o devido sem deixar cobrança órfã para trás.

Cada pagamento é de **uma** referência, nunca das duas:
- **mês** — a mensalidade daquele mês;
- **consulta** — a sessão, para quem paga por sessão.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from atendimentos.models import Consulta
from core.models import TenantOwnedModel, exigir_mesmo_dono
from pacientes.models import Caso


class Pagamento(TenantOwnedModel):
    class Forma(models.TextChoices):
        PIX = "PIX", "Pix"
        CARTAO = "CARTAO", "Cartão"
        DINHEIRO = "DINHEIRO", "Dinheiro"
        TRANSFERENCIA = "TRANSFERENCIA", "Transferência"

    # `PROTECT`: pagamento é histórico financeiro. Apagar o caso ou a consulta não pode levá-lo junto em silêncio.
    caso = models.ForeignKey(Caso, on_delete=models.PROTECT, related_name="pagamentos")
    mes_referencia = models.DateField(
        "Mês de referência", null=True, blank=True, help_text="Primeiro dia do mês da mensalidade.")
    consulta = models.ForeignKey(
        Consulta, on_delete=models.PROTECT, null=True, blank=True, related_name="pagamentos",
        verbose_name="Sessão")
    valor = models.DecimalField("Valor", max_digits=10, decimal_places=2,
                                validators=[MinValueValidator(Decimal("0.01"))])
    data = models.DateField("Pago em")
    forma = models.CharField("Forma de pagamento", max_length=13, choices=Forma.choices)
    observacao = models.TextField("Observação", blank=True)

    class Meta:
        verbose_name = "Pagamento"
        verbose_name_plural = "Pagamentos"
        ordering = ["-data", "-criado_em"]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(mes_referencia__isnull=False, consulta__isnull=True)
                           | models.Q(mes_referencia__isnull=True, consulta__isnull=False)),
                name="pagamento_de_um_mes_ou_de_uma_sessao",
            ),
        ]

    def __str__(self) -> str:
        return f"R$ {self.valor} em {self.data:%d/%m/%Y} · {self.caso}"

    def clean(self):
        super().clean()
        exigir_mesmo_dono(
            self,
            caso=self.caso if self.caso_id else None,
            consulta=self.consulta if self.consulta_id else None,
        )
        if self.consulta_id and self.caso_id and self.consulta.caso_id != self.caso_id:
            raise ValidationError("A sessão pertence a outro atendimento.")
        if self.consulta_id and not self.consulta.cobrada:
            raise ValidationError("Falta remarcada não é cobrada e não recebe pagamento.")
        if self.mes_referencia and self.mes_referencia.day != 1:
            raise ValidationError({"mes_referencia": "O mês de referência é guardado pelo primeiro dia do mês."})
