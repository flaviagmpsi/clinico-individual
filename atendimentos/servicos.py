"""A agenda: prever sessões pela frequência e cadastrar o que aconteceu (ADR-060).

`agenda` guarda a regra e não conhece consulta; `atendimentos` guarda a consulta e é quem sabe cruzar uma com a
outra (regra 5 de dependência). Tudo aqui roda no escopo do psicólogo corrente.

- **Previsão é cálculo, não registro.** `sessoes_previstas` deriva as sessões da regra de frequência a cada
  chamada; nada é gravado até o psicólogo cadastrar.
- **Só o psicólogo cadastra** (ADR-052, ADR-060): presente, faltou sem avisar, cliente cancelou, profissional
  cancelou ou remarcada (ADR-065). Sessão prevista que passou sem cadastro é **pendente**, e é dada como
  confirmada até ele dizer o contrário.
- **Só se cadastra o que já aconteceu.** Data e hora no futuro são recusadas.
- **Colisão bloqueia** (ADR-024) entre consultas que ocupam o horário e entre regras de frequência. Sessão
  prevista não bloqueia cadastro: previsão não é registro.

E o fim do atendimento: o **desfecho** encerra a frequência, e **retomar** reabre (ADR-049, ADR-055).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from agenda.models import HorarioDisponivel, Recorrencia
from atendimentos.models import Consulta, Desfecho
from core import contexto
from pacientes.models import Caso, Paciente

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

    @property
    def modalidade(self) -> str:
        """Online ou presencial, pelo padrão do paciente (ADR-065)."""
        return modalidade_do_caso(self.caso)

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


@dataclass(frozen=True)
class SessaoRemarcada:
    """O destino de uma sessão remarcada (ADR-068): esperada naquele horário, ainda não cadastrada.

    Tem a mesma cara de `SessaoPrevista` para a tela poder tratar as duas juntas, mas não vem de uma
    frequência: vem da consulta que foi remarcada, e é ela que diz o horário, a duração e a modalidade.
    """

    origem: Consulta

    @property
    def caso(self) -> Caso:
        return self.origem.caso

    @property
    def inicio(self) -> datetime:
        return self.origem.remarcada_para

    @property
    def duracao(self) -> int:
        return self.origem.duracao

    @property
    def fim(self) -> datetime:
        return self.inicio + timedelta(minutes=self.duracao)

    @property
    def data(self) -> date:
        return timezone.localtime(self.inicio).date()

    @property
    def data_iso(self) -> str:
        return self.data.isoformat()

    @property
    def modalidade(self) -> str:
        return self.origem.modalidade

    def pendente(self, agora: datetime | None = None) -> bool:
        return self.inicio <= (agora or timezone.now())


def sessoes_remarcadas(de: date, ate: date, *, caso: Caso | None = None) -> list[SessaoRemarcada]:
    """As sessões remarcadas **para** este período e que ainda não foram cadastradas."""
    consultas = (
        Consulta.objects.filter(estado=Consulta.Estado.REMARCADA,
                                remarcada_para__gte=momento(de, time.min),
                                remarcada_para__lt=momento(ate + timedelta(days=1), time.min))
        .select_related("caso").prefetch_related("caso__pacientes")
    )
    if caso is not None:
        consultas = consultas.filter(caso=caso)
    consultas = list(consultas)
    # A sessão nova, depois de cadastrada, deixa de ser espera: some daqui como a prevista some da previsão.
    cadastradas = set(
        Consulta.objects.filter(inicio__in=[c.remarcada_para for c in consultas])
        .values_list("caso_id", "inicio")
    )
    esperadas = [SessaoRemarcada(c) for c in consultas if (c.caso_id, c.remarcada_para) not in cadastradas]
    return sorted(esperadas, key=lambda sessao: sessao.inicio)


def sessoes_pendentes(agora: datetime | None = None,
                      *, caso: Caso | None = None) -> list[SessaoPrevista | SessaoRemarcada]:
    """O que já começou e ninguém cadastrou — pendência, nunca cadastro automático.

    São duas origens: a frequência, que prevê, e a remarcação, que marcou data nova (ADR-068).
    """
    agora = agora or timezone.now()
    hoje = timezone.localdate(agora)
    esperadas = (sessoes_previstas(_DESDE_SEMPRE, hoje, caso=caso)
                 + sessoes_remarcadas(_DESDE_SEMPRE, hoje, caso=caso))
    return sorted([sessao for sessao in esperadas if sessao.pendente(agora)],
                  key=lambda sessao: sessao.inicio)


# --- Calendário (ADR-073) ------------------------------------------------------------------------------------

PREVISTA = "PREVISTA"  # o "filtro de situação" das sessões esperadas, que não têm situação ainda


@dataclass(frozen=True)
class HorarioLivre:
    """Uma faixa da grade de horários em que ninguém está. Só existe onde há horário cadastrado (ADR-073)."""

    inicio: datetime
    duracao: int

    @property
    def fim(self) -> datetime:
        return self.inicio + timedelta(minutes=self.duracao)


def horarios_livres(dia: date, ocupados: list, blocos, duracao: int) -> list[HorarioLivre]:
    """Da grade do dia, as faixas de uma sessão em que ninguém está — de hora em hora, como na planilha.

    `ocupados` são os itens do dia que seguram o horário: consulta que ocupa (ADR-024) e sessão esperada.
    Consulta cancelada ou remarcada não segura — o horário dela está livre de novo.
    """
    livres = []
    for bloco in blocos:
        inicio, fim = momento(dia, bloco.inicio), momento(dia, bloco.fim)
        while inicio + timedelta(minutes=duracao) <= fim:
            if not any(_sobrepoe(inicio, duracao, item.inicio, item.duracao) for item in ocupados):
                livres.append(HorarioLivre(inicio, duracao))
            inicio += timedelta(hours=1)
    return livres


def hora_curta(instante: datetime) -> str:
    """`14H`, `8H30` — o jeito da planilha, sem os zeros que não dizem nada."""
    local = timezone.localtime(instante)
    return f"{local.hour}H" + (f"{local.minute:02d}" if local.minute else "")


@dataclass
class DiaDoCalendario:
    """Uma coluna do calendário: os cartões do dia em ordem de horário, cada um `(tipo, item, hora)`."""

    dia: date
    cartoes: list

    @property
    def sessoes(self) -> list:
        return [item for tipo, item, _ in self.cartoes if tipo != "livre"]

    @property
    def vazio(self) -> bool:
        return not self.cartoes


def calendario(de: date, ate: date, *, situacao: str = "", duracao: int = 50) -> list[DiaDoCalendario]:
    """Um dia por data entre `de` e `ate`: sessões cadastradas, esperadas e, sem filtro, os horários livres.

    Com filtro de situação a tela responde "onde estão as faltas?" — nem previsão nem horário livre cabem
    nessa pergunta. `PREVISTA` é o filtro das esperadas.
    """
    consultas = []
    if situacao != PREVISTA:
        achadas = (
            Consulta.objects.filter(inicio__gte=momento(de, time.min),
                                    inicio__lt=momento(ate + timedelta(days=1), time.min))
            .select_related("caso", "recorrencia").prefetch_related("caso__pacientes")
        )
        consultas = list(achadas.filter(estado=situacao) if situacao else achadas)
    esperadas = []
    if situacao in ("", PREVISTA):
        esperadas = ([("prevista", s) for s in sessoes_previstas(de, ate)]
                     + [("remarcada", s) for s in sessoes_remarcadas(de, ate)])
    itens = [("consulta", c) for c in consultas] + esperadas

    blocos_por_dia: dict[int, list] = {}
    if not situacao:
        for bloco in HorarioDisponivel.objects.all():
            blocos_por_dia.setdefault(bloco.dia_semana, []).append(bloco)

    dias = []
    for n in range((ate - de).days + 1):
        dia = de + timedelta(days=n)
        do_dia = [par for par in itens if timezone.localtime(par[1].inicio).date() == dia]
        ocupados = [item for tipo, item in do_dia if tipo != "consulta" or item.ocupa_horario]
        livres = horarios_livres(dia, ocupados, blocos_por_dia.get(dia.weekday(), []), duracao)
        cartoes = [(tipo, item, hora_curta(item.inicio)) for tipo, item in do_dia]
        cartoes += [("livre", livre, hora_curta(livre.inicio)) for livre in livres]
        dias.append(DiaDoCalendario(dia, sorted(cartoes, key=lambda cartao: cartao[1].inicio)))
    return dias


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

def _recusar_se_tem_pagamento(consulta: Consulta, acao: str) -> None:
    """Consulta com pagamento não deixa de ser cobrada (ADR-063): seria dinheiro recebido por sessão nenhuma.

    Nome reverso `pagamentos`, sem importar `financeiro`, que depende deste app (regra 5 de dependência).
    """
    if consulta.pk and consulta.pagamentos.exists():
        raise ValidationError(f"Esta consulta tem pagamento registrado. Exclua o pagamento antes de {acao}.")


def _recusar_se_tem_prontuario(consulta: Consulta, acao: str) -> None:
    """Sessão com prontuário aconteceu, e o prontuário tem guarda obrigatória (ADR-064).

    Nome reverso `prontuarios`, sem importar o app, que depende deste (regra 6 de dependência).
    """
    if consulta.pk and consulta.prontuarios.exists():
        raise ValidationError(f"Esta sessão tem prontuário. Não é possível {acao}.")


def _exigir_situacao(estado: str) -> None:
    if estado not in Consulta.Estado.values:
        raise ValidationError(
            "Escolha o que aconteceu: presente, faltou sem avisar, cliente cancelou, profissional cancelou "
            "ou remarcada.")


def _cobranca(estado: str, cobrada: bool | None) -> bool:
    """A cobrança decorre da situação (ADR-065). Só o cancelamento pelo cliente admite escolha."""
    _exigir_situacao(estado)
    if cobrada is None or estado not in Consulta.ESCOLHE_SE_COBRA:
        return Consulta.COBRA_POR_PADRAO[estado]
    return cobrada


def _remarcacao(estado: str, remarcada_para: datetime | None) -> datetime | None:
    """A data nova só existe na remarcada (ADR-068). Corrigir a situação para outra coisa a apaga."""
    return remarcada_para if estado == Consulta.Estado.REMARCADA else None


def _valor_da_sessao(estado: str, cobrada: bool | None, valor: Decimal | None) -> Decimal | None:
    """O valor **desta** sessão (ADR-070). Sessão que não entra na cobrança não tem valor nenhum."""
    return valor if _cobranca(estado, cobrada) else None


def modalidade_do_caso(caso: Caso) -> str:
    """O padrão do paciente (ADR-065). No casal, o do primeiro participante."""
    participante = caso.pacientes.first()
    return participante.modalidade if participante else Paciente.Modalidade.PRESENCIAL


def _cadastrar(consulta: Consulta, agora: datetime | None) -> Consulta:
    _exigir_situacao(consulta.estado)
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
    modalidade: str | None = None,
    cobrada: bool | None = None,
    valor: Decimal | None = None,
    remarcada_para: datetime | None = None,
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
                        inicio=momento(data, hora or regra.hora), duracao=duracao or regra.duracao,
                        cobrada=_cobranca(estado, cobrada),
                        modalidade=modalidade or modalidade_do_caso(regra.caso),
                        valor=_valor_da_sessao(estado, cobrada, valor),
                        remarcada_para=_remarcacao(estado, remarcada_para))
    return _cadastrar(consulta, agora)


@transaction.atomic
def cadastrar_avulsa(
    caso: Caso,
    *,
    estado: str,
    inicio: datetime,
    duracao: int | None = None,
    modalidade: str | None = None,
    cobrada: bool | None = None,
    valor: Decimal | None = None,
    remarcada_para: datetime | None = None,
    agora: datetime | None = None,
) -> Consulta:
    """Consulta fora da frequência: do paciente avulso, uma sessão extra, ou a remarcada que aconteceu."""
    desfecho = caso.desfecho_aberto()
    if desfecho is not None and timezone.localtime(inicio).date() > desfecho.data:
        raise ValidationError(
            f"Este atendimento está encerrado desde {desfecho.data:%d/%m/%Y}. "
            "Retome-o antes de cadastrar sessões depois dessa data.")
    consulta = Consulta(caso=caso, estado=estado, inicio=inicio,
                        duracao=duracao or _psicologo().duracao_sessao,
                        cobrada=_cobranca(estado, cobrada), modalidade=modalidade or modalidade_do_caso(caso),
                        valor=_valor_da_sessao(estado, cobrada, valor),
                        remarcada_para=_remarcacao(estado, remarcada_para))
    return _cadastrar(consulta, agora)


@transaction.atomic
def alterar_situacao(consulta: Consulta, estado: str, *, cobrada: bool | None = None,
                    modalidade: str | None = None, valor: Decimal | None = None,
                    remarcada_para: datetime | None = None) -> Consulta:
    """Corrige o que foi cadastrado. A data não muda: para isso, exclui-se o cadastro e cadastra-se de novo."""
    cobra = _cobranca(estado, cobrada)
    if estado != Consulta.Estado.REALIZADA:
        _recusar_se_tem_prontuario(consulta, "mudar a situação")
    if not cobra:
        _recusar_se_tem_pagamento(consulta, "deixar de cobrá-la")
    consulta.estado = estado
    consulta.cobrada = cobra
    consulta.valor = valor if cobra else None
    consulta.remarcada_para = _remarcacao(estado, remarcada_para or consulta.remarcada_para)
    if modalidade:
        consulta.modalidade = modalidade
    consulta.save()
    return consulta


@transaction.atomic
def excluir_consulta(consulta: Consulta) -> None:
    """Cadastro feito por engano. Se era da frequência, a sessão volta a ser pendente."""
    _recusar_se_tem_prontuario(consulta, "excluir o cadastro")
    _recusar_se_tem_pagamento(consulta, "excluir o cadastro")
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
