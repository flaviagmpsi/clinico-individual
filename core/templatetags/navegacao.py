"""O caminho no topo da tela (ADR-088): a seção é um link para a raiz dela.

Cada app tem uma tela raiz — a lista, a agenda, o mês. Saber onde ela fica é coisa de navegação, não de domínio,
por isso mora em `core` e é resolvido pelo nome do app, sem importar nada dele.
"""

from django import template
from django.urls import NoReverseMatch, reverse

register = template.Library()

RAIZES = {
    "pacientes": "pacientes:lista",
    "atendimentos": "atendimentos:agenda",
    "agenda": "agenda:horarios",
    "prontuarios": "prontuarios:lista",
    "financeiro": "financeiro:mes",
    "documentos": "documentos:aba",
    "contas": "contas:perfil",
}
RAIZES_POR_NOME = {"painel": "painel", "estatisticas": "estatisticas"}


@register.simple_tag
def raiz_da_secao(request) -> str:
    """A URL da tela raiz da seção em que a requisição está; vazio quando não há seção (login, tela pública)."""
    rota = getattr(request, "resolver_match", None)
    if rota is None:
        return ""
    nome = RAIZES_POR_NOME.get(rota.url_name) or RAIZES.get(rota.app_name)
    try:
        return reverse(nome) if nome else ""
    except NoReverseMatch:
        return ""
