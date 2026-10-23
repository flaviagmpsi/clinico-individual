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
        **desfazer(request),
    }


def desfazer(request) -> dict:
    """O aviso flutuante com "Desfazer" (ADR-140). A ação de cadastro guarda na sessão o que dá para desfazer; a
    primeira tela renderizada depois mostra e **consome** — some sozinho e não volta num refresh posterior."""
    import time

    sessao = getattr(request, "session", None)
    dado = sessao.get("desfazer") if sessao is not None else None
    if not dado:
        return {"desfazer": None}
    sessao.pop("desfazer", None)
    if dado.get("ate", 0) < time.time():
        return {"desfazer": None}
    return {"desfazer": {"url": dado.get("url", ""), "texto": dado.get("texto", "")}}


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
