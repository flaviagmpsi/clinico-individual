"""A agenda: transformar regra em consulta, e registrar o que aconteceu.

`agenda` guarda a regra e não conhece consulta; `atendimentos` guarda a consulta e é quem sabe gerar
uma a partir da outra (regra 5 de dependência). Tudo aqui roda no escopo do psicólogo corrente.

Três garantias moram neste módulo, cada uma com sua ADR:

- **Janela de previsão** (ADR-022): as consultas das regras são materializadas até `JANELA_SEMANAS` à
  frente, quando a agenda abre — sem agendador (ADR-018). Datas passadas não são geradas.
- **Colisão bloqueia** (ADR-024): o model confere as consultas já geradas; aqui se conferem também as
  ocorrências que a regra **ainda não gerou**, que o model não enxerga. Sem isso, uma consulta avulsa
  marcada daqui a cinco meses passaria por cima de uma sessão semanal fora da janela.
- **O sistema nunca registra sozinho** (ADR-052): consulta passada sem registro é pendência.

E o fim do atendimento: o **desfecho** fecha a agenda do caso, e **retomar** reabre (ADR-049, ADR-055).
Atendimento encerrado não aceita frequência, consulta nem remarcação.
"""

from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from agenda.models import Recorrencia
from atendimentos.models import Consulta, Desfecho
from core import contexto
from pacientes.models import Caso

JANELA_SEMANAS = 8  # ADR-022: "ordem de grandeza, 8 semanas" (P-46)
HORIZONTE_DE_CONFLITO_SEMANAS = 52
AVULSO = "AVULSO"  # não é valor de `Recorrencia`: é a ausência de regra (ADR-053)

_AGENDADA = Consulta.Estado.AGENDADA
_REALIZADA = Consulta.Estado.REALIZADA
_FALTA = Consulta.Estado.FALTA
_CANCELADA = Consulta.Estado.CANCELADA


def momento(dia: date, hora: time) -> datetime:
    return timezone.make_aware(datetime.combine(dia, hora))


def _psicologo():
    from contas.models import Psicologo

    return Psicologo.objects.get(pk=contexto.exigir())


def _sobrepoe(inicio_a: datetime, duracao_a: int, inicio_b: datetime, duracao_b: int) -> bool:
    return (inicio_a < inicio_b + timedelta(minutes=duracao_b)
            and inicio_b < inicio_a + timedelta(minutes=duracao_a))


def _ocorrencia_nao_gerada_em(inicio: datetime, duracao: int) -> Recorrencia | None:
    """A regra cuja sessão prevista — e ainda não materializada — ocuparia este horário."""
    dia = timezone.localtime(inicio).date()
    for regra in Recorrencia.objects.filter(dia_semana=dia.weekday()).select_related("caso"):
        if not regra.ocorre_em(dia) or regra.consultas.filter(data_prevista=dia).exists():
            continue  # já gerada: quem confere é o model
        if _sobrepoe(inicio, duracao, momento(dia, regra.hora), regra.duracao):
            return regra
    return None


def _recusar_sessao_prevista(inicio: datetime, duracao: int) -> None:
    regra = _ocorrencia_nao_gerada_em(inicio, duracao)
    if regra is not None:
        raise ValidationError(
            f"Horário ocupado: {regra.caso} tem sessão prevista nesse horário "
            f"({regra.get_frequencia_display().lower()}, {regra.hora:%H:%M}).")


def _conflito_da_regra(nova: Recorrencia) -> str | None:
    """Confere a regra nova contra as outras regras e contra as consultas já existentes."""
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

    ocupadas = (
        Consulta.objects.exclude(estado=_CANCELADA)
        .exclude(recorrencia=nova)
        .filter(inicio__gte=momento(nova.inicio, time.min))
        .select_related("caso")
    )
    for consulta in ocupadas:
        dia = timezone.localtime(consulta.inicio).date()
        if nova.ocorre_em(dia) and _sobrepoe(momento(dia, nova.hora), nova.duracao, consulta.inicio, consulta.duracao):
            return (f"Horário ocupado: já existe consulta de {consulta.caso} em "
                    f"{timezone.localtime(consulta.inicio):%d/%m/%Y às %H:%M}.")
    return None


@transaction.atomic
def gerar_consultas(hoje: date | None = None) -> list[str]:
    """Materializa as sessões previstas até `JANELA_SEMANAS` à frente. Idempotente.

    Devolve as ocorrências que **não** puderam ser geradas por colisão. Não deveria haver nenhuma — a
    colisão é barrada ao criar a regra e ao marcar consulta —, mas se houver, a agenda mostra em vez
    de esconder (ADR-012). Nunca sobrescreve uma consulta existente para abrir espaço.
    """
    hoje = hoje or timezone.localdate()
    ate = hoje + timedelta(weeks=JANELA_SEMANAS)
    nao_geradas = []
    regras = (
        Recorrencia.objects.filter(inicio__lte=ate)
        .filter(Q(fim__isnull=True) | Q(fim__gt=hoje))
        .select_related("caso")
    )
    for regra in regras:
        existentes = set(regra.consultas.values_list("data_prevista", flat=True))
        for dia in regra.ocorrencias(max(hoje, regra.inicio), ate):
            if dia in existentes:
                continue
            consulta = Consulta(caso=regra.caso, recorrencia=regra, data_prevista=dia,
                                inicio=momento(dia, regra.hora), duracao=regra.duracao)
            try:
                with transaction.atomic():
                    consulta.save()
            except ValidationError as erro:
                nao_geradas.append(f"{regra.caso}, {dia:%d/%m}: {erro.messages[0]}")
    return nao_geradas


