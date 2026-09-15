"""O que cada paciente deve, o que pagou e o que está pendente (ADR-062, ADR-063).

**O devido é cálculo, não registro.** A mensalidade vem da condição de cobrança do mês; a sessão, da consulta
cobrada e do valor por sessão vigente na data dela. Só o pagamento é gravado — pelo psicólogo, sempre.

**Lembrete** (N-08): uma cobrança fica pendente **a partir do vencimento** e enquanto o pago não cobrir o
devido. Paga antes do vencimento, nunca aparece.
"""

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from atendimentos.models import Consulta
from financeiro.models import Pagamento
from pacientes.models import Caso, CondicaoCobranca

MENSALIDADE = "MENSALIDADE"
SESSAO = "SESSAO"

_COBRADAS = [Consulta.Estado.REALIZADA, Consulta.Estado.FALTA_COBRADA]
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
          "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
_DESDE_SEMPRE = date(2000, 1, 1)


def ultimo_dia(ano: int, mes: int) -> date:
    return date(ano, mes, monthrange(ano, mes)[1])


def mes_seguinte(dia: date) -> date:
    return date(dia.year + (dia.month == 12), dia.month % 12 + 1, 1)


def mes_anterior(dia: date) -> date:
    return date(dia.year - (dia.month == 1), (dia.month - 2) % 12 + 1, 1)


def _meia_noite(dia: date) -> datetime:
    return timezone.make_aware(datetime.combine(dia, time.min))


@dataclass
class Cobranca:
    """O que um paciente deve por uma mensalidade ou por uma sessão, e o que já pagou por ela. Não é gravada."""

    caso: Caso
    tipo: str
    vencimento: date
    devido: Decimal
    pagamentos: list = field(default_factory=list)
    mes: date | None = None
    consulta: Consulta | None = None

    @property
    def pago(self) -> Decimal:
        return sum((pagamento.valor for pagamento in self.pagamentos), Decimal("0"))

    @property
    def saldo(self) -> Decimal:
        return max(self.devido - self.pago, Decimal("0"))

    @property
    def quitada(self) -> bool:
        return self.pago >= self.devido

    def pendente(self, hoje: date | None = None) -> bool:
        """O lembrete: venceu e o pago não cobre o devido. Pago antes do vencimento, nunca fica pendente."""
        return not self.quitada and self.vencimento <= (hoje or timezone.localdate())

    @property
    def formas(self) -> list[str]:
        return sorted({pagamento.get_forma_display() for pagamento in self.pagamentos})

    @property
    def descricao(self) -> str:
        if self.tipo == MENSALIDADE:
            return f"Mensalidade de {_MESES[self.mes.month - 1]}/{self.mes.year}"
        return f"Sessão de {self.vencimento:%d/%m/%Y}"

    @property
    def url_pagar(self) -> str:
        if self.tipo == MENSALIDADE:
            return reverse("financeiro:pagar_mensalidade", args=[self.caso.pk, self.mes.year, self.mes.month])
        return reverse("financeiro:pagar_sessao", args=[self.consulta.pk])


def _encerrado_o_mes_inteiro(caso: Caso, inicio: date, fim: date) -> bool:
    return any(d.data < inicio and (d.retomado_em is None or d.retomado_em > fim) for d in caso.desfechos.all())


def mensalidade(caso: Caso, ano: int, mes: int) -> Cobranca | None:
    """A mensalidade de um mês, ou `None` se o caso não paga por mês nele.

    Vale a condição vigente **no fim do mês**: a primeira condição pode começar no meio dele (ADR-050), e a
    mensalidade é cheia (ADR-062). Mês inteiro com o atendimento encerrado não gera mensalidade.
    """
    inicio, fim = date(ano, mes, 1), ultimo_dia(ano, mes)
    condicao = caso.condicao_vigente(fim)
    if condicao is None or condicao.modalidade != CondicaoCobranca.Modalidade.MENSAL:
        return None
    if _encerrado_o_mes_inteiro(caso, inicio, fim):
        return None
    return Cobranca(
        caso=caso, tipo=MENSALIDADE, vencimento=condicao.vencimento_em(ano, mes), devido=condicao.valor,
        pagamentos=list(Pagamento.objects.filter(caso=caso, mes_referencia=inicio)), mes=inicio)


