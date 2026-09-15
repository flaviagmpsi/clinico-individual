"""A agenda: prever sessões pela frequência e cadastrar o que aconteceu (ADR-060).

`agenda` guarda a regra e não conhece consulta; `atendimentos` guarda a consulta e é quem sabe cruzar uma com a
outra (regra 5 de dependência). Tudo aqui roda no escopo do psicólogo corrente.

- **Previsão é cálculo, não registro.** `sessoes_previstas` deriva as sessões da regra de frequência a cada
  chamada; nada é gravado até o psicólogo cadastrar.
- **Só o psicólogo cadastra** (ADR-052, ADR-060): realizada, falta cobrada ou falta remarcada. Sessão prevista
  que passou sem cadastro é **pendente**.
- **Só se cadastra o que já aconteceu.** Data e hora no futuro são recusadas.
- **Colisão bloqueia** (ADR-024) entre consultas que ocupam o horário e entre regras de frequência. Sessão
  prevista não bloqueia cadastro: previsão não é registro.

E o fim do atendimento: o **desfecho** encerra a frequência, e **retomar** reabre (ADR-049, ADR-055).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from agenda.models import Recorrencia
from atendimentos.models import Consulta, Desfecho
from core import contexto
from pacientes.models import Caso

HORIZONTE_DE_CONFLITO_SEMANAS = 52
AVULSO = "AVULSO"  # não é valor de `Recorrencia`: é a ausência de regra (ADR-053)

# Primeira data que a busca de pendências considera. Qualquer regra começa depois dela; `Recorrencia.ocorrencias`
# parte da primeira sessão da regra, então a data antiga não custa iteração.
_DESDE_SEMPRE = date(2000, 1, 1)


def momento(dia: date, hora: time) -> datetime:
    return timezone.make_aware(datetime.combine(dia, hora))


def _psicologo():
    from contas.models import Psicologo

    return Psicologo.objects.get(pk=contexto.exigir())


def _sobrepoe(inicio_a: datetime, duracao_a: int, inicio_b: datetime, duracao_b: int) -> bool:
    return (inicio_a < inicio_b + timedelta(minutes=duracao_b)
            and inicio_b < inicio_a + timedelta(minutes=duracao_a))


# --- Previsão --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SessaoPrevista:
    """Uma sessão que a frequência prevê e que ainda não foi cadastrada. Não existe no banco."""

    regra: Recorrencia
    data: date

    @property
    def caso(self) -> Caso:
        return self.regra.caso

    @property
    def inicio(self) -> datetime:
        return momento(self.data, self.regra.hora)

    @property
    def duracao(self) -> int:
        return self.regra.duracao

    @property
    def fim(self) -> datetime:
        return self.inicio + timedelta(minutes=self.duracao)

    @property
    def data_iso(self) -> str:
        return self.data.isoformat()

    def pendente(self, agora: datetime | None = None) -> bool:
        """Já começou e ninguém cadastrou (ADR-052)."""
        return self.inicio <= (agora or timezone.now())


def sessoes_previstas(de: date, ate: date, *, caso: Caso | None = None) -> list[SessaoPrevista]:
    """As sessões que a frequência prevê entre `de` e `ate`, inclusive, e que ninguém cadastrou."""
    regras = Recorrencia.objects.filter(inicio__lte=ate).filter(Q(fim__isnull=True) | Q(fim__gt=de))
    if caso is not None:
        regras = regras.filter(caso=caso)
    regras = list(regras.select_related("caso").prefetch_related("caso__pacientes"))
    cadastradas = set(
        Consulta.objects.filter(recorrencia__in=regras, data_prevista__gte=de, data_prevista__lte=ate)
        .values_list("recorrencia_id", "data_prevista")
    )
    previstas = [
        SessaoPrevista(regra, dia)
        for regra in regras
        for dia in regra.ocorrencias(de, ate)
        if (regra.pk, dia) not in cadastradas
    ]
    return sorted(previstas, key=lambda sessao: sessao.inicio)


def sessoes_pendentes(agora: datetime | None = None, *, caso: Caso | None = None) -> list[SessaoPrevista]:
    """Sessões previstas que já começaram e não foram cadastradas — pendência, nunca cadastro automático."""
    agora = agora or timezone.now()
    previstas = sessoes_previstas(_DESDE_SEMPRE, timezone.localdate(agora), caso=caso)
    return [sessao for sessao in previstas if sessao.pendente(agora)]


# --- Frequência ------------------------------------------------------------------------------------------------

def _conflito_da_regra(nova: Recorrencia) -> str | None:
    """Confere a regra nova contra as outras regras em vigor. Consulta cadastrada é passado e não conflita."""
    datas = nova.ocorrencias(nova.inicio, nova.inicio + timedelta(weeks=HORIZONTE_DE_CONFLITO_SEMANAS))
    outras = (
        Recorrencia.objects.exclude(pk=nova.pk)
        .filter(dia_semana=nova.dia_semana)
        .filter(Q(fim__isnull=True) | Q(fim__gt=nova.inicio))
        .select_related("caso")
    )
    for outra in outras:
        for dia in datas:
            if outra.ocorre_em(dia) and _sobrepoe(
                momento(dia, nova.hora), nova.duracao, momento(dia, outra.hora), outra.duracao
            ):
                return (f"Horário ocupado: {outra.caso} tem sessão {outra.get_frequencia_display().lower()} "
                        f"às {outra.hora:%H:%M} — a primeira coincidência seria em {dia:%d/%m/%Y}.")
    return None


def _encerrar(regra: Recorrencia, a_partir_de: date) -> None:
    """Fecha a regra numa data. Previsão não é registro: nada além da regra muda, e o que foi cadastrado fica."""
    if regra.inicio >= a_partir_de and not regra.consultas.exists():
        regra.delete()  # nunca chegou a valer e não deixou rastro
        return
    regra.fim = max(a_partir_de, regra.inicio)
    regra.save()


def _recusar_encerrado(caso: Caso) -> None:
    desfecho = caso.desfecho_aberto()
    if desfecho is not None:
        raise ValidationError(
            f"Este atendimento está encerrado ({desfecho.get_tipo_display().lower()} em {desfecho.data:%d/%m/%Y}). "
            "Retome-o antes de definir a frequência.")


@transaction.atomic
def definir_frequencia(
    caso: Caso,
    *,
    frequencia: str,
    dia_semana: int | None = None,
    hora: time | None = None,
    duracao: int | None = None,
    a_partir_de: date | None = None,
    hoje: date | None = None,
) -> Recorrencia | None:
    """Semanal, quinzenal ou avulso (ADR-053). Vale "desta data em diante" (ADR-022).

    Avulso não cria regra: encerra a vigente e deixa de prever sessões. Se a regra nova colidir com outra, nada é
    gravado — nem o encerramento da anterior.
    """
    _recusar_encerrado(caso)
    hoje = hoje or timezone.localdate()
    a_partir_de = a_partir_de or hoje
    if a_partir_de < hoje:
        raise ValidationError("A mudança vale de hoje em diante — o passado não é reescrito (ADR-022).")

    atual = caso.regra_aberta()
    if atual is not None:
        _encerrar(atual, a_partir_de)
    if frequencia == AVULSO:
        return None
    if dia_semana is None or hora is None:
        raise ValidationError("Semanal e quinzenal precisam de dia da semana e horário.")

    nova = Recorrencia.objects.create(
        caso=caso, frequencia=frequencia, dia_semana=dia_semana, hora=hora,
        duracao=duracao or _psicologo().duracao_sessao, inicio=a_partir_de,
    )
    conflito = _conflito_da_regra(nova)
    if conflito:
        raise ValidationError(conflito)
    return nova


# --- Cadastro --------------------------------------------------------------------------------------------------

def _cadastrar(consulta: Consulta, agora: datetime | None) -> Consulta:
    if consulta.estado not in Consulta.Estado.values:
        raise ValidationError("Escolha o que aconteceu: realizada, falta cobrada ou falta remarcada.")
    if consulta.inicio > (agora or timezone.now()):
        raise ValidationError("Só se cadastra o que já aconteceu — esta sessão ainda não começou.")
    consulta.save()
    return consulta


@transaction.atomic
def cadastrar_prevista(
    regra: Recorrencia,
    data: date,
    *,
    estado: str,
    hora: time | None = None,
    duracao: int | None = None,
    agora: datetime | None = None,
) -> Consulta:
    """Cadastra uma sessão da frequência — é o que a tira da pendência.

    Continua possível depois do desfecho: a pendência de antes do encerramento não some com ele (ADR-055).
    """
    if not regra.ocorre_em(data):
        raise ValidationError("Esta data não é uma sessão prevista pela frequência.")
    if regra.consultas.filter(data_prevista=data).exists():
        raise ValidationError("Esta sessão já foi cadastrada.")
    consulta = Consulta(caso=regra.caso, recorrencia=regra, data_prevista=data, estado=estado,
                        inicio=momento(data, hora or regra.hora), duracao=duracao or regra.duracao)
    return _cadastrar(consulta, agora)


@transaction.atomic
def cadastrar_avulsa(
    caso: Caso,
    *,
    estado: str,
    inicio: datetime,
    duracao: int | None = None,
    agora: datetime | None = None,
) -> Consulta:
    """Consulta fora da frequência: do paciente avulso, uma sessão extra, ou a remarcada que aconteceu."""
    desfecho = caso.desfecho_aberto()
    if desfecho is not None and timezone.localtime(inicio).date() > desfecho.data:
        raise ValidationError(
            f"Este atendimento está encerrado desde {desfecho.data:%d/%m/%Y}. "
            "Retome-o antes de cadastrar sessões depois dessa data.")
    consulta = Consulta(caso=caso, estado=estado, inicio=inicio, duracao=duracao or _psicologo().duracao_sessao)
    return _cadastrar(consulta, agora)


@transaction.atomic
def alterar_situacao(consulta: Consulta, estado: str) -> Consulta:
    """Corrige o que foi cadastrado. A data não muda: para isso, exclui-se o cadastro e cadastra-se de novo."""
    if estado not in Consulta.Estado.values:
        raise ValidationError("Escolha o que aconteceu: realizada, falta cobrada ou falta remarcada.")
    consulta.estado = estado
    consulta.save()
    return consulta


@transaction.atomic
def excluir_consulta(consulta: Consulta) -> None:
    """Cadastro feito por engano. Se era da frequência, a sessão volta a ser pendente."""
    consulta.delete()


# --- Fim do atendimento ----------------------------------------------------------------------------------------

@transaction.atomic
def registrar_desfecho(
    caso: Caso,
    *,
    tipo: str,
    iniciativa: str = "",
    motivo: str = "",
    data: date | None = None,
    agora: datetime | None = None,
) -> Desfecho:
    """Encerra o atendimento (ADR-049, ADR-055).

    A frequência termina hoje e nenhuma sessão nova é prevista. **O passado fica**: o que foi cadastrado e o que
    ficou pendente — o desfecho não cadastra nada no lugar do psicólogo (ADR-052).

    Na desistência e na interrupção a iniciativa decorre do tipo; em alta e encaminhamento, é informada.
    """
    agora = agora or timezone.now()
    hoje = timezone.localdate(agora)
    data = data or hoje
    if data > hoje:
        raise ValidationError("O desfecho se registra quando acontece — a data não pode estar no futuro.")
    if caso.desfecho_aberto() is not None:
        raise ValidationError("Este atendimento já está encerrado.")

    desfecho = Desfecho.objects.create(
        caso=caso, tipo=tipo, iniciativa=iniciativa or Desfecho.INICIATIVA_DO_TIPO.get(tipo, ""),
        motivo=motivo, data=data)

    for regra in caso.recorrencias.filter(Q(fim__isnull=True) | Q(fim__gt=hoje)):
        if regra.inicio > hoje and not regra.consultas.exists():
            regra.delete()  # nunca chegou a valer
        else:
            regra.fim = max(hoje, regra.inicio)
            regra.save()
    return desfecho


@transaction.atomic
def retomar(caso: Caso, *, hoje: date | None = None) -> Desfecho:
    """O paciente voltou: reabre **o mesmo** atendimento (ADR-055). A frequência nova é definida em seguida."""
    hoje = hoje or timezone.localdate()
    desfecho = caso.desfecho_aberto()
    if desfecho is None:
        raise ValidationError("Este atendimento não está encerrado.")
    desfecho.retomado_em = max(hoje, desfecho.data)
    desfecho.save(update_fields=["retomado_em"])
    return desfecho
