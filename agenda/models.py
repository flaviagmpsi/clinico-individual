"""A regra que prevê as sessões de um caso (ADR-022, ADR-053).

`Recorrencia` não é consulta. É "toda terça, 14h" ou "terça sim, terça não, 14h"; as consultas
concretas são geradas a partir dela e moram em `atendimentos`. A dependência corre num sentido só:
`atendimentos` conhece `agenda`, e `agenda` não conhece `atendimentos` (regra 5 de dependência).

**Paciente avulso não tem recorrência** — não há o que prever (ADR-053). Por isso "avulso" não é um
valor guardado aqui: é a ausência de regra vigente.

**Trocar frequência, dia ou horário não edita a regra.** Encerra a vigente numa data e cria outra a
partir dela — "esta e as próximas" (ADR-022). O passado continua explicado pela regra que valia
quando aconteceu, do mesmo jeito que `CondicaoCobranca` guarda vigência em vez de sobrescrever.
"""

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TenantOwnedModel, exigir_mesmo_dono
from pacientes.models import Caso


class Recorrencia(TenantOwnedModel):
    class Frequencia(models.TextChoices):
        SEMANAL = "SEMANAL", "Semanal"
        QUINZENAL = "QUINZENAL", "Quinzenal"

    class DiaSemana(models.IntegerChoices):
        # Os mesmos números de `date.weekday()`, para comparar sem tradução.
        SEGUNDA = 0, "Segunda-feira"
        TERCA = 1, "Terça-feira"
        QUARTA = 2, "Quarta-feira"
        QUINTA = 3, "Quinta-feira"
        SEXTA = 4, "Sexta-feira"
        SABADO = 5, "Sábado"
        DOMINGO = 6, "Domingo"

    caso = models.ForeignKey(Caso, on_delete=models.CASCADE, related_name="recorrencias")
    frequencia = models.CharField("Frequência", max_length=10, choices=Frequencia.choices)
    dia_semana = models.PositiveSmallIntegerField("Dia da semana", choices=DiaSemana.choices)
    hora = models.TimeField("Horário")
    duracao = models.PositiveSmallIntegerField(
        "Duração (minutos)", validators=[MinValueValidator(10), MaxValueValidator(240)])
    inicio = models.DateField(
        "Vale a partir de",
        help_text="Na quinzenal, a primeira sessão a partir desta data define quais semanas são as de atendimento.")
    fim = models.DateField(
        "Encerrada em", null=True, blank=True,
        help_text="Nenhuma sessão é prevista nesta data nem depois. Vazio enquanto a regra valer.")

    class Meta:
        verbose_name = "Recorrência"
        verbose_name_plural = "Recorrências"
        ordering = ["-inicio"]
        constraints = [
            # `>=` e não `>`: uma regra trocada no mesmo dia em que foi criada — corrigir um horário
            # recém-cadastrado, o caso mais comum — precisa poder terminar no próprio dia de início, e
            # aí não prevê sessão nenhuma.
            models.CheckConstraint(
                condition=models.Q(fim__isnull=True) | models.Q(fim__gte=models.F("inicio")),
                name="recorrencia_fim_nao_antes_do_inicio",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_frequencia_display()} · {self.get_dia_semana_display()}, {self.hora:%H:%M}"

    def clean(self):
        super().clean()
        exigir_mesmo_dono(self, caso=self.caso if self.caso_id else None)

    @property
    def primeira_ocorrencia(self) -> date:
        """O primeiro dia a partir de `inicio` que cai no dia da semana da regra — a âncora da quinzenal."""
        return self.inicio + timedelta(days=(self.dia_semana - self.inicio.weekday()) % 7)

    @property
    def _passo(self) -> int:
        return 14 if self.frequencia == self.Frequencia.QUINZENAL else 7

    def ocorre_em(self, dia: date) -> bool:
        primeira = self.primeira_ocorrencia
        if dia < primeira or (self.fim is not None and dia >= self.fim):
            return False
        return (dia - primeira).days % self._passo == 0

    def ocorrencias(self, de: date, ate: date) -> list[date]:
        """Datas previstas no intervalo fechado `[de, ate]`, respeitando início, fim e a alternância."""
        primeira = self.primeira_ocorrencia
        passo = self._passo
        if de > primeira:
            saltos = -(-(de - primeira).days // passo)  # divisão arredondada para cima
            dia = primeira + timedelta(days=saltos * passo)
        else:
            dia = primeira
        datas = []
        while dia <= ate and (self.fim is None or dia < self.fim):
            datas.append(dia)
            dia += timedelta(days=passo)
        return datas


class HorarioDisponivel(TenantOwnedModel):
    """Um bloco da grade semanal que o psicólogo declara: "terça, das 14h às 20h" (ADR-029).

    É **disponibilidade**, não vaga remanescente: o que já tem paciente é derivado das regras de
    frequência (`agenda.grade`), para ninguém precisar apagar o horário ao marcar um paciente. A grade
    **não bloqueia** nada — marcar fora dela só gera aviso (ADR-056).
    """

    dia_semana = models.PositiveSmallIntegerField("Dia da semana", choices=Recorrencia.DiaSemana.choices)
    inicio = models.TimeField("Das")
    fim = models.TimeField("Até")

    class Meta:
        verbose_name = "Horário disponível"
        verbose_name_plural = "Horários disponíveis"
        ordering = ["dia_semana", "inicio"]
        constraints = [
            models.CheckConstraint(condition=models.Q(fim__gt=models.F("inicio")), name="horario_fim_depois_do_inicio"),
        ]

    def __str__(self) -> str:
        return f"{self.get_dia_semana_display()}, {self.inicio:%H:%M}–{self.fim:%H:%M}"

    def clean(self):
        super().clean()
        if self.inicio is None or self.fim is None or self.dia_semana is None:
            return
        if self.fim <= self.inicio:
            raise ValidationError({"fim": "O fim precisa ser depois do início."})
        # Sobreposto é recusado; encostado ("8h–12h" e "12h–14h") não — ADR-056. Sobreposição contaria a
        # mesma hora duas vezes na ocupação.
        sobreposto = (
            HorarioDisponivel.objects.exclude(pk=self.pk)
            .filter(dia_semana=self.dia_semana, inicio__lt=self.fim, fim__gt=self.inicio)
            .first()
        )
        if sobreposto:
            raise ValidationError(f"Este bloco se sobrepõe a outro já declarado: {sobreposto}.")
