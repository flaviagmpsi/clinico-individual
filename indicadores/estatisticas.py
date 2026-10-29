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
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from agenda import compromissos
from agenda.models import Recorrencia
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
        # A agendada (ADR-139) ainda não aconteceu: não entra em presença nenhuma. `get` a ignora sem erro.
        campo = {E.REALIZADA: "presentes", E.FALTOU: "faltas", E.CANCELADA_CLIENTE: "canceladas_pelo_cliente",
                 E.CANCELADA_PROFISSIONAL: "canceladas_pelo_profissional", E.REMARCADA: "remarcadas"}.get(estado)
        if campo:
            setattr(self, campo, getattr(self, campo) + 1)


def presenca_de(consultas) -> Presenca:
    presenca = Presenca()
    for estado in consultas.values_list("estado", flat=True):
        presenca.somar(estado)
    return presenca


def presenca_do_paciente(paciente) -> Presenca:
    """A frequência de um paciente, em todas as sessões dele — individuais e de casal ou família."""
    return presenca_de(Consulta.objects.filter(caso__participacoes__paciente=paciente))


def presenca_total_por_caso(caso_ids) -> dict:
    """A frequência **de todo o histórico**, caso a caso, em uma consulta só (nota: consultas em lote).

    Para a barrinha de cada bloco da lista de pacientes: ela mostra o quanto o paciente vem de verdade, e não só
    no mês selecionado — "3 de 4 neste mês" engana num paciente que some há meses. Agrupa por caso e situação no
    banco; o seletor de período ao lado continua sendo quem responde "como foi este mês".
    """
    from django.db.models import Count

    caso_ids = list(caso_ids)
    presencas: dict = {cid: Presenca() for cid in caso_ids}
    if not caso_ids:
        return presencas
    linhas = (Consulta.objects.filter(caso_id__in=caso_ids)
              .values("caso_id", "estado").annotate(n=Count("id")))
    for linha in linhas:
        presenca = presencas[linha["caso_id"]]
        for _ in range(linha["n"]):
            presenca.somar(linha["estado"])
    return presencas


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
    pacientes_ativos: int

    @property
    def tem_atendimento_coletivo(self) -> bool:
        """Casal e família fazem um atendimento valer por duas pessoas — aí os dois números divergem."""
        return self.pacientes_ativos != self.composicao.total



def _horas(minutos: int) -> str:
    """"6h30", "2h". Mesma escrita da grade da semana, para os dois números se lerem juntos."""
    horas, resto = divmod(round(minutos), 60)
    return f"{horas}h{resto:02d}" if resto else f"{horas}h"

@dataclass
class RetratoDaAgenda:
    """Agenda: quando a clínica acontece, e com que frequência (ADR-103)."""

    periodo: Periodo
    horarios: list  # (rótulo, sessões realizadas), só das horas que tiveram sessão — alimenta o gráfico
    dias: list  # (dia da semana, sessões realizadas) — alimenta o gráfico
    composicao: Composicao
    # "Dia que mais atende" e "Horário mais usado" vêm dos pacientes **cadastrados** (a frequência fixa de cada um),
    # não só das sessões já realizadas: mostram o padrão real da semana, mesmo num mês com poucas sessões marcadas.
    horarios_agendados: list = field(default_factory=list)  # (rótulo, nº de pacientes com sessão fixa nessa hora)
    dias_agendados: list = field(default_factory=list)       # (dia da semana, nº de pacientes)
    # ADR-122: minutos de trabalho no período, somando sessão realizada e compromisso fora da clínica. Separados
    # para a tela poder dizer de onde vem cada parte — "22h, sendo 6h fora da clínica" explica; "28h" esconde.
    minutos_de_sessao: int = 0
    minutos_fora_da_clinica: int = 0

    @property
    def minutos_trabalhados(self) -> int:
        return self.minutos_de_sessao + self.minutos_fora_da_clinica

    @property
    def horas_trabalhadas(self) -> str:
        return _horas(self.minutos_trabalhados)

    @property
    def horas_fora_da_clinica(self) -> str:
        return _horas(self.minutos_fora_da_clinica)

    @property
    def tem_trabalho_fora(self) -> bool:
        return bool(self.minutos_fora_da_clinica)

    @property
    def horario_mais_usado(self):
        usado = max(self.horarios_agendados, key=lambda par: par[1], default=None)
        return usado if usado and usado[1] else None

    @property
    def dia_mais_cheio(self):
        cheio = max(self.dias_agendados, key=lambda par: par[1], default=None)
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
    return RetratoDaClinica(periodo=periodo, presenca=presenca_de(_consultas(periodo)), composicao=_composicao(),
                            pacientes_ativos=pacientes_ativos().count())


