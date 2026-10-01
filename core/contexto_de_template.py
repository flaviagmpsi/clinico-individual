"""O que toda tela precisa saber sobre o ambiente, sem cada view ter de lembrar (ADR-114)."""

from django.conf import settings


def ambiente(request) -> dict:
    """`acesso_liberado` no contexto de todo template.

    Podia ser lido com `{% if settings.ACESSO_LIBERADO %}`, mas isso exigiria expor o módulo de configuração
    inteiro ao template — e aí qualquer chave, inclusive a da OpenAI, fica a um ponto de distância de aparecer
    numa página.
    """
    return {"acesso_liberado": bool(getattr(settings, "ACESSO_LIBERADO", False))}
