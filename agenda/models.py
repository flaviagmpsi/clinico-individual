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



def serie_semanal(dia_semana: int, passo: int, inicio: date, fim: date | None,
                  de: date, ate: date) -> list[date]:
    """As datas de um compromisso semanal ou quinzenal no intervalo fechado `[de, ate]`.

    Saiu de `Recorrencia.ocorrencias` quando o compromisso fora da clínica passou a precisar da mesma conta
    (ADR-122). A aritmética é a de sempre: ancora na primeira ocorrência a partir de `inicio`, anda de `passo`
    em `passo`, e para em `fim` — que é exclusivo, porque a regra não vale no dia em que termina.
    """
    primeira = inicio + timedelta(days=(dia_semana - inicio.weekday()) % 7)
    if de > primeira:
        saltos = -(-(de - primeira).days // passo)  # divisão arredondada para cima
        dia = primeira + timedelta(days=saltos * passo)
    else:
        dia = primeira
    datas = []
    while dia <= ate and (fim is None or dia < fim):
        datas.append(dia)
        dia += timedelta(days=passo)
    return datas


def _enesimo_dia_do_mes(ano: int, mes: int, dia_semana: int, n: int) -> date:
    """O n-ésimo (1 a 4) `dia_semana` do mês. Sempre existe: todo mês tem ao menos quatro de cada dia."""
    primeiro = date(ano, mes, 1)
    deslocamento = (dia_semana - primeiro.weekday()) % 7
    return primeiro + timedelta(days=deslocamento + 7 * (n - 1))


def serie_mensal(dia_semana: int, ordinais: tuple[int, ...], inicio: date, fim: date | None,
                 de: date, ate: date) -> list[date]:
    """As datas da quinzenal por **par de semanas do mês** no intervalo fechado `[de, ate]` (ADR-146).

    Quinzenal aqui não é "de 14 em 14 dias": é um par fixo de semanas — 1ª e 3ª, ou 2ª e 4ª. Assim são sempre
    duas sessões por mês, nunca três, e a 5ª semana, quando existe, é ignorada. Dentro do par o intervalo é de
    14 dias; entre o fim de um mês e o começo do outro ele pode esticar, e é o preço de "sempre duas".
    """
    datas = []
    ano, mes = de.year, de.month
    while date(ano, mes, 1) <= ate:
        for n in ordinais:
            dia = _enesimo_dia_do_mes(ano, mes, dia_semana, n)
            if de <= dia <= ate and inicio <= dia and (fim is None or dia < fim):
                datas.append(dia)
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return sorted(datas)


class Recorrencia(TenantOwnedModel):
    class Frequencia(models.TextChoices):
        SEMANAL = "SEMANAL", "Semanal"
        QUINZENAL = "QUINZENAL", "Quinzenal"

    class SemanasDoMes(models.TextChoices):
        # As duas semanas do mês em que a quinzenal cai (ADR-146). Só esses dois pares garantem "sempre duas,
        # nunca três", com 14 dias dentro do par; um par como "3ª e 5ª" deixaria mês sem 5ª semana com uma só.
        PRIMEIRA_TERCEIRA = "1E3", "1ª e 3ª semana do mês"
        SEGUNDA_QUARTA = "2E4", "2ª e 4ª semana do mês"

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
    semanas_do_mes = models.CharField(
        "Semanas do mês", max_length=3, choices=SemanasDoMes.choices, blank=True,
        help_text="Só na quinzenal: em quais duas semanas do mês cai a sessão (ADR-146).")
    dia_semana = models.PositiveSmallIntegerField("Dia da semana", choices=DiaSemana.choices)
    hora = models.TimeField("Horário")
    duracao = models.PositiveSmallIntegerField(
        "Duração (minutos)", validators=[MinValueValidator(10), MaxValueValidator(240)])
    inicio = models.DateField(
        "Vale a partir de",
        help_text="Sessões anteriores a esta data não mudam (ADR-022).")
    fim = models.DateField(
        "Encerrada em", null=True, blank=True,
        help_text="Nenhuma sessão é prevista nesta data nem depois. Vazio enquanto a regra valer.")
    # ADR-120: o psicólogo informa no cadastro a data da primeira sessão, e ela nem sempre cai no dia da semana
    # que ele escolheu para o horário fixo — combinar "a primeira é sexta que vem, depois toda terça" é comum.
    # Guardada **à parte** do dia da semana porque é o que ela é: uma exceção, de uma vez só. Em branco quando a
    # primeira sessão já cai no dia certo, porque aí a série semanal dá conta dela.
    primeira_sessao_em = models.DateField(
        "Primeira sessão", null=True, blank=True,
        help_text="Só quando a primeira sessão cai em outro dia da semana. Vale uma vez; depois segue o fixo.")

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
            # A quinzenal guarda as semanas do mês; a semanal, não. Espelha o padrão do `Compromisso`: sem isto,
            # uma quinzenal sem o par ficaria sem saber que semanas prever, e sem erro em lugar nenhum.
            models.CheckConstraint(
                condition=(models.Q(frequencia="QUINZENAL") & ~models.Q(semanas_do_mes=""))
                          | (~models.Q(frequencia="QUINZENAL") & models.Q(semanas_do_mes="")),
                name="recorrencia_semanas_do_mes_so_na_quinzenal",
            ),
        ]

    def __str__(self) -> str:
        quando = f"{self.get_dia_semana_display()}, {self.hora:%H:%M}"
        if self.frequencia == self.Frequencia.QUINZENAL and self.semanas_do_mes:
            return f"{self.get_frequencia_display()} ({self.get_semanas_do_mes_display().lower()}) · {quando}"
        return f"{self.get_frequencia_display()} · {quando}"

    def clean(self):
        super().clean()
        exigir_mesmo_dono(self, caso=self.caso if self.caso_id else None)
        if self.frequencia == self.Frequencia.QUINZENAL:
            if not self.semanas_do_mes:
                raise ValidationError("A quinzenal precisa das semanas do mês (1ª e 3ª, ou 2ª e 4ª).")
        else:
            self.semanas_do_mes = ""

    @property
    def primeira_ocorrencia(self) -> date:
        """O primeiro dia do padrão fixo a partir de `inicio`, sem a exceção da ADR-120.

        Na semanal, o próximo dia da semana da regra. Na quinzenal, a primeira das semanas do mês escolhidas —
        70 dias de janela bastam, porque todo mês tem a 1ª..4ª ocorrência do dia.
        """
        if self.frequencia == self.Frequencia.QUINZENAL:
            return serie_mensal(self.dia_semana, self._ordinais, self.inicio, None,
                                self.inicio, self.inicio + timedelta(days=70))[0]
        return self.inicio + timedelta(days=(self.dia_semana - self.inicio.weekday()) % 7)

    @property
    def _ordinais(self) -> tuple[int, int]:
        """As duas semanas do mês da quinzenal, como ordinais do dia da semana (1ª e 3ª → (1, 3))."""
        return (1, 3) if self.semanas_do_mes == self.SemanasDoMes.PRIMEIRA_TERCEIRA else (2, 4)

    def _dentro_da_vigencia(self, dia: date) -> bool:
        return self.inicio <= dia and (self.fim is None or dia < self.fim)

    def ocorre_em(self, dia: date) -> bool:
        # A primeira sessão avulsa conta como ocorrência: é por ela que a tela de cadastrar a sessão aceita a
        # data (ADR-120). Não entra na contagem das semanas do mês da quinzenal.
        if self.primeira_sessao_em == dia and self._dentro_da_vigencia(dia):
            return True
        return dia in self.ocorrencias(dia, dia)

    @property
    def rotulo(self) -> str:
        """Quem ocupa este horário, para a grade da semana. `Compromisso` tem o mesmo, com o título dele."""
        return str(self.caso)

    def ocorrencias(self, de: date, ate: date) -> list[date]:
        """Datas previstas no intervalo fechado `[de, ate]`, respeitando início, fim e a frequência."""
        if self.frequencia == self.Frequencia.QUINZENAL:
            datas = serie_mensal(self.dia_semana, self._ordinais, self.inicio, self.fim, de, ate)
        else:
            datas = serie_semanal(self.dia_semana, 7, self.inicio, self.fim, de, ate)
        # A primeira sessão fora do dia fixo entra aqui, uma vez só, na ordem certa (ADR-120).
        avulsa = self.primeira_sessao_em
        if (avulsa is not None and de <= avulsa <= ate
                and self._dentro_da_vigencia(avulsa) and avulsa not in datas):
            datas.append(avulsa)
            datas.sort()
        return datas



