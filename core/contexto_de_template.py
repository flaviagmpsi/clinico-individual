"""O que toda tela precisa saber sobre o ambiente, sem cada view ter de lembrar (ADR-114)."""

from django.conf import settings


def ambiente(request) -> dict:
    """`acesso_liberado` no contexto de todo template.

    Podia ser lido com `{% if settings.ACESSO_LIBERADO %}`, mas isso exigiria expor o módulo de configuração
    inteiro ao template — e aí qualquer chave, inclusive a da OpenAI, fica a um ponto de distância de aparecer
    numa página.
    """
    return {
        "acesso_liberado": bool(getattr(settings, "ACESSO_LIBERADO", False)),
        **aparencia(request),
    }


def aparencia(request) -> dict:
    """Tema e densidade da conta, para o `<html>` já sair do servidor com o visual certo (ADR-140).

    `tema_fixo` é o valor do atributo `data-bs-theme` quando a pessoa escolheu Claro ou Noturno; quando ela segue
    o computador (ou não está logada), fica vazio e o navegador resolve por `prefers-color-scheme` antes de pintar.
    Assim o Noturno não pisca.
    """
    usuario = getattr(request, "user", None)
    tema = "sistema"
    densidade = "confortavel"
    if usuario is not None and getattr(usuario, "is_authenticated", False):
        tema = getattr(usuario, "tema", "sistema") or "sistema"
        densidade = getattr(usuario, "densidade", "confortavel") or "confortavel"
    return {
        "tema_fixo": {"claro": "light", "noturno": "dark"}.get(tema, ""),
        "segue_o_sistema": tema == "sistema",
        "densidade": densidade,
    }
