"""O que cada paciente deve, o que pagou e o que está pendente (ADR-062, ADR-063).

**O devido é cálculo, não registro.** A mensalidade vem da condição de cobrança do mês; a sessão, da consulta
cobrada e do valor por sessão vigente na data dela. Só o pagamento é gravado — pelo psicólogo, sempre.

**Três situações, não duas** (rodada 80): uma cobrança **existe** a partir de `desde` — o dia 1º, para a
mensalidade; o dia da sessão, para a sessão. Dali até o vencimento ela está **a receber**; passado o
vencimento e sem o pago cobrir o devido, está **vencida**, e é alerta (N-08). Paga antes do vencimento, nunca
chega a vencer.
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

    @property
    def desde(self) -> date:
        """A partir de quando esta cobrança **existe** para o psicólogo — e não de quando ela vence.

        Decisão do usuário (rodada 80): a mensalidade de outubro já é um pagamento a receber no dia 1º, porque
        o paciente tem o mês inteiro para pagá-la até o vencimento. Antes disso ela não existe: não se cobra em
        setembro o mês que não começou. A sessão nasce no dia em que acontece, que é o próprio vencimento dela
        (ADR-063) — por isso sessão nunca aparece como "a receber", só como vencida.
        """
        return self.mes if self.tipo == MENSALIDADE else self.vencimento

    def em_aberto(self, hoje: date | None = None) -> bool:
        """Já existe, e o pago não cobre o devido. É a soma de "a receber" e "vencida"."""
        return not self.quitada and self.desde <= (hoje or timezone.localdate())

    def pendente(self, hoje: date | None = None) -> bool:
        """**Venceu** e o pago não cobre o devido. Pago antes do vencimento, nunca fica pendente.

        É o alerta: o nome ficou como estava porque é isto que todas as telas chamam de pendente.
        """
        return not self.quitada and self.vencimento <= (hoje or timezone.localdate())

    def a_receber(self, hoje: date | None = None) -> bool:
        """Existe, não foi paga e **ainda não venceu** — o que o psicólogo espera receber, sem susto."""
        hoje = hoje or timezone.localdate()
        return self.em_aberto(hoje) and self.vencimento > hoje

    def dias_de_atraso(self, hoje: date | None = None) -> int:
        """Quantos dias passaram do vencimento. Zero quando não venceu — a tela usa para graduar o alerta."""
        return max((hoje or timezone.localdate()) - self.vencimento, timedelta(0)).days

    def dias_para_vencer(self, hoje: date | None = None) -> int:
        return max(self.vencimento - (hoje or timezone.localdate()), timedelta(0)).days

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


@dataclass
class Carga:
    """Tudo o que o financeiro precisa de um período, lido de uma vez (ADR-086).

    O devido é cálculo (ADR-062), e o cálculo percorre casos, condições, desfechos, consultas e pagamentos. Feito
    cobrança a cobrança, cada uma ia ao banco: com alguns meses de uso, o painel passava de duzentas consultas.
    Aqui são meia dúzia, qualquer que seja o tamanho do período.
    """

    casos: list
    consultas: list
    mensais: dict  # (caso_id, primeiro dia do mês) -> pagamentos daquela mensalidade

    def caso(self, pk: int):
        return next((caso for caso in self.casos if caso.pk == pk), None)


def carregar(de: date, ate: date, *, caso: Caso | None = None) -> Carga:
    casos = Caso.objects.prefetch_related("pacientes", "desfechos", "condicoes", "recorrencias")
    casos = list(casos.filter(pk=caso.pk) if caso is not None else casos)
    por_id = {item.pk: item for item in casos}
    consultas = (
        Consulta.objects.filter(cobrada=True, inicio__gte=_meia_noite(de),
                                inicio__lt=_meia_noite(ate + timedelta(days=1)))
        .prefetch_related("pagamentos")
    )
    consultas = list(consultas.filter(caso=caso) if caso is not None else consultas)
    for consulta in consultas:
        # O mesmo objeto de caso para todas as consultas dele: é nele que as condições já estão carregadas.
        if consulta.caso_id in por_id:
            consulta.caso = por_id[consulta.caso_id]
    mensais: dict = {}
    pagamentos = Pagamento.objects.filter(mes_referencia__gte=de.replace(day=1), mes_referencia__lte=ate)
    for pagamento in (pagamentos.filter(caso=caso) if caso is not None else pagamentos):
        mensais.setdefault((pagamento.caso_id, pagamento.mes_referencia), []).append(pagamento)
    return Carga(casos=casos, consultas=consultas, mensais=mensais)


def mensalidade(caso: Caso, ano: int, mes: int, *, carga: Carga | None = None) -> Cobranca | None:
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
    pagamentos = (carga.mensais.get((caso.pk, inicio), []) if carga is not None
                  else list(Pagamento.objects.filter(caso=caso, mes_referencia=inicio)))
    return Cobranca(caso=caso, tipo=MENSALIDADE, vencimento=condicao.vencimento_em(ano, mes), devido=condicao.valor,
                    pagamentos=pagamentos, mes=inicio)


def sessao(consulta: Consulta) -> Cobranca | None:
    """O pagamento pendente de uma sessão cobrada. Vence no dia dela (ADR-063).

    O valor sai de um de dois lugares: o **desta** sessão, quando o psicólogo o digitou (ADR-070) — é a sessão
    extra de quem paga mensalidade, ou a de quem ainda não tem valor combinado —, ou a condição por sessão
    vigente na data. Quem paga mensalidade e não digitou valor não gera cobrança de sessão: já está na mensalidade.
    """
    if not consulta.cobrada:
        return None
    dia = timezone.localtime(consulta.inicio).date()
    devido = consulta.valor
    if devido is None:
        condicao = consulta.caso.condicao_vigente(dia)
        if condicao is None or condicao.modalidade != CondicaoCobranca.Modalidade.POR_SESSAO:
            return None
        devido = condicao.valor
    return Cobranca(caso=consulta.caso, tipo=SESSAO, vencimento=dia, devido=devido,
                    pagamentos=list(consulta.pagamentos.all()), consulta=consulta)


def _do_periodo(carga: Carga, de: date, ate: date) -> list:
    return [consulta for consulta in carga.consultas if de <= timezone.localtime(consulta.inicio).date() <= ate]


def cobrancas_do_mes(ano: int, mes: int, *, caso: Caso | None = None, carga: Carga | None = None) -> list[Cobranca]:
    """Mensalidades do mês e sessões cobradas no mês, de quem paga por sessão.

    Quem vai pedir vários meses — o fluxo do ano — traz a `carga` pronta e a reaproveita.
    """
    inicio, fim = date(ano, mes, 1), ultimo_dia(ano, mes)
    carga = carga or carregar(inicio, fim, caso=caso)
    cobrancas = [c for c in (mensalidade(item, ano, mes, carga=carga) for item in carga.casos) if c]
    cobrancas += [c for c in (sessao(consulta) for consulta in _do_periodo(carga, inicio, fim)) if c]
    return sorted(cobrancas, key=lambda c: (c.vencimento, str(c.caso)))


def cobrancas_em_aberto(hoje: date | None = None, *, caso: Caso | None = None) -> list[Cobranca]:
    """Tudo o que existe e não foi quitado, de qualquer mês: o que vai vencer **e** o que já venceu.

    Os dois juntos porque custam a mesma carga: separá-los em duas funções leria o banco duas vezes para
    responder a mesma pergunta. Quem quer só um lado filtra por `pendente()` ou `a_receber()`.
    """
    hoje = hoje or timezone.localdate()
    carga = carregar(_DESDE_SEMPRE, hoje, caso=caso)
    abertas = []
    for item in carga.casos:
        mensais = [c for c in item.condicoes.all() if c.modalidade == CondicaoCobranca.Modalidade.MENSAL]
        if not mensais:
            continue
        primeira = min(condicao.vigente_desde for condicao in mensais)
        mes = date(primeira.year, primeira.month, 1)
        # Até o mês corrente, inclusive: a mensalidade dele já existe no dia 1º, mesmo que vença depois.
        while mes <= hoje:
            cobranca = mensalidade(item, mes.year, mes.month, carga=carga)
            if cobranca and cobranca.em_aberto(hoje):
                abertas.append(cobranca)
            mes = mes_seguinte(mes)
    for consulta in carga.consultas:
        cobranca = sessao(consulta)
        if cobranca and cobranca.em_aberto(hoje):
            abertas.append(cobranca)
    return sorted(abertas, key=lambda c: (c.vencimento, str(c.caso)))


def pagamentos_pendentes(hoje: date | None = None, *, caso: Caso | None = None) -> list[Cobranca]:
    """Só o que **venceu** e não foi quitado — o alerta."""
    hoje = hoje or timezone.localdate()
    return [c for c in cobrancas_em_aberto(hoje, caso=caso) if c.pendente(hoje)]


def pagamentos_a_receber(hoje: date | None = None, *, caso: Caso | None = None) -> list[Cobranca]:
    """Só o que existe e **ainda não venceu** — o que está por receber, em ordem de vencimento."""
    hoje = hoje or timezone.localdate()
    return [c for c in cobrancas_em_aberto(hoje, caso=caso) if c.a_receber(hoje)]


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
