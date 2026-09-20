"""As três coisas que acontecem com uma assinatura hoje: começar o teste, ativar, e saber em que pé está."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from assinaturas.models import DIAS_DE_TESTE, Assinatura


class TesteJaUsado(Exception):
    """O teste grátis é um por conta (ADR-094)."""


def assinatura_atual() -> Assinatura | None:
    """A assinatura do psicólogo do escopo, ou `None` se ele ainda não escolheu como começar."""
    return Assinatura.objects.first()


def comecar_teste(agora=None) -> Assinatura:
    if assinatura_atual() is not None:
        raise TesteJaUsado("Esta conta já escolheu como começar.")
    agora = agora or timezone.now()
    return Assinatura.objects.create(estado=Assinatura.Estado.TESTE,
                                     teste_termina_em=agora + timedelta(days=DIAS_DE_TESTE))


def ativar(meio: str, *, id_no_gateway: str = "", agora=None) -> Assinatura:
    """O pagamento foi confirmado. Vale para quem assina de cara, no meio do teste ou depois de ele acabar.

    No cartão, "confirmado" é `PAYMENT_CONFIRMED`, não `PAYMENT_RECEIVED` (ADR-036, I-06).
    """
    assinatura = assinatura_atual() or Assinatura()
    assinatura.estado = Assinatura.Estado.ATIVA
    assinatura.ativa_desde = agora or timezone.now()
    assinatura.meio = meio
    assinatura.id_no_gateway = id_no_gateway
    assinatura.save()
    return assinatura


def pagamento_simulado() -> bool:
    """Enquanto a integração com o Asaas não existe (S-01), o pagamento é simulado — **só fora de produção**.

    `ASSINATURA_SIMULADA` nasce de `DEBUG` em `config/settings.py`, então não há `.env` que a ligue no ar: um
    botão que ativa a assinatura sem cobrar não pode existir em produção.
    """
    return bool(getattr(settings, "ASSINATURA_SIMULADA", False))
