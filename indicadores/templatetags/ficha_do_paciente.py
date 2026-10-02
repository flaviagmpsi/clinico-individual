"""O que a ficha do paciente mostra e que vem de outros apps: frequência e situação financeira (ADR-084).

A ficha é do app `pacientes`, de quem `atendimentos` e `financeiro` dependem — ela não pode importá-los sem fechar um
ciclo (regra 5). `indicadores` depende de todos e ninguém depende dele (regra 2): é daqui que a ficha recebe esses
números, por template tag. Só leitura, como tudo neste app.
"""

from decimal import Decimal

from django import template

from financeiro.servicos import cobrancas_em_aberto
from indicadores.estatisticas import presenca_do_paciente

register = template.Library()


@register.simple_tag
def frequencia_do_paciente(paciente):
    """`Presenca` com presentes, faltas, canceladas e remarcadas de todas as sessões do paciente."""
    return presenca_do_paciente(paciente)


def _soma(cobrancas) -> Decimal:
    return sum((c.saldo for c in cobrancas), Decimal("0"))


@register.simple_tag
def situacao_financeira(caso):
    """Vencido, a receber, em dia ou sem cobrança combinada.

    Quatro estados, e não dois (rodada 80): o que venceu e não entrou é alerta; o que existe e ainda tem prazo
    — a mensalidade do mês corrente, desde o dia 1º — é informação. Quem tem os dois é "vencido", porque o
    atraso é o que pede ação. Uma leitura só do banco para as duas listas.
    """
    vazio = {"estado": "sem_cobranca", "pendentes": [], "a_receber": [],
             "total": Decimal("0"), "total_a_receber": Decimal("0")}
    if caso is None:
        return vazio
    abertas = cobrancas_em_aberto(caso=caso)
    vencidas = [c for c in abertas if c.pendente()]
    a_receber = [c for c in abertas if c.a_receber()]
    if vencidas or a_receber:
        return {"estado": "pendente" if vencidas else "a_receber",
                "pendentes": vencidas, "a_receber": a_receber,
                "total": _soma(vencidas), "total_a_receber": _soma(a_receber)}
    combinou = caso.condicoes.exists() or caso.pagamentos.exists()
    return {**vazio, "estado": "em_dia" if combinou else "sem_cobranca"}
