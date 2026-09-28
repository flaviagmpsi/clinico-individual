"""Formulários de conta.

Desde a P-69 os validadores do model rodam em **toda** gravação (`core.models.ValidaAoSalvar`),
não só aqui. O formulário continua sendo o lugar de validação com mensagem amigável ao usuário;
o model é a garantia de que nenhum outro caminho — shell, comando de management, view futura —
grava dado fora do formato.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, BaseUserCreationForm

from contas import abordagens as catalogo
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


_AJUDA_ABORDAGENS = "Marque quantas quiser. Não achou a sua? Marque “Outra” e escreva."
_AJUDA_AREAS = "O que você faz além da clínica. Deixe em branco se atende só no consultório."


class _Catalogo(forms.MultipleChoiceField):
    """Escolha múltipla num catálogo fechado, guardada como lista de códigos (ADR-107).

    A classe vai no widget, e não no template: sem ela o navegador desenha a caixa nativa — azul, fora da paleta,
    e sem o recuo que põe o rótulo ao lado dela.
    """

    def __init__(self, catalogo, **kwargs):
        kwargs.setdefault("widget", forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}))
        super().__init__(choices=catalogo, **kwargs)


class EscolhasComOutra:
    """Liga cada catálogo ao seu campo de texto: marcou “Outra”, escreve; desmarcou, o texto some.

    O texto não é limpo só na tela — se ficasse gravado com a opção desmarcada, `abordagem_descrita` continuaria
    mostrando algo que a pessoa tirou, e a contagem por OUTRA acusaria gente que não marcou OUTRA.
    """

    CATALOGOS: dict[str, str] = {}   # {campo da lista: campo de texto}

    def clean(self):
        dados = super().clean()
        for lista, escrito in self.CATALOGOS.items():
            escolhidos = dados.get(lista) or []
            texto = (dados.get(escrito) or "").strip()
            if catalogo.OUTRA in escolhidos:
                if not texto:
                    self.add_error(escrito, "Escreva qual, ou desmarque “Outra”.")
            elif texto:
                dados[escrito] = ""
        return dados


class _QuemEVoce:
    """Nome, CPF e telefone são vazios no banco até o quiz (ADR-094) — e obrigatórios em toda tela que os grava."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ("nome_completo", "cpf", "telefone"):
            self.fields[campo].required = True

    # CPF repetido **não** se confere aqui: dentro do sistema o RLS esconde as outras contas (ADR-046), e a consulta
    # responderia sempre "não existe". Quem recusa é a coluna única; a view traduz a recusa (`GravaSemRepetir`).


