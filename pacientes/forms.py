"""Formulário do paciente.

O `psicologo` **não** está em `fields`, e não é esquecimento: ele é `editable=False` no model e
preenchido a partir do contexto da requisição (`TenantOwnedModel.save`). Não existe campo de dono
na tela, então não existe como errar o dono — nem por engano, nem por quem inspecionar o HTML.
"""

from django import forms

from pacientes.models import Paciente

_TEXTO = {"class": "form-control"}
_NUM = {"class": "form-control", "inputmode": "numeric"}
_DATA = {"class": "form-control", "type": "date"}


class PacienteForm(forms.ModelForm):
    class Meta:
        model = Paciente
        fields = ["nome", "cpf", "data_nascimento", "telefone", "email",
                  "cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf",
                  "medicamento", "data_primeira_sessao", "observacoes"]
        widgets = {
            "nome": forms.TextInput(attrs={**_TEXTO, "autofocus": True}),
            "cpf": forms.TextInput(attrs={**_NUM, "placeholder": "só números"}),
            "data_nascimento": forms.DateInput(attrs=_DATA),
            "telefone": forms.TextInput(attrs={**_NUM, "placeholder": "31988887777"}),
            "email": forms.EmailInput(attrs=_TEXTO),
            "cep": forms.TextInput(attrs={**_NUM, "placeholder": "30140071"}),
            "logradouro": forms.TextInput(attrs=_TEXTO),
            "numero": forms.TextInput(attrs=_TEXTO),
            "complemento": forms.TextInput(attrs=_TEXTO),
            "bairro": forms.TextInput(attrs=_TEXTO),
            "cidade": forms.TextInput(attrs=_TEXTO),
            "uf": forms.Select(attrs={"class": "form-select"}),
            "medicamento": forms.Textarea(attrs={**_TEXTO, "rows": 2,
                "placeholder": "O que o paciente relata usar. Deixe vazio se não houver."}),
            "data_primeira_sessao": forms.DateInput(attrs=_DATA),
            "observacoes": forms.Textarea(attrs={**_TEXTO, "rows": 3}),
        }
        help_texts = {
            "cpf": "Opcional. Quem nasceu antes de 2018 pode não ter.",
            "medicamento": "Registro do relato do paciente — o psicólogo não prescreve.",
        }
