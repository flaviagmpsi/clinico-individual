"""Os compromissos fora da clínica, no formato que o calendário desenha (ADR-122).

Mora em `agenda` porque o compromisso é só tempo ocupado: não conhece paciente, caso nem consulta. Quem o
desenha é `atendimentos.servicos.calendario`, que já conhece `agenda` — a seta de dependência não se inverte.

A ocorrência **não é gravada**, como a sessão prevista: ela é derivada do compromisso e do intervalo pedido.
Guardar uma linha por semana seria inventar estado para repetir o que a regra já diz.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.utils import timezone

from agenda.models import Compromisso


def _momento(dia: date, hora) -> datetime:
    return timezone.make_aware(datetime.combine(dia, hora))


@dataclass(frozen=True)
class CompromissoNoDia:
    """Um compromisso acontecendo num dia. Tem a mesma cara de uma sessão esperada para a tela tratar junto."""

    compromisso: Compromisso
    data: date

    @property
    def titulo(self) -> str:
        return self.compromisso.titulo

    @property
    def inicio(self) -> datetime:
        return _momento(self.data, self.compromisso.hora)

    @property
    def duracao(self) -> int:
        return self.compromisso.duracao

    @property
    def fim(self) -> datetime:
        return self.inicio + timedelta(minutes=self.duracao)

    @property
    def ocupa_horario(self) -> bool:
        """Ocupa, sempre. É a decisão do usuário: o sistema não pode propor marcar alguém por cima."""
        return True


def do_periodo(de: date, ate: date) -> list[CompromissoNoDia]:
    """Todos os compromissos que acontecem entre `de` e `ate`, inclusive, em ordem de horário."""
    candidatos = Compromisso.objects.filter(inicio__lte=ate).exclude(fim__lte=de)
    ocorrencias = [CompromissoNoDia(c, dia) for c in candidatos for dia in c.ocorrencias(de, ate)]
    return sorted(ocorrencias, key=lambda item: item.inicio)


def que_ocupam_a_grade() -> list[Compromisso]:
    """Os que repetem e ainda valem — os únicos que tomam um lugar fixo na semana-tipo.

    O compromisso de uma vez só não entra: ele acontece num dia, não toda semana, e tirá-lo da grade faria o
    horário parecer ocupado para sempre por causa de uma reunião.
    """
    return list(Compromisso.objects.filter(fim__isnull=True).exclude(frequencia=Compromisso.Frequencia.UNICO))