class PerfilForm(EscolhasComOutra, _QuemEVoce, LimpaMascara, forms.ModelForm):
    CAMPOS_NUMERICOS = ("cpf", "telefone", "cnpj", "telefone_clinica", "cep")
    CATALOGOS = {"abordagens": "abordagem_outra", "outras_areas": "area_outra"}

    abordagens = _Catalogo(catalogo.ABORDAGENS, label="Abordagens", required=False,
                           help_text=_AJUDA_ABORDAGENS)
    outras_areas = _Catalogo(catalogo.AREAS, label="Outras áreas de atuação", required=False,
                             help_text=_AJUDA_AREAS)

    class Meta:
        model = Psicologo
        fields = ["nome_completo", "email", "cpf", "telefone",
                  "crp_regiao", "crp_numero",
                  "abordagens", "abordagem_outra", "outras_areas", "area_outra",
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
            "abordagem_outra": forms.TextInput(attrs={"class": "form-control form-control-sm",
                                                      "placeholder": "Escreva qual"}),
            "area_outra": forms.TextInput(attrs={"class": "form-control form-control-sm",
                                                 "placeholder": "Escreva qual"}),
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
        if not dados.get("atende_online") and not dados.get("atende_presencial"):
            self.add_error("atende_presencial", "Marque pelo menos uma forma de atendimento.")
        dia = dados.get("dia_vencimento_mensalidade")
        if dados.get("tipo_vencimento_mensalidade") == TipoDia.DIA_UTIL and dia and dia > MAIOR_DIA_UTIL:
            self.add_error("dia_vencimento_mensalidade", f"Nenhum mês tem mais que {MAIOR_DIA_UTIL} dias úteis.")
        return dados


_CONTROLE = {"class": "form-control"}
_NUMERO = {"class": "form-control", "inputmode": "numeric"}
_ESCOLHA = {"class": "form-select"}
_MARCA = {"class": "form-check-input"}


class CriarContaForm(BaseUserCreationForm):
    """A porta de entrada (ADR-094): o **login** e o **CRP**, e mais nada.

    O CRP fica aqui porque é condição de entrada (ADR-044): sem registro não há conta. Nome, CPF e telefone
    saíram para o quiz — pedir documento antes de a pessoa ver o produto era o maior atrito do cadastro.
    """

    class Meta(BaseUserCreationForm.Meta):
        model = Psicologo
        fields = ["email", "crp_regiao", "crp_numero"]
        field_classes = {}
        widgets = {
            "email": forms.EmailInput(attrs={**_CONTROLE, "placeholder": "voce@exemplo.com", "autofocus": True}),
            "crp_regiao": forms.TextInput(attrs={**_NUMERO, "placeholder": "04", "maxlength": 2}),
            "crp_numero": forms.TextInput(attrs={**_NUMERO, "placeholder": "123456"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ["password1", "password2"]:
            self.fields[campo].widget.attrs.update({"class": "form-control"})

    def clean(self):
        dados = super().clean()
        # A unicidade do CRP é uma restrição de duas colunas; dita aqui, vira mensagem no campo em vez de erro solto.
        regiao, numero = dados.get("crp_regiao"), dados.get("crp_numero")
        if regiao and numero and Psicologo.objects.filter(crp_regiao=regiao, crp_numero=numero).exists():
            self.add_error("crp_numero", "Já existe uma conta com este CRP. Se for a sua, entre com o seu e-mail.")
        return dados


class IdentificacaoForm(_QuemEVoce, LimpaMascara, forms.ModelForm):
    """Passo 1 do quiz: quem é o psicólogo — o que vai impresso em todo documento (ADR-044)."""

    CAMPOS_NUMERICOS = ("cpf", "telefone")

    class Meta:
        model = Psicologo
        fields = ["nome_completo", "cpf", "telefone"]
        widgets = {
            "nome_completo": forms.TextInput(attrs={**_CONTROLE, "autofocus": True}),
            "cpf": forms.TextInput(attrs={**_NUMERO, "data-mascara": "cpf", "placeholder": "000.000.000-00"}),
            "telefone": forms.TextInput(attrs={**_NUMERO, "data-mascara": "telefone",
                                               "placeholder": "(31) 98888-7777"}),
        }


class RegimeForm(LimpaMascara, forms.ModelForm):
    """Passo 2: o lado fiscal — regime (ADR-067) e se o sistema controla as despesas (ADR-100)."""

    CAMPOS_NUMERICOS = ("cnpj",)

    class Meta:
        model = Psicologo
        fields = ["regime", "cnpj", "razao_social", "usa_despesas"]
        widgets = {
            "regime": forms.RadioSelect(attrs=_MARCA),
            "cnpj": forms.TextInput(attrs={**_NUMERO, "data-mascara": "cnpj",
                                           "placeholder": "00.000.000/0000-00"}),
            "razao_social": forms.TextInput(attrs=_CONTROLE),
            "usa_despesas": forms.CheckboxInput(attrs=_MARCA),
        }

    def clean(self):
        dados = super().clean()
        if dados.get("regime") == Psicologo.Regime.PJ and not dados.get("cnpj"):
            self.add_error("cnpj", "Regime pessoa jurídica precisa do CNPJ.")
        if dados.get("regime") == Psicologo.Regime.PF and dados.get("cnpj"):
            self.add_error("cnpj", "Regime pessoa física não tem CNPJ. Troque o regime ou limpe o campo.")
        return dados


class ComoAtendeForm(EscolhasComOutra, forms.ModelForm):
    """Passo 3: abordagens, outras áreas e formas de atendimento (ADR-094, ADR-107)."""

    CATALOGOS = {"abordagens": "abordagem_outra", "outras_areas": "area_outra"}

    abordagens = _Catalogo(catalogo.ABORDAGENS, label="Qual é a sua abordagem?",
                           help_text=_AJUDA_ABORDAGENS)
    outras_areas = _Catalogo(catalogo.AREAS, label="Atua em alguma outra área?", required=False,
                             help_text=_AJUDA_AREAS)

    class Meta:
        model = Psicologo
        fields = ["abordagens", "abordagem_outra", "outras_areas", "area_outra",
                  "atende_online", "atende_presencial"]
        widgets = {
            "abordagem_outra": forms.TextInput(attrs={"class": "form-control form-control-sm",
                                                      "placeholder": "Escreva qual"}),
            "area_outra": forms.TextInput(attrs={"class": "form-control form-control-sm",
                                                 "placeholder": "Escreva qual"}),
            "atende_online": forms.CheckboxInput(attrs=_MARCA),
            "atende_presencial": forms.CheckboxInput(attrs=_MARCA),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Na primeira vez, nada vem marcado: o "presencial" que o banco tem por padrão não é resposta de ninguém.
        if not self.instance.abordagens:
            self.initial.update(atende_online=False, atende_presencial=False)

    def clean(self):
        dados = super().clean()
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
