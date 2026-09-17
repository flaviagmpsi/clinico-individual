"""Máscara é coisa de tela; o banco guarda número puro.

O usuário digita `529.982.247-25` e `1.200,00`; o model exige `52998224725` e `1200.00`. A limpeza
acontece **antes** da validação do campo, e não em `clean_<campo>`: o `max_length=11` do CPF roda no
`_clean_fields`, antes de qualquer `clean_` nosso, e recusaria a máscara como "longo demais".

Por isso o mixin reescreve `self.data` no `__init__`. É a única etapa anterior à validação onde o
formulário ainda pode mexer no que chegou do navegador.
"""

import re

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            return
        dados = self.data.copy()
        for campo, limpar in [(c, apenas_digitos) for c in self.CAMPOS_NUMERICOS] + \
                             [(c, decimal_brasileiro) for c in self.CAMPOS_DECIMAIS]:
            chave = self.add_prefix(campo)
            if chave in dados:
                dados[chave] = limpar(dados[chave])
        self.data = dados
