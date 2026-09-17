"""Formulários de conta.

Desde a P-69 os validadores do model rodam em **toda** gravação (`core.models.ValidaAoSalvar`),
não só aqui. O formulário continua sendo o lugar de validação com mensagem amigável ao usuário;
o model é a garantia de que nenhum outro caminho — shell, comando de management, view futura —
grava dado fora do formato.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from contas.models import Psicologo
from core.calendario import MAIOR_DIA_UTIL, TipoDia
from core.formularios import LimpaMascara


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


class PerfilForm(LimpaMascara, forms.ModelForm):
    CAMPOS_NUMERICOS = ("cpf", "telefone", "cnpj", "telefone_clinica", "cep")

    class Meta:
        model = Psicologo
        fields = ["nome_completo", "email", "cpf", "telefone",
                  "crp_regiao", "crp_numero", "regime", "cnpj", "razao_social", "crp_empresa",
                  "nome_clinica", "telefone_clinica", "cep", "logradouro", "numero", "complemento",
                  "bairro", "cidade", "uf",
                  "duracao_sessao", "tipo_vencimento_mensalidade", "dia_vencimento_mensalidade"]
        widgets = {
            "nome_completo": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "cpf": forms.TextInput(attrs={"class": "form-control", "placeholder": "000.000.000-00",
                                          "inputmode": "numeric", "data-mascara": "cpf"}),
            "telefone": forms.TextInput(attrs={"class": "form-control", "placeholder": "(31) 98888-7777",
                                               "inputmode": "numeric", "data-mascara": "telefone"}),
            "crp_regiao": forms.TextInput(attrs={"class": "form-control", "placeholder": "04",
                                                 "inputmode": "numeric"}),
            "crp_numero": forms.TextInput(attrs={"class": "form-control", "placeholder": "123456",
                                                 "inputmode": "numeric"}),
            "regime": forms.Select(attrs={"class": "form-select"}),
            "cnpj": forms.TextInput(attrs={"class": "form-control", "inputmode": "numeric",
                                           "data-mascara": "cnpj", "placeholder": "00.000.000/0000-00"}),
            "razao_social": forms.TextInput(attrs={"class": "form-control"}),
            "crp_empresa": forms.TextInput(attrs={"class": "form-control"}),
            "nome_clinica": forms.TextInput(attrs={"class": "form-control",
                                                   "placeholder": "Consultório da Ana Ribeiro"}),
            "telefone_clinica": forms.TextInput(attrs={"class": "form-control", "inputmode": "numeric",
                                                       "data-mascara": "telefone",
                                                       "placeholder": "(31) 3333-4444"}),
            "cep": forms.TextInput(attrs={"class": "form-control", "inputmode": "numeric",
                                          "data-mascara": "cep", "data-busca-cep": "1",
                                          "placeholder": "30140-071"}),
            "logradouro": forms.TextInput(attrs={"class": "form-control"}),
            "numero": forms.TextInput(attrs={"class": "form-control"}),
            "complemento": forms.TextInput(attrs={"class": "form-control"}),
            "bairro": forms.TextInput(attrs={"class": "form-control"}),
            "cidade": forms.TextInput(attrs={"class": "form-control"}),
            "uf": forms.Select(attrs={"class": "form-select"}),
            "duracao_sessao": forms.NumberInput(attrs={"class": "form-control", "min": 10, "max": 240,
                                                       "step": 5}),
            "tipo_vencimento_mensalidade": forms.Select(attrs={"class": "form-select"}),
            "dia_vencimento_mensalidade": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 31}),
        }

    def clean(self):
        dados = super().clean()
        # ADR-044: o CRP da empresa é opcional, mas CNPJ só faz sentido em PJ. Avisar aqui evita
        # um cadastro que parece completo e produz recibo errado lá na frente.
        if dados.get("regime") == Psicologo.Regime.PF and dados.get("cnpj"):
            self.add_error("cnpj", "Regime pessoa física não tem CNPJ. Troque o regime ou limpe o campo.")
        # O regime decide o que o sistema vai oferecer adiante — recibo de pessoa física e carnê-leão de um
        # lado, nota e contabilidade da empresa do outro. PJ sem CNPJ deixaria essa escolha no ar.
        if dados.get("regime") == Psicologo.Regime.PJ and not dados.get("cnpj"):
            self.add_error("cnpj", "Regime pessoa jurídica precisa do CNPJ.")
        dia = dados.get("dia_vencimento_mensalidade")
        if dados.get("tipo_vencimento_mensalidade") == TipoDia.DIA_UTIL and dia and dia > MAIOR_DIA_UTIL:
            self.add_error("dia_vencimento_mensalidade", f"Nenhum mês tem mais que {MAIOR_DIA_UTIL} dias úteis.")
        return dados