class Compromisso(TenantOwnedModel):
    """Um compromisso de trabalho que **não** é atendimento particular (ADR-122).

    Supervisão, paciente de ONG, aula, reunião. O psicólogo escreve o que é e quando é, e o sistema só o
    desenha na agenda e conta as horas. Decisão do usuário, nas palavras dele: *"é puramente visual pra minha
    agenda ficar mais fiel à quantidade de coisas que eu faço no meu trabalho"*.

    **O que ele deliberadamente não é:** não tem paciente nem caso, não vira `Consulta`, não entra no
    financeiro, não gera prontuário e nunca aparece como sessão a cadastrar. Nenhum dos apps clínicos precisa
    saber que ele existe — é por isso que ele mora aqui, em `agenda`, e não em `atendimentos`.

    **O que ele é:** tempo ocupado. Some dos horários livres oferecidos no cadastro de paciente novo, para o
    sistema não propor marcar alguém por cima da supervisão, e entra na conta de horas trabalhadas.
    """

    class Frequencia(models.TextChoices):
        UNICO = "UNICO", "Uma vez só"
        SEMANAL = "SEMANAL", "Toda semana"
        QUINZENAL = "QUINZENAL", "A cada duas semanas"

    titulo = models.CharField(
        "O que é", max_length=120,
        help_text="Como aparece na agenda. Por exemplo: Supervisão do Arthur, Atendimento ONG, Reunião de equipe.")
    frequencia = models.CharField("Com que frequência", max_length=10, choices=Frequencia.choices,
                                  default=Frequencia.SEMANAL)
    # Nulo no compromisso de uma vez só: nele quem manda é a data, e o dia da semana sai dela.
    dia_semana = models.PositiveSmallIntegerField(
        "Dia da semana", choices=Recorrencia.DiaSemana.choices, null=True, blank=True)
    hora = models.TimeField("Horário")
    duracao = models.PositiveSmallIntegerField(
        "Duração (minutos)", default=50, validators=[MinValueValidator(10), MaxValueValidator(480)])
    inicio = models.DateField("A partir de", help_text="No compromisso de uma vez só, é o dia dele.")
    fim = models.DateField(
        "Até", null=True, blank=True,
        help_text="Nada é previsto nesta data nem depois. Vazio enquanto o compromisso valer.")

    class Meta:
        verbose_name = "Compromisso"
        verbose_name_plural = "Compromissos"
        ordering = ["dia_semana", "hora", "titulo"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fim__isnull=True) | models.Q(fim__gte=models.F("inicio")),
                name="compromisso_fim_nao_antes_do_inicio",
            ),
            # O dia da semana é obrigatório no que se repete e proibido no de uma vez só: sem isto, um
            # compromisso semanal sem dia nenhum ficaria invisível para sempre, sem erro em lugar nenhum.
            models.CheckConstraint(
                condition=(models.Q(frequencia="UNICO", dia_semana__isnull=True)
                           | (~models.Q(frequencia="UNICO") & models.Q(dia_semana__isnull=False))),
                name="compromisso_dia_semana_combina_com_a_frequencia",
            ),
        ]

    def __str__(self) -> str:
        return self.titulo

    @property
    def rotulo(self) -> str:
        """O que a grade da semana escreve no trecho ocupado. `Recorrencia` tem o mesmo, com o paciente."""
        return self.titulo

    @property
    def unico(self) -> bool:
        return self.frequencia == self.Frequencia.UNICO

    @property
    def _passo(self) -> int:
        return 14 if self.frequencia == self.Frequencia.QUINZENAL else 7

    def clean(self):
        super().clean()
        if self.unico:
            self.dia_semana = None
        elif self.dia_semana is None:
            raise ValidationError("Compromisso que se repete precisa do dia da semana.")

    def ocorre_em(self, dia: date) -> bool:
        if self.unico:
            return dia == self.inicio
        if dia < self.inicio or (self.fim is not None and dia >= self.fim):
            return False
        return dia in self.ocorrencias(dia, dia)

    def ocorrencias(self, de: date, ate: date) -> list[date]:
        """Datas em que este compromisso acontece no intervalo fechado `[de, ate]`."""
        if self.unico:
            return [self.inicio] if de <= self.inicio <= ate else []
        return serie_semanal(self.dia_semana, self._passo, self.inicio, self.fim, de, ate)

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