def _encerrar(regra: Recorrencia, a_partir_de: date) -> None:
    """Fecha a regra numa data, preservando o que não é mais só previsão (ADR-022).

    Saem as sessões futuras ainda agendadas e **não remarcadas**. Ficam as remarcadas à mão — é
    exatamente o que a marca `remarcada` protege — e tudo que já foi registrado.
    """
    regra.consultas.filter(data_prevista__gte=a_partir_de, estado=_AGENDADA, remarcada=False).delete()
    if regra.inicio >= a_partir_de and not regra.consultas.exists():
        regra.delete()  # nunca chegou a valer e não deixou rastro
        return
    regra.fim = max(a_partir_de, regra.inicio)
    regra.save()


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
    """Semanal, quinzenal ou avulso (ADR-053). Vale para "esta e as próximas" (ADR-022).

    Avulso não cria regra: encerra a vigente e deixa de prever sessões. Se a regra nova colidir com
    outra sessão, nada é gravado — nem o encerramento da anterior.
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
    gerar_consultas(hoje)
    return nova


@transaction.atomic
def marcar_avulsa(caso: Caso, *, inicio: datetime, duracao: int | None = None) -> Consulta:
    """Consulta fora de regra: do paciente avulso, ou uma sessão extra de quem tem frequência."""
    _recusar_encerrado(caso)
    duracao = duracao or _psicologo().duracao_sessao
    _recusar_sessao_prevista(inicio, duracao)
    return Consulta.objects.create(caso=caso, inicio=inicio, duracao=duracao)


@transaction.atomic
def remarcar(consulta: Consulta, *, inicio: datetime, duracao: int | None = None) -> Consulta:
    """Muda só esta sessão. Se ela veio de uma regra, fica marcada para a regra não desfazer (ADR-022)."""
    if consulta.estado != _AGENDADA:
        raise ValidationError("Só consulta ainda agendada pode ser remarcada.")
    _recusar_encerrado(consulta.caso)
    duracao = duracao or consulta.duracao
    _recusar_sessao_prevista(inicio, duracao)
    consulta.inicio = inicio
    consulta.duracao = duracao
    if consulta.recorrencia_id is not None:
        consulta.remarcada = True
    consulta.save()
    return consulta


@transaction.atomic
def registrar(
    consulta: Consulta,
    estado: str,
    *,
    contabilizada: bool | None = None,
    agora: datetime | None = None,
) -> Consulta:
    """Registra o que aconteceu. Comparecimento e cobrança são eixos independentes (ADR-023).

    Sem `contabilizada` explícito, vale o padrão: realizada entra na cobrança; falta entra se o
    psicólogo cobra falta (perfil, ADR-025); cancelada não entra. O psicólogo ajusta caso a caso.
    """
    if estado not in (_REALIZADA, _FALTA, _CANCELADA):
        raise ValidationError("Situação inválida para registro.")
    agora = agora or timezone.now()
    if estado != _CANCELADA and consulta.inicio > agora:
        raise ValidationError(
            "Consulta que ainda não começou só pode ser cancelada — realizada ou falta se registra depois.")
    if contabilizada is None:
        if estado == _REALIZADA:
            contabilizada = True
        elif estado == _FALTA:
            contabilizada = _psicologo().cobra_falta
        else:
            contabilizada = False
    consulta.estado = estado
    consulta.contabilizada = contabilizada
    consulta.registrada_em = agora
    consulta.save()
    return consulta


def _recusar_encerrado(caso: Caso) -> None:
    desfecho = caso.desfecho_aberto()
    if desfecho is not None:
        raise ValidationError(
            f"Este atendimento está encerrado ({desfecho.get_tipo_display().lower()} em {desfecho.data:%d/%m/%Y}). "
            "Retome-o antes de marcar sessões.")


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

    A frequência termina hoje e saem as consultas futuras ainda agendadas — todas, inclusive remarcadas e
    avulsas: o atendimento acabou, não há sessão a proteger. **O passado fica**, inclusive a consulta
    passada sem registro, que continua pendência: o desfecho não registra nada no lugar do psicólogo (ADR-052).

    Na desistência e na interrupção a iniciativa decorre do tipo; em alta e encaminhamento, é informada.
    """
    agora = agora or timezone.now()
    hoje = timezone.localdate(agora)
    data = data or hoje
    if data > hoje:
        raise ValidationError("O desfecho se registra quando acontece — a data não pode estar no futuro.")
    if caso.desfecho_aberto() is not None:
        raise ValidationError("Este atendimento já está encerrado.")

    # Gravado antes de mexer na agenda: se o registro for inválido, nada foi apagado.
    desfecho = Desfecho.objects.create(
        caso=caso, tipo=tipo, iniciativa=iniciativa or Desfecho.INICIATIVA_DO_TIPO.get(tipo, ""),
        motivo=motivo, data=data)

    caso.consultas.filter(estado=_AGENDADA, inicio__gt=agora).delete()
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


def consultas_sem_registro(agora: datetime | None = None):
    """Consultas que já começaram e seguem agendadas — pendência, nunca registro automático (ADR-052)."""
    agora = agora or timezone.now()
    return Consulta.objects.filter(estado=_AGENDADA, inicio__lt=agora).select_related("caso").order_by("inicio")
