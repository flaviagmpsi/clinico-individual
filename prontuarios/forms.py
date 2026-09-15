"""Formulário do prontuário: um campo de texto livre (ADR-064), e o motivo quando for correção."""

from django import forms

_TEXTO = {"class": "form-control"}


class ProntuarioForm(forms.Form):
    motivo = forms.CharField(
        label="Motivo da correção", widget=forms.Textarea(attrs={**_TEXTO, "rows": 2}),
        help_text="Fica guardado junto da nova versão. A versão anterior não é apagada.")
    texto = forms.CharField(label="Registro da sessão", widget=forms.Textarea(attrs={**_TEXTO, "rows": 14}))

    def __init__(self, *args, correcao: bool, **kwargs):
        super().__init__(*args, **kwargs)
        if not correcao:
            del self.fields["motivo"]
