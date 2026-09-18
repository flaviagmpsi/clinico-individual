"""Formulários do prontuário.

- `ProntuarioForm`: a tela de uma sessão — um campo de texto livre (ADR-064). Editar não pede motivo (ADR-075).
- `FolhaDoProntuarioForm`: o prontuário inteiro do paciente, preenchido dentro da folha (ADR-077, ADR-079). Os
  campos levam a explicação do que o CFP espera ali, que a tela mostra quando o campo recebe o foco.
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
    """Demanda, encerramento e um campo de evolução por sessão realizada — `evolucao_<pk da consulta>`."""

    demanda = forms.CharField(
        label="Avaliação da demanda e objetivos do trabalho", required=False, help_text=orientacoes.AJUDA_DEMANDA,
        widget=_na_folha("Avaliação da demanda e objetivos do trabalho", orientacoes.AJUDA_DEMANDA,
                         "O que trouxe a pessoa, como você avaliou a demanda e quais são os objetivos do trabalho"))
    encerramento = forms.CharField(
        label="Encaminhamento ou encerramento", required=False, help_text=orientacoes.AJUDA_ENCERRAMENTO,
        widget=_na_folha("Encaminhamento ou encerramento", orientacoes.AJUDA_ENCERRAMENTO,
                         "Em branco enquanto o atendimento segue"))

    def __init__(self, *args, evolucao=(), **kwargs):
        super().__init__(*args, **kwargs)
        self._evolucao = list(evolucao)
        for registro in self._evolucao:
            self.fields[self._nome(registro)] = forms.CharField(
                label="Evolução", required=False,
                widget=_na_folha("Evolução do trabalho", orientacoes.AJUDA_EVOLUCAO,
                                 "Síntese da sessão e procedimentos adotados"))

    @staticmethod
    def _nome(registro) -> str:
        return f"evolucao_{registro.consulta.pk}"

    def sessoes(self) -> list:
        """Pares (registro, campo), na ordem da folha."""
        return [(registro, self[self._nome(registro)]) for registro in self._evolucao]

    def evolucoes(self) -> dict:
        return {registro.consulta.pk: self.cleaned_data.get(self._nome(registro), "") for registro in self._evolucao}
