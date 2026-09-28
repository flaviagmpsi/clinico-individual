"""A ficha resumida de cada paciente, para a lista em blocos (ADR-109).

Mora em `indicadores` porque junta coisas de três apps — `pacientes`, `agenda` e `financeiro` — e `indicadores` é
o único que pode depender de todos. Em `pacientes` ela criaria uma dependência ao contrário.

**Tudo em lote, nunca paciente a paciente.** A tela mostra dezenas de blocos; uma consulta por bloco seriam
dezenas de idas ao banco, e o Neon é remoto — o custo é de rede, não de CPU. Então: uma consulta para as
recorrências, uma carga só para as pendências (`financeiro.servicos.pagamentos_pendentes`, que já lê tudo de uma
vez), e o resto sai do que a lista já trouxe.
"""

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal

from django.utils import timezone

from agenda.models import Recorrencia
from financeiro import servicos as financeiro
from pacientes.models import Caso, Paciente

# A frequência vira cor no bloco. São três, e o rótulo vai escrito ao lado: quem não distingue cor lê "semanal".
SEMANAL = "semanal"
QUINZENAL = "quinzenal"
AVULSO = "avulso"


@dataclass(frozen=True)
class Ficha:
    """O que um bloco de paciente mostra. Nada aqui é gravado — é tudo derivado, como o resto do sistema."""

    paciente: Paciente
    frequencia: str
    dia_semana: int | None
    hora: time | None
    em_aberto: Decimal
    presenca: object | None

    @property
    def quando(self) -> str:
        """"Segunda, 08:00 · semanal", ou o que der para dizer quando não há horário fixo."""
        if self.dia_semana is None or self.hora is None:
            return "sem horário fixo · avulso"
        dia = Recorrencia.DiaSemana(self.dia_semana).label.replace("-feira", "")
        return f"{dia}, {self.hora:%H:%M} · {self.frequencia}"

    @property
    def em_dia(self) -> bool:
        return not self.em_aberto


def _recorrencia_vigente(recorrencias, hoje: date) -> Recorrencia | None:
    """A regra que vale hoje. `ordering` já traz da mais nova para a mais velha, então a primeira que serve vence."""
    for regra in recorrencias:
        if regra.inicio <= hoje and (regra.fim is None or regra.fim > hoje):
            return regra
    return None


def fichas(pacientes, presenca_por_paciente=None, hoje: date | None = None) -> list[Ficha]:
    """Uma ficha por paciente, na ordem em que os pacientes vieram."""
    hoje = hoje or timezone.localdate()
    pacientes = list(pacientes)
    if not pacientes:
        return []

    # --- de quem é cada caso: uma consulta para todos ------------------------------------------------------------
    casos = (Caso.objects.filter(participacoes__paciente__in=pacientes)
             .prefetch_related("participacoes", "recorrencias").distinct())
    caso_do_paciente: dict[int, Caso] = {}
    for caso in casos:
        for participacao in caso.participacoes.all():
            caso_do_paciente.setdefault(participacao.paciente_id, caso)

    # --- o que cada um deve: uma carga só, e não uma por paciente ------------------------------------------------
    aberto_por_caso: dict[int, Decimal] = {}
    for cobranca in financeiro.pagamentos_pendentes(hoje):
        aberto_por_caso[cobranca.caso.pk] = aberto_por_caso.get(cobranca.caso.pk, Decimal("0")) + cobranca.saldo

    presenca_por_caso = {caso.pk: p for caso, p in (presenca_por_paciente or [])}

    resultado = []
    for paciente in pacientes:
        caso = caso_do_paciente.get(paciente.pk)
        regra = _recorrencia_vigente(caso.recorrencias.all(), hoje) if caso else None
        resultado.append(Ficha(
            paciente=paciente,
            frequencia=regra.get_frequencia_display().lower() if regra else AVULSO,
            dia_semana=regra.dia_semana if regra else None,
            hora=regra.hora if regra else None,
            em_aberto=aberto_por_caso.get(caso.pk, Decimal("0")) if caso else Decimal("0"),
            presenca=presenca_por_caso.get(caso.pk) if caso else None,
        ))
    return resultado
