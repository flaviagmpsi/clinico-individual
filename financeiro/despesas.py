"""Despesas da clínica e o fluxo de caixa do mês (ADR-083).

**A ocorrência é cálculo, não registro.** A despesa mensal é uma linha; o que ela gera em cada mês sai daqui. Gravado
é só o que o psicólogo informa: a despesa e a baixa ("paguei") de cada mês.

**O fluxo de caixa é por competência**, como o resto do financeiro (ADR-062): a receita de um mês é a das cobranças
**daquele mês**, recebida ou não; a despesa de um mês é a que vence nele, paga ou não. Assim o mês fechado não muda
quando um atrasado paga no mês seguinte — muda só de "a receber" para "recebida".
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from atendimentos.servicos import sessoes_previstas
from financeiro.models import BaixaDeDespesa, Despesa
from financeiro.servicos import Carga, carregar, cobrancas_do_mes, ultimo_dia
from pacientes.models import CondicaoCobranca

ZERO = Decimal("0")


@dataclass
class Ocorrencia:
    """Uma despesa num mês: o que vence, quando, e se já foi paga."""

    despesa: Despesa
    mes: date
    vencimento: date
    baixa: BaixaDeDespesa | None = None

    @property
    def paga(self) -> bool:
        return self.baixa is not None

    @property
    def valor(self) -> Decimal:
        """Paga, vale o que saiu do caixa; em aberto, o valor cadastrado."""
        return self.baixa.valor if self.baixa else self.despesa.valor

    def atrasada(self, hoje: date | None = None) -> bool:
        return not self.paga and self.vencimento < (hoje or timezone.localdate())


def _vencimento_no_mes(despesa: Despesa, ano: int, mes: int) -> date:
    """O dia do primeiro vencimento, levado ao mês pedido. Dia 31 em fevereiro vira o último dia."""
    return date(ano, mes, min(despesa.vencimento.day, ultimo_dia(ano, mes).day))


def _ocorre_em(despesa: Despesa, mes: date) -> bool:
    if not despesa.mensal:
        return despesa.vencimento.replace(day=1) == mes
    return despesa.vencimento.replace(day=1) <= mes and (despesa.fim is None or despesa.fim >= mes)


@dataclass
class CargaDeDespesas:
    """As despesas e as baixas de um período, lidas de uma vez — para o ano não custar doze idas ao banco."""

    despesas: list
    baixas: dict  # (despesa_id, primeiro dia do mês) -> baixa


def carregar_despesas(de: date, ate: date) -> CargaDeDespesas:
    inicio = de.replace(day=1)
    avulsas = Q(mensal=False, vencimento__gte=inicio, vencimento__lte=ate)
    mensais = Q(mensal=True, vencimento__lte=ate) & (Q(fim__isnull=True) | Q(fim__gte=inicio))
    baixas = BaixaDeDespesa.objects.filter(mes__gte=inicio, mes__lte=ate)
    return CargaDeDespesas(despesas=list(Despesa.objects.filter(avulsas | mensais)),
                           baixas={(baixa.despesa_id, baixa.mes): baixa for baixa in baixas})


def despesas_do_mes(ano: int, mes: int, *, carga: CargaDeDespesas | None = None) -> list[Ocorrencia]:
    inicio, fim = date(ano, mes, 1), ultimo_dia(ano, mes)
    carga = carga or carregar_despesas(inicio, fim)
    ocorrencias = [
        Ocorrencia(despesa=despesa, mes=inicio, baixa=carga.baixas.get((despesa.pk, inicio)),
                   vencimento=despesa.vencimento if not despesa.mensal else _vencimento_no_mes(despesa, ano, mes))
        for despesa in carga.despesas if _ocorre_em(despesa, inicio)
    ]
    return sorted(ocorrencias, key=lambda o: (o.vencimento, o.despesa.descricao))


@transaction.atomic
def pagar(despesa: Despesa, mes: date, *, pago_em: date | None = None, valor: Decimal | None = None) -> BaixaDeDespesa:
    """Marca a despesa daquele mês como paga. O valor pago fica na baixa — é o que saiu do caixa."""
    mes = mes.replace(day=1)
    pago_em = pago_em or timezone.localdate()
    if not _ocorre_em(despesa, mes):
        raise ValidationError("Esta despesa não existe neste mês.")
    if pago_em > timezone.localdate():
        raise ValidationError("O pagamento se marca quando é feito — a data não pode estar no futuro.")
    if BaixaDeDespesa.objects.filter(despesa=despesa, mes=mes).exists():
        raise ValidationError("Esta despesa já está marcada como paga neste mês.")
    return BaixaDeDespesa.objects.create(despesa=despesa, mes=mes, pago_em=pago_em, valor=valor or despesa.valor)


def desfazer_pagamento(despesa: Despesa, mes: date) -> None:
    """Marcou por engano: a baixa daquele mês sai, e a despesa volta a ficar em aberto."""
    baixa = BaixaDeDespesa.objects.filter(despesa=despesa, mes=mes.replace(day=1)).first()
    if baixa is None:
        raise ValidationError("Esta despesa não está marcada como paga neste mês.")
    baixa.delete()


def encerrar(despesa: Despesa, ultimo_mes: date) -> Despesa:
    """A despesa mensal deixa de aparecer depois de `ultimo_mes`. O que já foi pago fica como está."""
    if not despesa.mensal:
        raise ValidationError("Só despesa mensal se encerra. A de um mês só se exclui.")
    despesa.fim = ultimo_dia(ultimo_mes.year, ultimo_mes.month)
    despesa.save()
    return despesa


def excluir(despesa: Despesa) -> None:
    """Cadastrada por engano. Com mês já pago, recusa: histórico financeiro não some — encerra-se."""
    if despesa.baixas.exists():
        raise ValidationError(
            "Esta despesa já tem mês marcado como pago. Para ela parar de aparecer, encerre-a; "
            "para apagá-la, desfaça antes os pagamentos.")
    despesa.delete()


# --- Fluxo de caixa ------------------------------------------------------------------------------------------------

@dataclass
class Fluxo:
    mes: date
    receitas_recebidas: Decimal
    receitas_a_receber: Decimal
    despesas_pagas: Decimal
    despesas_a_pagar: Decimal
    # Do "a receber", quanto é **previsão**: sessão que a frequência prevê e ainda não aconteceu (ADR-061).
    receitas_previstas: Decimal = ZERO

    @property
    def total_receitas(self) -> Decimal:
        return self.receitas_recebidas + self.receitas_a_receber

    @property
    def total_despesas(self) -> Decimal:
        return self.despesas_pagas + self.despesas_a_pagar

    @property
    def resultado(self) -> Decimal:
        """O resultado do mês se tudo se cumprir: todas as receitas menos todas as despesas."""
        return self.total_receitas - self.total_despesas

    @property
    def resultado_realizado(self) -> Decimal:
        """O que já aconteceu de fato: o recebido menos o pago."""
        return self.receitas_recebidas - self.despesas_pagas


def previsto_por_mes(de: date, ate: date, agora, carga: Carga) -> dict:
    """Quanto as sessões que a frequência ainda prevê vão render, mês a mês — só de quem paga por sessão (ADR-061).

    A que passou sem cadastro não é previsão: é pendência. Uma chamada só para o período inteiro, e a condição de
    cobrança sai da `carga`, já na memória (ADR-086).
    """
    totais: dict = {}
    if de > ate:
        return totais
    for sessao in sessoes_previstas(de, ate):
        if sessao.pendente(agora):
            continue
        caso = carga.caso(sessao.caso.pk) or sessao.caso
        condicao = caso.condicao_vigente(sessao.data)
        if condicao is not None and condicao.modalidade == CondicaoCobranca.Modalidade.POR_SESSAO:
            mes = sessao.data.replace(day=1)
            totais[mes] = totais.get(mes, ZERO) + condicao.valor
    return totais


def fluxo_de_caixa(ano: int, mes: int, agora=None, *, carga: Carga | None = None,
                   despesas: CargaDeDespesas | None = None, previstos: dict | None = None) -> Fluxo:
    agora = agora or timezone.now()
    hoje = timezone.localdate(agora)
    inicio, fim = date(ano, mes, 1), ultimo_dia(ano, mes)
    carga = carga or carregar(inicio, fim)
    if previstos is None:
        previstos = previsto_por_mes(max(inicio, hoje), fim, agora, carga)
    previsto = previstos.get(inicio, ZERO)
    cobrancas = cobrancas_do_mes(ano, mes, carga=carga)
    ocorrencias = despesas_do_mes(ano, mes, carga=despesas)
    return Fluxo(
        mes=inicio,
        receitas_recebidas=sum((c.pago for c in cobrancas), ZERO),
        receitas_a_receber=sum((c.saldo for c in cobrancas), ZERO) + previsto,
        receitas_previstas=previsto,
        despesas_pagas=sum((o.valor for o in ocorrencias if o.paga), ZERO),
        despesas_a_pagar=sum((o.valor for o in ocorrencias if not o.paga), ZERO),
    )


def fluxo_do_ano(ano: int, agora=None) -> list[Fluxo]:
    """Os doze meses, para o gráfico de resultado previsto do ano (I-12). Três cargas, e não doze vezes três."""
    agora = agora or timezone.now()
    hoje = timezone.localdate(agora)
    de, ate = date(ano, 1, 1), date(ano, 12, 31)
    carga, despesas = carregar(de, ate), carregar_despesas(de, ate)
    previstos = previsto_por_mes(max(de, hoje), ate, agora, carga)
    return [fluxo_de_caixa(ano, mes, agora, carga=carga, despesas=despesas, previstos=previstos)
            for mes in range(1, 13)]
