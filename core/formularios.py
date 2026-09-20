"""Máscara é coisa de tela; o banco guarda número puro.

O usuário digita `529.982.247-25` e `1.200,00`; o model exige `52998224725` e `1200.00`. A limpeza
acontece **antes** da validação do campo, e não em `clean_<campo>`: o `max_length=11` do CPF roda no
`_clean_fields`, antes de qualquer `clean_` nosso, e recusaria a máscara como "longo demais".

Por isso o mixin reescreve `self.data` no `__init__`. É a única etapa anterior à validação onde o
formulário ainda pode mexer no que chegou do navegador.
"""

import re

from django import forms
from django.core.exceptions import ValidationError

_NAO_DIGITO = re.compile(r"\D")


def apenas_digitos(valor: str) -> str:
    return _NAO_DIGITO.sub("", valor or "")


def decimal_brasileiro(valor: str) -> str:
    """`1.200,50` → `1200.50`. Deixa passar o que já está no formato do Python."""
    valor = (valor or "").strip()
    if "," not in valor:
        return valor
    return valor.replace(".", "").replace(",", ".")


class LimpaMascara:
    """Tira a máscara dos campos listados antes de validar.

    `CAMPOS_NUMERICOS` guardam só dígitos (CPF, CNPJ, telefone, CEP); `CAMPOS_DECIMAIS` são valores em
    reais, que chegam com ponto de milhar e vírgula decimal.
    """

    CAMPOS_NUMERICOS: tuple[str, ...] = ()
    CAMPOS_DECIMAIS: tuple[str, ...] = ()

    def campos_numericos(self) -> tuple[str, ...]:
        """Quem precisa decidir pelo que chegou — o CEP de fora do Brasil tem letra — sobrescreve isto."""
        return self.CAMPOS_NUMERICOS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            return
        dados = self.data.copy()
        for campo, limpar in [(c, apenas_digitos) for c in self.campos_numericos()] + \
                             [(c, decimal_brasileiro) for c in self.CAMPOS_DECIMAIS]:
            chave = self.add_prefix(campo)
            if chave in dados:
                dados[chave] = limpar(dados[chave])
        self.data = dados


class _VariasCaixas(forms.Widget):
    """Várias caixas de texto com o mesmo nome. O desenho é de `components/_lista_de_textos.html`."""

    def value_from_datadict(self, data, files, name):
        return data.getlist(name) if hasattr(data, "getlist") else data.get(name) or []

    def format_value(self, value):
        return list(value or [])


class ListaDeTextos(forms.Field):
    """Uma lista curta de textos **escritos à mão**, um por caixa — sem lista pronta para escolher.

    Guarda numa coluna JSON. Tira espaço sobrando, caixa vazia e repetição (sem olhar maiúscula), e mantém a
    ordem em que a pessoa escreveu. Renderize com `components/_lista_de_textos.html`.
    """

    widget = _VariasCaixas

    def __init__(self, *, maximo=8, tamanho=120, **kwargs):
        self.maximo, self.tamanho = maximo, tamanho
        super().__init__(**kwargs)

    def to_python(self, value):
        vistos, itens = set(), []
        for bruto in value or []:
            texto = " ".join(str(bruto).split())
            if texto and texto.casefold() not in vistos:
                vistos.add(texto.casefold())
                itens.append(texto)
        return itens

    def validate(self, value):
        super().validate(value)
        if len(value) > self.maximo:
            raise ValidationError(f"No máximo {self.maximo} itens.")
        if any(len(item) > self.tamanho for item in value):
            raise ValidationError(f"Cada item tem no máximo {self.tamanho} letras.")
