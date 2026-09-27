"""Estatísticas da clínica (ADR-084, ADR-103): cada número ao lado do assunto de que ele fala.

A aba própria deixou de existir (ADR-103). O que era um painel de estatísticas virou **quatro blocos**, cada um na
tela a que pertence — e por isso este módulo expõe um por um, em vez de um `montar()` que calcula tudo: quem abre a
agenda não deve pagar pelo cálculo da presença por paciente.

| Bloco | Onde aparece | O que responde |
|---|---|---|
| `retrato_da_clinica` | painel | como a clínica funcionou no período — presença e atendimentos em curso |
| `retrato_da_agenda` | agenda | horário mais usado, dia mais cheio, e a frequência dos atendimentos |
| `presenca_dos_pacientes` | pacientes | quem vem e quem falta, paciente a paciente |
| `resultado_previsto` | financeiro | receitas, despesas e resultado, mês a mês no ano |

Tudo é derivado e **só de dado administrativo** — horário, situação da sessão, frequência, valor. Nunca conteúdo de
prontuário (I-10), e nenhum nome de paciente vai para o JavaScript dos gráficos.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

from atendimentos.models import Consulta
from financeiro.despesas import Fluxo, fluxo_do_ano
from indicadores.periodo import Periodo
from pacientes.models import Caso
from pacientes.servicos import pacientes_ativos

_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
E = Consulta.Estado


@dataclass
class Presenca:
    """Quantas sessões aconteceram, de quantas dependiam do paciente.

    **Conta para a presença:** presente, faltou sem avisar e cliente cancelou — as três em que a sessão dependia do
    paciente. **Não conta:** o que o profissional cancelou e o que foi remarcado, que não dizem nada sobre a
    frequência dele (a remarcada vira outra sessão, que aí sim conta).
    """

    presentes: int = 0
    faltas: int = 0
    canceladas_pelo_cliente: int = 0
    canceladas_pelo_profissional: int = 0
    remarcadas: int = 0

    @property
    def esperadas(self) -> int:
        return self.presentes + self.faltas + self.canceladas_pelo_cliente

    @property
    def ausencias(self) -> int:
        return self.faltas + self.canceladas_pelo_cliente

    @property
    def canceladas(self) -> int:
        return self.canceladas_pelo_cliente + self.canceladas_pelo_profissional

    @property
    def total(self) -> int:
        return self.esperadas + self.canceladas_pelo_profissional + self.remarcadas

    @property
    def percentual(self) -> int | None:
        return round(100 * self.presentes / self.esperadas) if self.esperadas else None

    def somar(self, estado: str) -> None:
        campo = {E.REALIZADA: "presentes", E.FALTOU: "faltas", E.CANCELADA_CLIENTE: "canceladas_pelo_cliente",
                 E.CANCELADA_PROFISSIONAL: "canceladas_pelo_profissional", E.REMARCADA: "remarcadas"}[estado]
        setattr(self, campo, getattr(self, campo) + 1)


def presenca_de(consultas) -> Presenca:
    presenca = Presenca()
    for estado in consultas.values_list("estado", flat=True):
        presenca.somar(estado)
    return presenca


def presenca_do_paciente(paciente) -> Presenca:
    """A frequência de um paciente, em todas as sessões dele — individuais e de casal ou família."""
    return presenca_de(Consulta.objects.filter(caso__participacoes__paciente=paciente))


@dataclass
class Composicao:
    semanais: int = 0
    quinzenais: int = 0
    avulsos: int = 0

    @property
    def total(self) -> int:
        return self.semanais + self.quinzenais + self.avulsos


@dataclass
class RetratoDaClinica:
    """Painel: como a clínica funcionou no período (ADR-103)."""

    periodo: Periodo
    presenca: Presenca
    composicao: Composicao


@dataclass
class RetratoDaAgenda:
    """Agenda: quando a clínica acontece, e com que frequência (ADR-103)."""

    periodo: Periodo
    horarios: list  # (rótulo, sessões), só das horas que tiveram sessão
    dias: list  # (dia da semana, sessões)
    composicao: Composicao

    @property
    def horario_mais_usado(self):
        return max(self.horarios, key=lambda par: par[1], default=None)

    @property
    def dia_mais_cheio(self):
        cheio = max(self.dias, key=lambda par: par[1], default=None)
        return cheio if cheio and cheio[1] else None

    @property
    def tem_sessoes(self) -> bool:
        return any(n for _, n in self.horarios)


@dataclass
class PresencaDosPacientes:
    """Pacientes: quem vem e quem falta (ADR-103)."""

    periodo: Periodo
    presenca: Presenca  # o total do período, que é o gráfico
    por_paciente: list  # (caso, Presenca), da menor presença para a maior


@dataclass
class ResultadoPrevisto:
    """Financeiro: o ano em receitas e despesas, com o mês em foco quando o período é um mês (ADR-103)."""

    periodo: Periodo
    fluxos: list[Fluxo]

    @property
    def _do_periodo(self) -> list[Fluxo]:
        """No mês, só ele; no ano, os doze. Os cards falam do período escolhido; o gráfico, sempre do ano."""
        return [self.fluxos[self.periodo.mes - 1]] if self.periodo.por_mes else self.fluxos

    @property
    def receitas(self) -> Decimal:
        return sum((f.total_receitas for f in self._do_periodo), Decimal("0"))

    @property
    def despesas(self) -> Decimal:
        return sum((f.total_despesas for f in self._do_periodo), Decimal("0"))

    @property
    def resultado(self) -> Decimal:
        return self.receitas - self.despesas


def _composicao() -> Composicao:
    """Os atendimentos **em curso** hoje, pela frequência combinada. Sem regra aberta, é avulso (ADR-053)."""
    composicao = Composicao()
    for caso in Caso.objects.prefetch_related("recorrencias", "desfechos"):
        if caso.desfecho_aberto() is not None:
            continue
        regra = caso.regra_aberta()
        if regra is None:
            composicao.avulsos += 1
        elif regra.frequencia == regra.Frequencia.QUINZENAL:
            composicao.quinzenais += 1
        else:
            composicao.semanais += 1
    return composicao


def _consultas(periodo: Periodo):
    return Consulta.objects.filter(inicio__gte=periodo.inicio, inicio__lt=periodo.fim)


def retrato_da_clinica(periodo: Periodo) -> RetratoDaClinica:
    """Painel (ADR-103): a presença do período e os atendimentos em curso hoje."""
    return RetratoDaClinica(periodo=periodo, presenca=presenca_de(_consultas(periodo)), composicao=_composicao())


def retrato_da_agenda(periodo: Periodo) -> RetratoDaAgenda:
    """Agenda (ADR-103): em que horas e em que dias as sessões aconteceram, e a frequência combinada."""
    horas, dias = Counter(), Counter()
    for momento in _consultas(periodo).filter(estado=E.REALIZADA).values_list("inicio", flat=True):
        local = timezone.localtime(momento)
        horas[local.hour] += 1
        dias[local.weekday()] += 1
    return RetratoDaAgenda(
        periodo=periodo,
        horarios=[(f"{hora:02d}h", horas[hora]) for hora in sorted(horas)],
        # Sábado e domingo só aparecem quando houve sessão: a coluna vazia do fim de semana não diz nada.
        dias=[(_DIAS[dia], dias[dia]) for dia in range(7) if dia < 5 or dias[dia]],
        composicao=_composicao(),
    )


def presenca_dos_pacientes(periodo: Periodo) -> PresencaDosPacientes:
    """Pacientes (ADR-103): a presença de cada um, da menor para a maior."""
    consultas = _consultas(periodo)
    por_caso: dict = {}
    for consulta in consultas.select_related("caso").prefetch_related("caso__pacientes"):
        por_caso.setdefault(consulta.caso, Presenca()).somar(consulta.estado)
    # No mês, quem está em atendimento e não teve sessão também aparece — "sem sessão no mês" é informação real da
    # clínica, não linha vazia. No ano, entra só quem teve sessão: o ano de quem começou em dezembro não é zero.
    if periodo.por_mes:
        for caso in Caso.objects.prefetch_related("pacientes", "desfechos"):
            if caso.desfecho_aberto() is None:
                por_caso.setdefault(caso, Presenca())
    por_paciente = sorted(
        ((caso, p) for caso, p in por_caso.items() if p.esperadas or (periodo.por_mes and not p.total)),
        key=lambda par: (par[1].percentual is None, par[1].percentual or 0, -par[1].esperadas, str(par[0])))
    return PresencaDosPacientes(periodo=periodo, presenca=presenca_de(consultas), por_paciente=por_paciente)


def resultado_previsto(periodo: Periodo, agora: datetime | None = None) -> ResultadoPrevisto:
    """Financeiro (ADR-103): o ano em receitas e despesas. O gráfico é sempre do ano; os cards, do período."""
    return ResultadoPrevisto(periodo=periodo, fluxos=fluxo_do_ano(periodo.ano, agora or timezone.now()))


def aniversariantes_do_mes(hoje: date | None = None) -> list:
    """Pacientes **em atendimento** que fazem aniversário neste mês, por dia. Para o painel (ADR-084)."""
    hoje = hoje or timezone.localdate()
    pacientes = pacientes_ativos().filter(data_nascimento__month=hoje.month)
    return sorted(
        ({"paciente": p, "dia": p.data_nascimento.day, "idade": hoje.year - p.data_nascimento.year,
          "hoje": p.data_nascimento.day == hoje.day, "passou": p.data_nascimento.day < hoje.day}
         for p in pacientes),
        key=lambda item: (item["dia"], item["paciente"].nome))

