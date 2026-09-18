"""O que a ficha do paciente mostra e que vem de outros apps: frequência e situação financeira (ADR-084).

A ficha é do app `pacientes`, de quem `atendimentos` e `financeiro` dependem — ela não pode importá-los sem fechar um
ciclo (regra 5). `indicadores` depende de todos e ninguém depende dele (regra 2): é daqui que a ficha recebe esses
números, por template tag. Só leitura, como tudo neste app.
"""

from decimal import Decimal

from django import template

from financeiro.servicos import pagamentos_pendentes
from indicadores.estatisticas import presenca_do_paciente

register = template.Library()


@register.simple_tag
def frequencia_do_paciente(paciente):
    """`Presenca` com presentes, faltas, canceladas e remarcadas de todas as sessões do paciente."""
    return presenca_do_paciente(paciente)


@register.simple_tag
def situacao_financeira(caso):
    """Em dia, com pendência ou sem cobrança combinada. Pendência é o que venceu e não foi quitado (N-08)."""
    if caso is None:
        return {"estado": "sem_cobranca", "pendentes": [], "total": Decimal("0")}
    pendentes = pagamentos_pendentes(caso=caso)
    if pendentes:
        return {"estado": "pendente", "pendentes": pendentes, "total": sum((c.saldo for c in pendentes), Decimal("0"))}
    combinou = caso.condicoes.exists() or caso.pagamentos.exists()
    return {"estado": "em_dia" if combinou else "sem_cobranca", "pendentes": [], "total": Decimal("0")}