def sessao(consulta: Consulta) -> Cobranca | None:
    """O pagamento pendente de uma sessão cobrada, para quem paga por sessão. Vence no dia dela (ADR-063)."""
    if not consulta.cobrada:
        return None
    dia = timezone.localtime(consulta.inicio).date()
    condicao = consulta.caso.condicao_vigente(dia)
    if condicao is None or condicao.modalidade != CondicaoCobranca.Modalidade.POR_SESSAO:
        return None
    return Cobranca(caso=consulta.caso, tipo=SESSAO, vencimento=dia, devido=condicao.valor,
                    pagamentos=list(consulta.pagamentos.all()), consulta=consulta)


def _consultas_cobradas(de: date, ate: date, caso: Caso | None = None):
    consultas = (
        Consulta.objects.filter(estado__in=_COBRADAS, inicio__gte=_meia_noite(de),
                                inicio__lt=_meia_noite(ate + timedelta(days=1)))
        .select_related("caso").prefetch_related("caso__pacientes", "pagamentos")
    )
    return consultas.filter(caso=caso) if caso is not None else consultas


def _casos(caso: Caso | None):
    return [caso] if caso is not None else list(Caso.objects.prefetch_related("pacientes", "desfechos"))


def cobrancas_do_mes(ano: int, mes: int, *, caso: Caso | None = None) -> list[Cobranca]:
    """Mensalidades do mês e sessões cobradas no mês, de quem paga por sessão."""
    cobrancas = [c for c in (mensalidade(item, ano, mes) for item in _casos(caso)) if c]
    consultas = _consultas_cobradas(date(ano, mes, 1), ultimo_dia(ano, mes), caso)
    cobrancas += [c for c in (sessao(consulta) for consulta in consultas) if c]
    return sorted(cobrancas, key=lambda c: (c.vencimento, str(c.caso)))


def pagamentos_pendentes(hoje: date | None = None, *, caso: Caso | None = None) -> list[Cobranca]:
    """Tudo o que venceu e não foi quitado, de qualquer mês — o que o lembrete mostra."""
    hoje = hoje or timezone.localdate()
    pendentes = []
    for item in _casos(caso):
        primeira = item.condicoes.filter(modalidade=CondicaoCobranca.Modalidade.MENSAL).order_by("vigente_desde").first()
        if primeira is None:
            continue
        mes = date(primeira.vigente_desde.year, primeira.vigente_desde.month, 1)
        while mes <= hoje:
            cobranca = mensalidade(item, mes.year, mes.month)
            if cobranca and cobranca.pendente(hoje):
                pendentes.append(cobranca)
            mes = mes_seguinte(mes)
    for consulta in _consultas_cobradas(_DESDE_SEMPRE, hoje, caso):
        cobranca = sessao(consulta)
        if cobranca and cobranca.pendente(hoje):
            pendentes.append(cobranca)
    return sorted(pendentes, key=lambda c: (c.vencimento, str(c.caso)))


def _recusar_invalido(data: date, forma: str) -> None:
    if forma not in Pagamento.Forma.values:
        raise ValidationError("Informe a forma de pagamento: Pix, cartão, dinheiro ou transferência.")
    if data > timezone.localdate():
        raise ValidationError("O pagamento se registra quando é recebido — a data não pode estar no futuro.")


@transaction.atomic
def registrar_pagamento_mensalidade(
    caso: Caso, *, ano: int, mes: int, valor: Decimal, data: date, forma: str, observacao: str = "",
) -> Pagamento:
    """Pagamento da mensalidade de um mês. Pagou menos, o resto fica pendente; pagou a mais, fica registrado."""
    _recusar_invalido(data, forma)
    if mensalidade(caso, ano, mes) is None:
        raise ValidationError(f"Não há mensalidade de {mes:02d}/{ano} para este atendimento.")
    return Pagamento.objects.create(caso=caso, mes_referencia=date(ano, mes, 1), valor=valor, data=data,
                                    forma=forma, observacao=observacao)


@transaction.atomic
def registrar_pagamento_sessao(
    consulta: Consulta, *, data: date, forma: str, valor: Decimal | None = None, observacao: str = "",
) -> Pagamento:
    """Pagamento de uma sessão. Sem valor, vale o que falta pagar dela."""
    _recusar_invalido(data, forma)
    cobranca = sessao(consulta)
    if cobranca is None:
        raise ValidationError("Esta consulta não gera pagamento por sessão.")
    if valor is None:
        if cobranca.quitada:
            raise ValidationError("Esta sessão já está paga.")
        valor = cobranca.saldo
    return Pagamento.objects.create(caso=consulta.caso, consulta=consulta, valor=valor, data=data,
                                    forma=forma, observacao=observacao)


@transaction.atomic
def excluir_pagamento(pagamento: Pagamento) -> None:
    """Registro feito por engano. A cobrança volta a ficar pendente, se já venceu."""
    pagamento.delete()
