"""A grade de horários: o que o psicólogo declarou, o que já tem paciente e o que sobrou (ADR-029, ADR-056).

A ocupação é **derivada** das regras de frequência em vigor — nunca mantida à mão. Só olha regra, nunca
consulta: `agenda` não conhece `atendimentos` (regra 5 de dependência), e a pergunta que a grade responde
("tenho vaga para paciente novo?") é sobre o compromisso fixo, não sobre a consulta cadastrada desta semana.

Aritmética em minutos desde a meia-noite, sem `datetime`: a grade é semanal e não tem data.
"""

from dataclasses import dataclass, field
from datetime import time

from agenda.models import HorarioDisponivel, Recorrencia

# Quinzenal ocupa metade: na outra semana o horário está livre (ADR-056). Avulso não tem regra e não ocupa.
PESO = {Recorrencia.Frequencia.SEMANAL: 1.0, Recorrencia.Frequencia.QUINZENAL: 0.5}


def _minutos(hora: time) -> int:
    return hora.hour * 60 + hora.minute


def _hora(minutos: int) -> time:
    return time(minutos // 60, minutos % 60)


def _unir(intervalos: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Junta intervalos sobrepostos **ou encostados** — "8h–12h" e "12h–14h" viram "8h–14h"."""
    unidos: list[list[int]] = []
    for inicio, fim in sorted(intervalos):
        if unidos and inicio <= unidos[-1][1]:
            unidos[-1][1] = max(unidos[-1][1], fim)
        else:
            unidos.append([inicio, fim])
    return [(a, b) for a, b in unidos]


def _faixas_do_dia(blocos, dia_semana: int) -> list[tuple[int, int]]:
    return _unir([(_minutos(b.inicio), _minutos(b.fim)) for b in blocos if b.dia_semana == dia_semana])


def _cabe(faixas, inicio: int, fim: int) -> bool:
    return any(a <= inicio and fim <= b for a, b in faixas)


def fora_da_grade(dia_semana: int, hora: time, duracao: int) -> bool:
    """Se a sessão cai, no todo ou em parte, fora da grade declarada. **Sem grade, nunca** (ADR-056)."""
    blocos = list(HorarioDisponivel.objects.all())
    if not blocos:
        return False
    inicio = _minutos(hora)
    return not _cabe(_faixas_do_dia(blocos, dia_semana), inicio, inicio + duracao)


@dataclass
class Trecho:
    inicio: int
    fim: int
    regras: list = field(default_factory=list)

    @property
    def livre(self) -> bool:
        return not self.regras

    @property
    def hora_inicio(self) -> time:
        return _hora(self.inicio)

    @property
    def hora_fim(self) -> time:
        return _hora(self.fim)


@dataclass
class DiaDaGrade:
    numero: int
    nome: str
    blocos: list = field(default_factory=list)  # [(HorarioDisponivel, [Trecho])]
    fora: list = field(default_factory=list)  # regras que não cabem inteiras na grade


def _horas(minutos: float) -> str:
    minutos = round(minutos)
    horas, resto = divmod(minutos, 60)
    return f"{horas}h{resto:02d}" if resto else f"{horas}h"


@dataclass
class Mapa:
    dias: list
    minutos_disponiveis: int
    minutos_ocupados: float
    tem_grade: bool

    @property
    def ocupacao(self) -> int | None:
        if not self.minutos_disponiveis:
            return None
        return round(100 * self.minutos_ocupados / self.minutos_disponiveis)

    @property
    def horas_disponiveis(self) -> str:
        return _horas(self.minutos_disponiveis)

    @property
    def horas_ocupadas(self) -> str:
        return _horas(self.minutos_ocupados)

    @property
    def horas_livres(self) -> str:
        return _horas(self.minutos_disponiveis - self.minutos_ocupados)


def _trechos(inicio: int, fim: int, regras) -> tuple[list[Trecho], float]:
    """Corta o bloco nos pontos onde começa ou termina uma sessão fixa, e soma a ocupação ponderada."""
    dentro = []
    cortes = {inicio, fim}
    for regra in regras:
        r_inicio = _minutos(regra.hora)
        r_fim = r_inicio + regra.duracao
        if r_inicio < fim and r_fim > inicio:
            cortes.update({max(inicio, r_inicio), min(fim, r_fim)})
            dentro.append((r_inicio, r_fim, regra))

    pontos = sorted(cortes)
    trechos: list[Trecho] = []
    ocupado = 0.0
    for a, b in zip(pontos, pontos[1:]):
        cobrindo = [regra for r_inicio, r_fim, regra in dentro if r_inicio < b and r_fim > a]
        # Duas quinzenais em semanas alternadas somam 1; nada passa de 1 porque a colisão impede.
        ocupado += (b - a) * min(1.0, sum(PESO[regra.frequencia] for regra in cobrindo))
        if trechos and trechos[-1].regras == cobrindo:
            trechos[-1].fim = b
        else:
            trechos.append(Trecho(a, b, cobrindo))
    return trechos, ocupado


def mapa_da_semana() -> Mapa:
    """A semana-tipo: cada bloco declarado cortado em livre e ocupado, e as sessões fixas fora da grade.

    Considera só a regra **aberta** de cada atendimento. Uma regra com fim marcado está saindo — a que
    a substitui é a que ocupa o horário daqui em diante; contar as duas mostraria o mesmo paciente duas vezes.
    """
    blocos = list(HorarioDisponivel.objects.all())
    regras = list(
        Recorrencia.objects.filter(fim__isnull=True).select_related("caso").prefetch_related("caso__pacientes")
    )
    dias = []
    disponivel = 0
    ocupado = 0.0
    for numero, nome in Recorrencia.DiaSemana.choices:
        do_dia = [r for r in regras if r.dia_semana == numero]
        dia = DiaDaGrade(numero, nome)
        for bloco in (b for b in blocos if b.dia_semana == numero):
            inicio, fim = _minutos(bloco.inicio), _minutos(bloco.fim)
            trechos, ocupado_no_bloco = _trechos(inicio, fim, do_dia)
            dia.blocos.append((bloco, trechos))
            disponivel += fim - inicio
            ocupado += ocupado_no_bloco
        faixas = _faixas_do_dia(blocos, numero)
        dia.fora = sorted(
            (r for r in do_dia if not _cabe(faixas, _minutos(r.hora), _minutos(r.hora) + r.duracao)),
            key=lambda r: r.hora,
        )
        if dia.blocos or dia.fora:
            dias.append(dia)
    return Mapa(dias=dias, minutos_disponiveis=disponivel, minutos_ocupados=ocupado, tem_grade=bool(blocos))
