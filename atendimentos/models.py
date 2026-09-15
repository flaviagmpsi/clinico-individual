"""A consulta — o registro do que aconteceu, feito pelo psicólogo (ADR-060).

É a âncora do produto: o prontuário pende da consulta **realizada** (ADR-016) e a cobrança, da consulta
**cobrada**. Desde a ADR-060 a cobrança deriva da situação: realizada é sempre cobrada; falta é cobrada ou
remarcada.

**O sistema nunca cria consulta.** A frequência prevê sessões (`atendimentos.servicos.sessoes_previstas`), mas
previsão não é registro: a consulta nasce quando o psicólogo a cadastra, e sessão prevista que passou sem
cadastro é pendência (ADR-052).

Aponta para o `Caso`, não para o paciente (ADR-026): uma sessão de casal é **uma** consulta.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from agenda.models import Recorrencia
from core.models import TenantOwnedModel, exigir_mesmo_dono
from pacientes.models import Caso

DURACAO_MAXIMA = 240


class Consulta(TenantOwnedModel):
    class Estado(models.TextChoices):
        REALIZADA = "REALIZADA", "Realizada"
        FALTA_COBRADA = "FALTA_COBRADA", "Falta cobrada"
        FALTA_REMARCADA = "FALTA_REMARCADA", "Falta remarcada"

    # `PROTECT`, e não `CASCADE`: consulta registrada é histórico clínico e financeiro. Apagar o caso
    # não pode levá-la junto em silêncio — a exclusão de paciente trata isso explicitamente (ADR-048).
    caso = models.ForeignKey(Caso, on_delete=models.PROTECT, related_name="consultas")

    # Da frequência: os dois campos juntos, e `data_prevista` é a sessão prevista que este cadastro tirou da
    # pendência. Avulsa — paciente avulso, sessão extra, a remarcada que aconteceu —: nenhum dos dois.
    recorrencia = models.ForeignKey(
        Recorrencia, on_delete=models.PROTECT, null=True, blank=True, related_name="consultas")
    data_prevista = models.DateField("Data prevista pela frequência", null=True, blank=True)

    inicio = models.DateTimeField("Início")
    duracao = models.PositiveSmallIntegerField(
        "Duração (minutos)", validators=[MinValueValidator(10), MaxValueValidator(DURACAO_MAXIMA)])
    estado = models.CharField("Situação", max_length=16, choices=Estado.choices)

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
        return f"{timezone.localtime(self.inicio):%d/%m/%Y %H:%M} · {self.caso}"

    @property
    def fim(self):
        return self.inicio + timedelta(minutes=self.duracao)

    @property
    def avulsa(self) -> bool:
        return self.recorrencia_id is None

    @property
    def cobrada(self) -> bool:
        """Deriva da situação (ADR-060): só a falta remarcada não é cobrada."""
        return self.estado != self.Estado.FALTA_REMARCADA

    def clean(self):
        super().clean()
        exigir_mesmo_dono(
            self,
            caso=self.caso if self.caso_id else None,
            recorrencia=self.recorrencia if self.recorrencia_id else None,
        )
        if self.recorrencia_id and self.caso_id and self.recorrencia.caso_id != self.caso_id:
            raise ValidationError("A frequência pertence a outro atendimento.")
        if self.recorrencia_id and self.data_prevista and not self.recorrencia.ocorre_em(self.data_prevista):
            raise ValidationError("Esta data não é uma sessão prevista pela frequência.")
        self._recusar_colisao()

    def _recusar_colisao(self):
        """ADR-024: duas consultas não ocupam o mesmo horário.

        Falta remarcada não ocupa horário — a sessão não aconteceu e o horário ficou livre. A busca é limitada às
        consultas que começam até `DURACAO_MAXIMA` minutos antes desta — nenhuma que comece antes disso consegue
        alcançá-la — e a sobreposição é conferida em Python, sem aritmética de intervalo no banco.
        """
        if not (self.inicio and self.duracao) or self.estado == self.Estado.FALTA_REMARCADA:
            return
        vizinhas = (
            Consulta.objects.exclude(pk=self.pk)
            .exclude(estado=self.Estado.FALTA_REMARCADA)
            .filter(inicio__lt=self.fim, inicio__gt=self.inicio - timedelta(minutes=DURACAO_MAXIMA))
            .select_related("caso")
        )
        for outra in vizinhas:
            if outra.fim > self.inicio:
                local = timezone.localtime(outra.inicio)
                raise ValidationError(
                    f"Horário ocupado: já existe consulta de {outra.caso} às {local:%H:%M} de {local:%d/%m}.")


class Desfecho(TenantOwnedModel):
    """Como um atendimento terminou (ADR-049) — e, se o paciente voltou, quando (ADR-055).

    Do **caso**, não do paciente: num casal, o desfecho é do atendimento inteiro. Um caso pode ter vários
    ao longo dos anos — alta, retorno, nova alta —, mas só um **em aberto**, que é o que faz o atendimento
    contar como encerrado.

    O **momento** da desistência não é perguntado: `sessoes_realizadas` conta (ADR-027).
    """

    class Tipo(models.TextChoices):
        ALTA = "ALTA", "Alta"
        DESISTENCIA = "DESISTENCIA", "Desistência"
        ENCAMINHAMENTO = "ENCAMINHAMENTO", "Encaminhamento"
        INTERRUPCAO = "INTERRUPCAO", "Interrupção pelo psicólogo"

    class Iniciativa(models.TextChoices):
        PACIENTE = "PACIENTE", "Do paciente"
        PSICOLOGO = "PSICOLOGO", "Do psicólogo"

    # Os dois tipos que já dizem de quem partiu. Alta e encaminhamento podem vir de qualquer lado.
    INICIATIVA_DO_TIPO = {Tipo.DESISTENCIA: Iniciativa.PACIENTE, Tipo.INTERRUPCAO: Iniciativa.PSICOLOGO}

    # `PROTECT`: o desfecho é histórico que a análise usa (ADR-027) — sai só por decisão explícita.
    caso = models.ForeignKey(Caso, on_delete=models.PROTECT, related_name="desfechos")
    tipo = models.CharField("Desfecho", max_length=15, choices=Tipo.choices)
    iniciativa = models.CharField("Iniciativa", max_length=10, choices=Iniciativa.choices)
    data = models.DateField("Data")
    motivo = models.TextField("Motivo", blank=True)
    retomado_em = models.DateField("Retomado em", null=True, blank=True)

    class Meta:
        verbose_name = "Desfecho"
        verbose_name_plural = "Desfechos"
        ordering = ["-data", "-criado_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["caso"], condition=models.Q(retomado_em__isnull=True), name="um_desfecho_em_aberto_por_caso"),
            models.CheckConstraint(
                condition=models.Q(retomado_em__isnull=True) | models.Q(retomado_em__gte=models.F("data")),
                name="retomada_nao_antes_do_desfecho"),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} em {self.data:%d/%m/%Y} · {self.caso}"

    def clean(self):
        super().clean()
        exigir_mesmo_dono(self, caso=self.caso if self.caso_id else None)
        esperada = self.INICIATIVA_DO_TIPO.get(self.tipo)
        if esperada and self.iniciativa and self.iniciativa != esperada:
            raise ValidationError({"iniciativa": f"{self.get_tipo_display()} é sempre "
                                                 f"{self.Iniciativa(esperada).label.lower()}."})

    @property
    def sessoes_realizadas(self) -> int:
        """Sessões realizadas até o desfecho, contadas desde a última retomada — o "momento" (ADR-027)."""
        from datetime import datetime, time

        def meia_noite(dia):
            return timezone.make_aware(datetime.combine(dia, time.min))

        consultas = self.caso.consultas.filter(estado=Consulta.Estado.REALIZADA,
                                               inicio__lt=meia_noite(self.data + timedelta(days=1)))
        retomada = (
            self.caso.desfechos.exclude(pk=self.pk)
            .filter(retomado_em__isnull=False, retomado_em__lte=self.data)
            .order_by("-retomado_em").first()
        )
        if retomada:
            consultas = consultas.filter(inicio__gte=meia_noite(retomada.retomado_em))
        return consultas.count()
