"""Senha forte no cadastro (ADR-130).

Decisão do usuário: "quero que precise fazer uma senha mais forte na hora do cadastro, o cadastro vai pedir uma
senha com letra maiuscula, minuscula, simbolo e numeros".

Entra na lista de validadores do Django, ao lado dos que já existem (tamanho mínimo, senha comum, não só
números). Vale para **todo** lugar que valida senha: o cadastro, a troca de senha e a recuperação — porque é
onde o Django chama `validate_password`, e não num formulário só.

A mensagem lista o que **falta**, não o que a regra pede em abstrato: quem errou precisa saber o que acrescentar,
não reler o enunciado.
"""

import re

from django.core.exceptions import ValidationError

# Símbolo é "qualquer coisa que não seja letra nem número" — pontuação, acento solto, espaço. Mais largo que uma
# lista fixa de propósito: o objetivo é variedade, e brigar com o usuário sobre quais símbolos valem não ajuda.
_TEM_MAIUSCULA = re.compile(r"[A-ZÀ-Þ]")
_TEM_MINUSCULA = re.compile(r"[a-zß-ÿ]")
_TEM_NUMERO = re.compile(r"\d")
_TEM_SIMBOLO = re.compile(r"[^0-9A-Za-zÀ-ÿ]")


class SenhaForteValidator:
    """Exige letra maiúscula, letra minúscula, número e símbolo."""

    def validate(self, password, user=None):
        faltam = []
        if not _TEM_MAIUSCULA.search(password):
            faltam.append("uma letra maiúscula")
        if not _TEM_MINUSCULA.search(password):
            faltam.append("uma letra minúscula")
        if not _TEM_NUMERO.search(password):
            faltam.append("um número")
        if not _TEM_SIMBOLO.search(password):
            faltam.append("um símbolo (como ! ? @ # -)")
        if faltam:
            raise ValidationError(
                "A senha precisa de " + self._lista(faltam) + ".",
                code="senha_fraca",
            )

    def get_help_text(self):
        return "Use letras maiúsculas e minúsculas, números e ao menos um símbolo (como ! ? @ # -)."

    @staticmethod
    def _lista(itens: list[str]) -> str:
        """"a, b e c" — a vírgula de sempre, o "e" antes do último."""
        if len(itens) == 1:
            return itens[0]
        return ", ".join(itens[:-1]) + " e " + itens[-1]
