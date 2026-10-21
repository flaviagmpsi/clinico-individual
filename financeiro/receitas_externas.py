"""Ganhos do psicólogo fora da clínica particular (ADR-136): supervisão, ONG, CLT, bicos.

Espelha `financeiro.despesas` do outro lado do caixa. **A ocorrência é cálculo, não registro:** a renda mensal é
uma linha, e o que ela rende em cada mês sai daqui; gravado é só a receita e o recebimento ("recebi") de cada mês.

**Por competência**, como o resto do financeiro (ADR-062): a receita de um mês é a que vence nele, recebida ou
não — assim o mês fechado não muda quando um atrasado cai no mês seguinte, só vira de "a receber" para "recebida".
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from financeiro.models import RecebimentoExterno, ReceitaExterna
from financeiro.servicos import ultimo_dia

ZERO = Decimal("0")


@dataclass
class OcorrenciaDeReceita:
    """Uma receita externa num mês: o que se espera receber, quando, e se já caiu."""

    receita: ReceitaExterna
    mes: date
    vencimento: date
    recebimento: RecebimentoExterno | None = None

    @property
    def recebida(self) -> bool:
        return self.recebimento is not None

    @property
    def valor(self) -> Decimal:
        """Recebida, vale o que entrou no caixa; em aberto, o valor cadastrado."""
        return self.recebimento.valor if self.recebimento else self.receita.valor

    @property
    def entra_no_carne_leao(self) -> bool:
        return self.receita.entra_no_carne_leao

    def atrasada(self, hoje: date | None = None) -> bool:
        return not self.recebida and self.vencimento < (hoje or timezone.localdate())


def _vencimento_no_mes(receita: ReceitaExterna, ano: int, mes: int) -> date:
    """O dia do primeiro recebimento, levado ao mês pedido. Dia 31 em fevereiro vira o último dia."""
    return date(ano, mes, min(receita.vencimento.day, ultimo_dia(ano, mes).day))


def _ocorre_em(receita: ReceitaExterna, mes: date) -> bool:
    if not receita.mensal:
        return receita.vencimento.replace(day=1) == mes
    return receita.vencimento.replace(day=1) <= mes and (receita.fim is None or receita.fim >= mes)


@dataclass
class CargaDeReceitas:
    """As receitas e os recebimentos de um período, lidos de uma vez — para o ano não custar doze idas ao banco."""

    receitas: list
    recebimentos: dict  # (receita_id, primeiro dia do mês) -> recebimento


def carregar_receitas(de: date, ate: date) -> CargaDeReceitas:
    inicio = de.replace(day=1)
    avulsas = Q(mensal=False, vencimento__gte=inicio, vencimento__lte=ate)
    mensais = Q(mensal=True, vencimento__lte=ate) & (Q(fim__isnull=True) | Q(fim__gte=inicio))
    recebimentos = RecebimentoExterno.objects.filter(mes__gte=inicio, mes__lte=ate)
    return CargaDeReceitas(
        receitas=list(ReceitaExterna.objects.filter(avulsas | mensais)),
        recebimentos={(r.receita_id, r.mes): r for r in recebimentos})


def receitas_do_mes(ano: int, mes: int, *, carga: CargaDeReceitas | None = None) -> list[OcorrenciaDeReceita]:
    inicio = date(ano, mes, 1)
    carga = carga or carregar_receitas(inicio, ultimo_dia(ano, mes))
    ocorrencias = [
        OcorrenciaDeReceita(
            receita=receita, mes=inicio, recebimento=carga.recebimentos.get((receita.pk, inicio)),
            vencimento=receita.vencimento if not receita.mensal else _vencimento_no_mes(receita, ano, mes))
        for receita in carga.receitas if _ocorre_em(receita, inicio)
    ]
    return sorted(ocorrencias, key=lambda o: (o.vencimento, o.receita.descricao))


def recebimentos_pendentes(ate: date | None = None) -> list[OcorrenciaDeReceita]:
    """As ocorrências ainda não recebidas, do mês corrente para trás — o que o psicólogo tem a receber.

    Para o painel: "controle do que tem que receber" (pedido do usuário). Não inclui mês futuro: o que ainda vai
    vencer não é pendência, é previsão (mesma lógica da cobrança da clínica).
    """
    ate = ate or timezone.localdate()
    inicio_do_mes = date(ate.year, ate.month, 1)
    carga = carregar_receitas(date(ate.year - 2, 1, 1), ultimo_dia(ate.year, ate.month))
    pendentes: list[OcorrenciaDeReceita] = []
    mes = date(ate.year - 2, 1, 1)
    while mes <= inicio_do_mes:
        for o in receitas_do_mes(mes.year, mes.month, carga=carga):
            if not o.recebida:
                pendentes.append(o)
        mes = date(mes.year + (mes.month // 12), (mes.month % 12) + 1, 1)
    return sorted(pendentes, key=lambda o: o.vencimento)


@transaction.atomic
def receber(receita: ReceitaExterna, mes: date, *, recebido_em: date | None = None,
            valor: Decimal | None = None) -> RecebimentoExterno:
    """Marca a receita daquele mês como recebida. O valor recebido fica no registro — é o que entrou no caixa."""
    mes = mes.replace(day=1)
    recebido_em = recebido_em or timezone.localdate()
    if not _ocorre_em(receita, mes):
        raise ValidationError("Este ganho não existe neste mês.")
    if recebido_em > timezone.localdate():
        raise ValidationError("O recebimento se marca quando acontece — a data não pode estar no futuro.")
    if RecebimentoExterno.objects.filter(receita=receita, mes=mes).exists():
        raise ValidationError("Este ganho já está marcado como recebido neste mês.")
    return RecebimentoExterno.objects.create(
        receita=receita, mes=mes, recebido_em=recebido_em, valor=valor or receita.valor)


def desfazer_recebimento(receita: ReceitaExterna, mes: date) -> None:
    """Marcou por engano: o recebimento daquele mês sai, e o ganho volta a ficar a receber."""
    recebimento = RecebimentoExterno.objects.filter(receita=receita, mes=mes.replace(day=1)).first()
    if recebimento is None:
        raise ValidationError("Este ganho não está marcado como recebido neste mês.")
    recebimento.delete()


def encerrar(receita: ReceitaExterna, ultimo_mes: date) -> ReceitaExterna:
    """O ganho mensal deixa de aparecer depois de `ultimo_mes`. O que já foi recebido fica como está."""
    if not receita.mensal:
        raise ValidationError("Só ganho mensal se encerra. O de um mês só se exclui.")
    receita.fim = ultimo_dia(ultimo_mes.year, ultimo_mes.month)
    receita.save()
    return receita


def excluir(receita: ReceitaExterna) -> None:
    """Cadastrado por engano. Com mês já recebido, recusa: histórico financeiro não some — encerra-se."""
    if receita.recebimentos.exists():
        raise ValidationError(
            "Este ganho já tem mês marcado como recebido. Para ele parar de aparecer, encerre-o; "
            "para apagá-lo, desfaça antes os recebimentos.")
    receita.delete()
