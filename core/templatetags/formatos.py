"""Formatação de exibição que o domínio guarda sem máscara.

CPF, CNPJ e telefone são gravados só com dígitos (a máscara é da tela, `core/formularios.py` a remove antes de
validar). Para mostrar na ficha e em listas com a mesma cara dos documentos, formatamos aqui, na apresentação —
nunca no banco. Entrada que não tem o tamanho esperado volta como veio, para não esconder dado estranho.
"""

from django import template

register = template.Library()


@register.filter
def cpf(valor: str) -> str:
    v = (valor or "").strip()
    return f"{v[:3]}.{v[3:6]}.{v[6:9]}-{v[9:]}" if len(v) == 11 and v.isdigit() else v


@register.filter
def cnpj(valor: str) -> str:
    v = (valor or "").strip()
    return f"{v[:2]}.{v[2:5]}.{v[5:8]}/{v[8:12]}-{v[12:]}" if len(v) == 14 and v.isdigit() else v
