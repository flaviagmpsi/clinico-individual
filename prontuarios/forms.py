"""Formulários do prontuário.

- `ProntuarioForm`: a tela de uma sessão — um campo de texto livre (ADR-064). Editar não pede motivo (ADR-075).
- `FolhaDoProntuarioForm`: a demanda e o encerramento do prontuário geral, preenchidos dentro da folha
  (ADR-077, ADR-079). Quem mostra a folha é o app `documentos` (ADR-080).
"""

from django import forms

from prontuarios import orientacoes


class ProntuarioForm(forms.Form):
    texto = forms.CharField(label="Registro da sessão",
                            widget=forms.Textarea(attrs={"class": "form-control", "rows": 14}))


def _na_folha(rotulo: str, ajuda: str, dica: str) -> forms.Textarea:
    return forms.Textarea(attrs={"class": "na-folha", "rows": 2, "placeholder": dica,
                                 "data-rotulo": rotulo, "data-ajuda": ajuda})


class FolhaDoProntuarioForm(forms.Form):
    """As duas partes do prontuário geral que se escrevem nele. A evolução vem dos registros de sessão (ADR-080)."""

    demanda = forms.CharField(
        label="Avaliação da demanda e objetivos do trabalho", required=False, help_text=orientacoes.AJUDA_DEMANDA,
        widget=_na_folha("Avaliação da demanda e objetivos do trabalho", orientacoes.AJUDA_DEMANDA,
                         "O que trouxe a pessoa, como você avaliou a demanda e quais são os objetivos do trabalho"))
    encerramento = forms.CharField(
        label="Encaminhamento ou encerramento", required=False, help_text=orientacoes.AJUDA_ENCERRAMENTO,
        widget=_na_folha("Encaminhamento ou encerramento", orientacoes.AJUDA_ENCERRAMENTO,
                         "Em branco enquanto o atendimento segue"))
