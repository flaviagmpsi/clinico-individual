"""Formulários de conta.

Desde a P-69 os validadores do model rodam em **toda** gravação (`core.models.ValidaAoSalvar`),
não só aqui. O formulário continua sendo o lugar de validação com mensagem amigável ao usuário;
o model é a garantia de que nenhum outro caminho — shell, comando de management, view futura —
grava dado fora do formato.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, BaseUserCreationForm

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
                  "crp_regiao", "crp_numero", "abordagem", "abordagem_outra",
                  "atende_online", "atende_presencial",
                  "regime", "cnpj", "razao_social", "crp_empresa",
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
            "abordagem": forms.Select(attrs={"class": "form-select"}),
            "abordagem_outra": forms.TextInput(attrs={"class": "form-control", "placeholder": "Qual?"}),
            "atende_online": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "atende_presencial": forms.CheckboxInput(attrs={"class": "form-check-input"}),
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
        if dados.get("abordagem") == Psicologo.Abordagem.OUTRA and not dados.get("abordagem_outra"):
            self.add_error("abordagem_outra", "Diga qual é a abordagem.")
        dia = dados.get("dia_vencimento_mensalidade")
        if dados.get("tipo_vencimento_mensalidade") == TipoDia.DIA_UTIL and dia and dia > MAIOR_DIA_UTIL:
            self.add_error("dia_vencimento_mensalidade", f"Nenhum mês tem mais que {MAIOR_DIA_UTIL} dias úteis.")
        return dados


_CONTROLE = {"class": "form-control"}
_NUMERO = {"class": "form-control", "inputmode": "numeric"}
_ESCOLHA = {"class": "form-select"}
_MARCA = {"class": "form-check-input"}


class CriarContaForm(LimpaMascara, BaseUserCreationForm):
    """Passo 1 do quiz (C-10): o mínimo para a conta **existir** — e o model exige tudo isto.

    Não é uma escolha de produto pedir CPF e CRP já na criação: `Psicologo` os tem como obrigatórios desde a
    ADR-044, e uma conta sem eles não passaria pela validação que roda em toda gravação (P-69).
    """

    CAMPOS_NUMERICOS = ("cpf", "telefone")

    class Meta(BaseUserCreationForm.Meta):
        model = Psicologo
        fields = ["nome_completo", "email", "cpf", "telefone", "crp_regiao", "crp_numero"]
        field_classes = {}
        widgets = {
            "nome_completo": forms.TextInput(attrs={**_CONTROLE, "autofocus": True}),
            "email": forms.EmailInput(attrs={**_CONTROLE, "placeholder": "voce@exemplo.com"}),
            "cpf": forms.TextInput(attrs={**_NUMERO, "data-mascara": "cpf", "placeholder": "000.000.000-00"}),
            "telefone": forms.TextInput(attrs={**_NUMERO, "data-mascara": "telefone",
                                               "placeholder": "(31) 98888-7777"}),
            "crp_regiao": forms.TextInput(attrs={**_NUMERO, "placeholder": "04"}),
            "crp_numero": forms.TextInput(attrs={**_NUMERO, "placeholder": "123456"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ["password1", "password2"]:
            self.fields[campo].widget.attrs.update({"class": "form-control"})


class RegimeForm(LimpaMascara, forms.ModelForm):
    """Passo 2: como o psicólogo atende do ponto de vista fiscal (ADR-067)."""

    CAMPOS_NUMERICOS = ("cnpj",)

    class Meta:
        model = Psicologo
        fields = ["regime", "cnpj", "razao_social"]
        widgets = {
            "regime": forms.RadioSelect(attrs=_MARCA),
            "cnpj": forms.TextInput(attrs={**_NUMERO, "data-mascara": "cnpj",
                                           "placeholder": "00.000.000/0000-00"}),
            "razao_social": forms.TextInput(attrs=_CONTROLE),
        }

    def clean(self):
        dados = super().clean()
        if dados.get("regime") == Psicologo.Regime.PJ and not dados.get("cnpj"):
            self.add_error("cnpj", "Regime pessoa jurídica precisa do CNPJ.")
        if dados.get("regime") == Psicologo.Regime.PF and dados.get("cnpj"):
            self.add_error("cnpj", "Regime pessoa física não tem CNPJ. Troque o regime ou limpe o campo.")
        return dados


class ComoAtendeForm(forms.ModelForm):
    """Passo 3: abordagem e formas de atendimento (ADR-071)."""

    class Meta:
        model = Psicologo
        fields = ["abordagem", "abordagem_outra", "atende_online", "atende_presencial"]
        widgets = {
            "abordagem": forms.Select(attrs=_ESCOLHA),
            "abordagem_outra": forms.TextInput(attrs={**_CONTROLE, "placeholder": "Qual?"}),
            "atende_online": forms.CheckboxInput(attrs=_MARCA),
            "atende_presencial": forms.CheckboxInput(attrs=_MARCA),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["abordagem"].required = True
        self.fields["abordagem"].choices = [("", "Escolha")] + list(Psicologo.Abordagem.choices)

    def clean(self):
        dados = super().clean()
        if dados.get("abordagem") == Psicologo.Abordagem.OUTRA and not dados.get("abordagem_outra"):
            self.add_error("abordagem_outra", "Diga qual é a abordagem.")
        if not dados.get("atende_online") and not dados.get("atende_presencial"):
            self.add_error("atende_presencial", "Marque pelo menos uma forma de atendimento.")
        return dados


class ClinicaForm(LimpaMascara, forms.ModelForm):
    """Passo 4: onde atende. O endereço só é obrigatório para quem atende presencialmente."""

    CAMPOS_NUMERICOS = ("telefone_clinica", "cep")

    class Meta:
        model = Psicologo
        fields = ["nome_clinica", "telefone_clinica", "cep", "logradouro", "numero", "complemento",
                  "bairro", "cidade", "uf"]
        widgets = {
            "nome_clinica": forms.TextInput(attrs={**_CONTROLE, "placeholder": "Consultório da Ana Ribeiro"}),
            "telefone_clinica": forms.TextInput(attrs={**_NUMERO, "data-mascara": "telefone",
                                                       "placeholder": "(31) 3333-4444"}),
            "cep": forms.TextInput(attrs={**_NUMERO, "data-mascara": "cep", "data-busca-cep": "1",
                                          "placeholder": "30140-071"}),
            "logradouro": forms.TextInput(attrs=_CONTROLE),
            "numero": forms.TextInput(attrs=_CONTROLE),
            "complemento": forms.TextInput(attrs=_CONTROLE),
            "bairro": forms.TextInput(attrs=_CONTROLE),
            "cidade": forms.TextInput(attrs=_CONTROLE),
            "uf": forms.Select(attrs=_ESCOLHA),
        }

    def clean(self):
        dados = super().clean()
        # Quem atende só online não tem endereço de consultório para dar, e travar o cadastro nele seria
        # inventar uma exigência que a profissão não faz.
        if self.instance.atende_presencial:
            for campo in ["cep", "logradouro", "numero", "bairro", "cidade", "uf"]:
                if not dados.get(campo):
                    self.add_error(campo, "Quem atende presencialmente precisa informar o endereço.")
        return dados
