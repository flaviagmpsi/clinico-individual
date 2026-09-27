"""Formulários do prontuário.

- `ProntuarioForm`: a tela de uma sessão — um campo de texto livre (ADR-064). Editar não pede motivo (ADR-075).
- `FolhaDoProntuarioForm`: a demanda e o encerramento do prontuário geral, preenchidos dentro da folha
  (ADR-077, ADR-079). Quem mostra a folha é o app `documentos` (ADR-080).
"""

from django import forms

from prontuarios import orientacoes
from prontuarios.models import Anamnese


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


# O que se espera em cada tema — dito em uma linha, embaixo do campo. São sugestões de roteiro, não exigências.
class AnamneseForm(forms.Form):
    """Um campo de texto por bloco do roteiro (ADR-101). Os blocos vêm do psicólogo, não daqui."""

    def __init__(self, *args, blocos, **kwargs):
        super().__init__(*args, **kwargs)
        self.blocos = blocos
        for tema, resposta in blocos:
            self.fields[f"tema_{tema.pk}"] = forms.CharField(
                label=tema.titulo, required=False, help_text=tema.ajuda,
                initial=resposta.texto if resposta else "",
                widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))

    def campos_dos_blocos(self):
        """(tema, campo) na ordem do roteiro — é assim que a tela desenha, sem adivinhar nome de campo."""
        return [(tema, self[f"tema_{tema.pk}"]) for tema, _ in self.blocos]

    def textos(self) -> dict[int, str]:
        return {tema.pk: self.cleaned_data.get(f"tema_{tema.pk}", "") for tema, _ in self.blocos}

    def tem_conteudo(self) -> bool:
        return any((texto or "").strip() for texto in self.textos().values())


class TemaDeAnamneseForm(forms.Form):
    """O bloco novo que o psicólogo acrescenta ao roteiro dele."""

    titulo = forms.CharField(
        label="Novo tema", max_length=120,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex.: rede de apoio na comunidade"}))
    ajuda = forms.CharField(
        label="O que anotar aqui", max_length=255, required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Opcional — a nota que aparece sob o campo"}))

