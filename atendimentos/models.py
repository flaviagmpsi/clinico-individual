"""A consulta — o atendimento marcado e, depois, o registro do que aconteceu.

É a âncora do produto: o prontuário pende da consulta **realizada** (ADR-016) e a cobrança, da
consulta **contabilizada** (ADR-023). Os dois eixos são independentes de propósito — é o que cobre
falta cobrada (cobrança sem prontuário) e sessão de cortesia (prontuário sem cobrança).

Aponta para o `Caso`, não para o paciente (ADR-026): uma sessão de casal é **uma** consulta, e por
isso não colide consigo mesma.

**O sistema nunca muda o estado sozinho** (ADR-052). Consulta cuja hora passou e segue `AGENDADA`
é pendência no painel, não é marcada como realizada nem como falta.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from agenda.models import Recorrencia
from core.models import TenantOwnedModel, exigir_mesmo_dono
from pacientes.models import Caso

DURACAO_MAXIMA = 240


class Consulta(TenantOwnedModel):
    class Estado(models.TextChoices):
        AGENDADA = "AGENDADA", "Agendada"
        REALIZADA = "REALIZADA", "Realizada"
        FALTA = "FALTA", "Falta"
        CANCELADA = "CANCELADA", "Cancelada"

    # `PROTECT`, e não `CASCADE`: consulta registrada é histórico clínico e financeiro. Apagar o caso
    # não pode levá-la junto em silêncio — a exclusão de paciente trata isso explicitamente (ADR-048).
    caso = models.ForeignKey(Caso, on_delete=models.PROTECT, related_name="consultas")

    # Origem na regra. Os dois campos andam juntos: consulta avulsa não tem nenhum, consulta prevista
    # tem os dois. `data_prevista` é a identidade da ocorrência e **não muda** na remarcação — é o que
    # impede a regra de gerar a mesma sessão de novo depois que ela foi mudada de dia.
    recorrencia = models.ForeignKey(
        Recorrencia, on_delete=models.PROTECT, null=True, blank=True, related_name="consultas")
    data_prevista = models.DateField("Data prevista pela regra", null=True, blank=True)

    inicio = models.DateTimeField("Início")
    duracao = models.PositiveSmallIntegerField(
        "Duração (minutos)", validators=[MinValueValidator(10), MaxValueValidator(DURACAO_MAXIMA)])
    estado = models.CharField("Situação", max_length=10, choices=Estado.choices, default=Estado.AGENDADA)
    contabilizada = models.BooleanField(
        "Entra na cobrança", default=False,
        help_text="Só tem efeito depois do registro. Proposto pelo perfil: realizada entra; falta entra "
                  "se você cobra falta (ADR-023). Ajustável em cada consulta.")
    remarcada = models.BooleanField(
        "Remarcada à mão", default=False,
        help_text="Uma mudança futura na regra não sobrescreve esta consulta (ADR-022).")
    registrada_em = models.DateTimeField("Registrada em", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Consulta"
        verbose_name_plural = "Consultas"
        ordering = ["inicio"]
        indexes = [models.Index(fields=["psicologo", "inicio"], name="consulta_dono_inicio")]
        constraints = [
            models.UniqueConstraint(
                fields=["recorrencia", "data_prevista"],
                condition=models.Q(recorrencia__isnull=False),
                name="uma_consulta_por_ocorrencia",
            ),
            models.CheckConstraint(
                condition=(models.Q(recorrencia__isnull=True, data_prevista__isnull=True)
                           | models.Q(recorrencia__isnull=False, data_prevista__isnull=False)),
                name="ocorrencia_tem_regra_e_data",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.inicio:%d/%m/%Y %H:%M} · {self.caso}"

    @property
    def fim(self):
        return self.inicio + timedelta(minutes=self.duracao)

    @property
    def avulsa(self) -> bool:
        return self.recorrencia_id is None

    def clean(self):
        super().clean()
        exigir_mesmo_dono(
            self,
            caso=self.caso if self.caso_id else None,
            recorrencia=self.recorrencia if self.recorrencia_id else None,
        )
        if self.recorrencia_id and self.caso_id and self.recorrencia.caso_id != self.caso_id:
            raise ValidationError("A regra de recorrência pertence a outro atendimento.")
        self._recusar_colisao()

    def _recusar_colisao(self):
        """ADR-024: horário ocupado **bloqueia** a marcação.

        Só ocupa a agenda o que não foi cancelado. A busca é limitada às consultas que começam até
        `DURACAO_MAXIMA` minutos antes desta — nenhuma que comece antes disso consegue alcançá-la — e a
        sobreposição é conferida em Python, sem aritmética de intervalo no banco.

        Cobre as consultas já **geradas**. Ocorrências que a regra ainda não materializou são conferidas
        no serviço que marca a consulta (`atendimentos.servicos`), porque dependem da janela da agenda.
        """
        if not (self.inicio and self.duracao) or self.estado == self.Estado.CANCELADA:
            return
        vizinhas = (
            Consulta.objects.exclude(pk=self.pk)
            .exclude(estado=self.Estado.CANCELADA)
            .filter(inicio__lt=self.fim, inicio__gt=self.inicio - timedelta(minutes=DURACAO_MAXIMA))
            .select_related("caso")
        )
        for outra in vizinhas:
            if outra.fim > self.inicio:
                raise ValidationError(
                    f"Horário ocupado: já existe consulta de {outra.caso} às {outra.inicio:%H:%M} "
                    f"de {outra.inicio:%d/%m}.")
