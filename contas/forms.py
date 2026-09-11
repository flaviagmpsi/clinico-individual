"""Formulários de conta. Aqui é onde os validadores do model finalmente rodam.

Enquanto o `full_clean()` no `save()` não for decidido (P-69), o `ModelForm` é o **único** lugar
que aplica os `RegexValidator` de CPF, telefone e CRP. Por isso todo caminho de entrada de dado
do produto passa por um formulário — não por conveniência, por ser a validação que existe.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from contas.models import Psicologo


class LoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={"class": "form-control", "autofocus": True,
                                       "placeholder": "voce@exemplo.com"}),
    )
    password = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "••••••••"}),
    )


class PerfilForm(forms.ModelForm):
    class Meta:
        model = Psicologo
        fields = ["nome_completo", "email", "cpf", "telefone",
                  "crp_regiao", "crp_numero", "regime", "cnpj", "crp_empresa"]
        widgets = {
            "nome_completo": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "cpf": forms.TextInput(attrs={"class": "form-control", "placeholder": "00000000000",
                                          "inputmode": "numeric"}),
            "telefone": forms.TextInput(attrs={"class": "form-control", "placeholder": "31988887777",
                                               "inputmode": "numeric"}),
            "crp_regiao": forms.TextInput(attrs={"class": "form-control", "placeholder": "04",
                                                 "inputmode": "numeric"}),
            "crp_numero": forms.TextInput(attrs={"class": "form-control", "placeholder": "123456",
                                                 "inputmode": "numeric"}),
            "regime": forms.Select(attrs={"class": "form-select"}),
            "cnpj": forms.TextInput(attrs={"class": "form-control", "inputmode": "numeric"}),
            "crp_empresa": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean(self):
        dados = super().clean()
        # ADR-044: o CRP da empresa é opcional, mas CNPJ só faz sentido em PJ. Avisar aqui evita
        # um cadastro que parece completo e produz recibo errado lá na frente.
        if dados.get("regime") == Psicologo.Regime.PF and dados.get("cnpj"):
            self.add_error("cnpj", "Regime pessoa física não tem CNPJ. Troque o regime ou limpe o campo.")
        return dados