def _faixa_de_horas(horas) -> list:
    """As horas entre a primeira e a última com sessão, **sem buracos** (ADR-128).

    Antes devolvia só as horas que tiveram sessão, e o gráfico desenhava "11h" colado em "18h" como se fossem
    vizinhos — a forma dizia "a tarde é cheia" quando a tarde estava vazia. Preenchido com zero, o vão entre os
    blocos de atendimento vira o que ele é.
    """
    if not horas:
        return []
    return [(f"{hora:02d}h", horas.get(hora, 0)) for hora in range(min(horas), max(horas) + 1)]


def retrato_da_agenda(periodo: Periodo) -> RetratoDaAgenda:
    """Agenda (ADR-103): em que horas e em que dias as sessões aconteceram, e a frequência combinada."""
    horas, dias = Counter(), Counter()
    minutos_de_sessao = 0
    for momento, duracao in _consultas(periodo).filter(estado=E.REALIZADA).values_list("inicio", "duracao"):
        local = timezone.localtime(momento)
        horas[local.hour] += 1
        dias[local.weekday()] += 1
        minutos_de_sessao += duracao
    # ADR-122: o que o psicólogo faz e não é paciente particular conta nas horas, e em nenhuma outra conta.
    # ADR-128: **até hoje, nunca além**. Este cartão responde "como a sua agenda funcionou", no passado, e a
    # sessão só entra quando registrada como realizada. Contar o compromisso do período inteiro punha futuro no
    # mesmo número que passado — numa conta real, 23 dos 35 compromissos de outubro ainda não tinham acontecido,
    # e o mês marcava 32h40 de trabalho no dia 14.
    ate = min(periodo.ultimo_dia, timezone.localdate())
    fora = compromissos.do_periodo(periodo.primeiro_dia, ate) if ate >= periodo.primeiro_dia else []
    # "Dia que mais atende" e "Horário mais usado": pelos pacientes cadastrados (a regra fixa de cada um), não só
    # pelas sessões realizadas. Cada atendimento de paciente em vigor conta uma vez no seu dia e na sua hora. Só as
    # regras **em vigor no período** — um mês ou ano passado não deve mostrar o padrão de hoje.
    por_hora, por_dia = Counter(), Counter()
    ativas = (Recorrencia.objects.filter(inicio__lte=periodo.ultimo_dia)
              .filter(Q(fim__isnull=True) | Q(fim__gt=periodo.primeiro_dia)))
    for hora, dia_semana in ativas.values_list("hora", "dia_semana"):
        por_hora[hora.hour] += 1
        por_dia[dia_semana] += 1
    return RetratoDaAgenda(
        periodo=periodo,
        horarios=_faixa_de_horas(horas),
        # Sábado e domingo só aparecem quando houve sessão: a coluna vazia do fim de semana não diz nada.
        dias=[(_DIAS[dia], dias[dia]) for dia in range(7) if dia < 5 or dias[dia]],
        horarios_agendados=[(f"{h:02d}h", por_hora[h]) for h in sorted(por_hora)],
        dias_agendados=[(_DIAS[d], por_dia[d]) for d in range(7) if por_dia[d]],
        composicao=_composicao(),
        minutos_de_sessao=minutos_de_sessao,
        minutos_fora_da_clinica=sum(item.duracao for item in fora),
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


def aniversariantes_de_hoje(hoje: date | None = None) -> list:
    """Pacientes **em atendimento** que fazem aniversário **hoje**. Para o pop-up do painel (ADR-134).

    A lembrança saiu do card fixo do mês e virou um aviso do dia: quem faz aniversário hoje aparece quando o
    psicólogo abre o sistema, uma vez por dia (o "fechar" é guardado no navegador, não aqui)."""
    hoje = hoje or timezone.localdate()
    pacientes = pacientes_ativos().filter(data_nascimento__month=hoje.month, data_nascimento__day=hoje.day)
    return sorted(
        ({"paciente": p, "idade": hoje.year - p.data_nascimento.year} for p in pacientes),
        key=lambda item: item["paciente"].nome)

