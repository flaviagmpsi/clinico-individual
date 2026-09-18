"""Estatísticas da clínica (ADR-084): o resultado previsto do ano e o retrato dos atendimentos.

Mora numa aba própria, e não no painel: o painel responde "o que eu faço agora" (ADR-027, ADR-072); isto responde
"como a minha clínica funciona". Tudo é derivado e **só de dado administrativo** — horário, situação da sessão,
frequência, valor. Nunca conteúdo de prontuário (I-10).
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from django.utils import timezone

from atendimentos.models import Consulta
from financeiro.despesas import Fluxo, fluxo_do_ano
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
class Estatisticas:
    ano: int
    fluxos: list[Fluxo]
    presenca: Presenca
    por_paciente: list  # (caso, Presenca), da menor presença para a maior
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
    def receitas_do_ano(self) -> Decimal:
        return sum((f.total_receitas for f in self.fluxos), Decimal("0"))

    @property
    def despesas_do_ano(self) -> Decimal:
        return sum((f.total_despesas for f in self.fluxos), Decimal("0"))

    @property
    def resultado_do_ano(self) -> Decimal:
        return self.receitas_do_ano - self.despesas_do_ano


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


def montar(ano: int, agora: datetime | None = None) -> Estatisticas:
    agora = agora or timezone.now()
    inicio = timezone.make_aware(datetime.combine(date(ano, 1, 1), time.min))
    fim = timezone.make_aware(datetime.combine(date(ano + 1, 1, 1), time.min))
    do_ano = Consulta.objects.filter(inicio__gte=inicio, inicio__lt=fim)

    horas, dias = Counter(), Counter()
    for momento in do_ano.filter(estado=E.REALIZADA).values_list("inicio", flat=True):
        local = timezone.localtime(momento)
        horas[local.hour] += 1
        dias[local.weekday()] += 1

    por_caso: dict = {}
    for consulta in do_ano.select_related("caso").prefetch_related("caso__pacientes"):
        por_caso.setdefault(consulta.caso, Presenca()).somar(consulta.estado)
    por_paciente = sorted(((caso, p) for caso, p in por_caso.items() if p.esperadas),
                          key=lambda par: (par[1].percentual, -par[1].esperadas, str(par[0])))

    return Estatisticas(
        ano=ano, fluxos=fluxo_do_ano(ano, agora), presenca=presenca_de(do_ano), por_paciente=por_paciente,
        horarios=[(f"{hora:02d}h", horas[hora]) for hora in sorted(horas)],
        dias=[(_DIAS[dia], dias[dia]) for dia in range(7) if dia < 5 or dias[dia]],
        composicao=_composicao(),
    )


def aniversariantes_do_mes(hoje: date | None = None) -> list:
    """Pacientes **em atendimento** que fazem aniversário neste mês, por dia. Para o painel (ADR-084)."""
    hoje = hoje or timezone.localdate()
    pacientes = pacientes_ativos().filter(data_nascimento__month=hoje.month)
    return sorted(
        ({"paciente": p, "dia": p.data_nascimento.day, "idade": hoje.year - p.data_nascimento.year,
          "hoje": p.data_nascimento.day == hoje.day, "passou": p.data_nascimento.day < hoje.day}
         for p in pacientes),
        key=lambda item: (item["dia"], item["paciente"].nome))

