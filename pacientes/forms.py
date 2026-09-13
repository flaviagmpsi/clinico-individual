"""Formulário do paciente.

O `psicologo` **não** está em `fields`, e não é esquecimento: ele é `editable=False` no model e
preenchido a partir do contexto da requisição (`TenantOwnedModel.save`). Não existe campo de dono
na tela, então não existe como errar o dono — nem por engano, nem por quem inspecionar o HTML.
"""

from django import forms
from django.core.exceptions import ValidationError

from pacientes.models import Caso, CondicaoCobranca, Paciente, ResponsavelLegal

_TEXTO = {"class": "form-control"}
_NUM = {"class": "form-control", "inputmode": "numeric"}
_DATA = {"class": "form-control", "type": "date"}
_SELECT = {"class": "form-select"}
_CHECK = {"class": "form-check-input"}


class CondicaoCobrancaForm(forms.Form):
    """Valor e forma de cobrança, no mesmo cadastro do paciente — sem a palavra "caso" (ADR-026).

    `Form`, e não `ModelForm`, de propósito: o valor é **opcional** no cadastro (ADR-012), e o model
    exige valor. Um `ModelForm` rodaria a validação do model mesmo com o campo vazio e recusaria o
    cadastro de quem ainda não combinou preço. A validação de verdade acontece no `save()` do
    serviço, que só cria a condição quando há valor.
    """

    modalidade = forms.ChoiceField(
        label="Forma de cobrança", choices=CondicaoCobranca.Modalidade.choices,
        initial=CondicaoCobranca.Modalidade.POR_SESSAO, required=False,
        widget=forms.Select(attrs=_SELECT))
    # `required=False` na forma de cobrança também: um POST que não traga o bloco de cobrança —
    # uma importação, um cliente antigo — tem de continuar cadastrando o paciente. Sem valor, a
    # forma não importa; com valor e sem forma, vale o padrão "por sessão".
    valor = forms.DecimalField(
        label="Valor", required=False, min_value=0, max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={**_TEXTO, "step": "0.01", "placeholder": "0,00"}),
        help_text="Opcional. Pode ser combinado depois.")
    vencimento = forms.ChoiceField(
        label="Vencimento", required=False,
        choices=[("", "—")] + list(CondicaoCobranca.Vencimento.choices),
        widget=forms.Select(attrs=_SELECT), help_text="Só para mensalidade.")

    def __init__(self, *args, vencimento_padrao: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        if vencimento_padrao:
            # C-04 / ADR-025: o valor herdado do perfil vem preenchido **e diz de onde veio**.
            # Um campo que aparece marcado sem explicação faz o psicólogo achar que escolheu algo
            # que não escolheu.
            self.fields["vencimento"].initial = vencimento_padrao
            rotulo = dict(CondicaoCobranca.Vencimento.choices).get(vencimento_padrao, "")
            self.fields["vencimento"].help_text = f"Padrão do seu perfil: {rotulo.lower()}. Só para mensalidade."

    def clean(self):
        dados = super().clean()
        if dados.get("valor") is None:
            return dados
        dados["modalidade"] = dados.get("modalidade") or CondicaoCobranca.Modalidade.POR_SESSAO
        if dados["modalidade"] == CondicaoCobranca.Modalidade.MENSAL and not dados.get("vencimento"):
            self.add_error("vencimento", "Mensalidade precisa de vencimento.")
        return dados

    def condicao(self) -> dict:
        """Argumentos de cobrança para `servicos.cadastrar_paciente` — vazio se não houver valor."""
        dados = self.cleaned_data
        if dados.get("valor") is None:
            return {}
        return {"valor": dados["valor"],
                "modalidade": dados.get("modalidade") or CondicaoCobranca.Modalidade.POR_SESSAO,
                "vencimento": dados.get("vencimento") or ""}


class PagadorForm(forms.ModelForm):
    """Quem paga o atendimento individual: o próprio paciente, ou outra pessoa (ADR-009).

    O caso comum não pede campo nenhum. Os de nome e CPF só importam quando "outra pessoa" está
    marcado — pai pagando pelo filho, empresa custeando funcionário.
    """

    outra_pessoa = forms.BooleanField(
        label="Quem paga é outra pessoa", required=False, widget=forms.CheckboxInput(attrs=_CHECK))

    class Meta:
        model = Caso
        fields = ["pagador_nome", "pagador_cpf"]
        widgets = {
            "pagador_nome": forms.TextInput(attrs=_TEXTO),
            "pagador_cpf": forms.TextInput(attrs={**_NUM, "placeholder": "só números"}),
        }

    def __init__(self, *args, paciente: Paciente, **kwargs):
        super().__init__(*args, **kwargs)
        self.paciente = paciente
        self.fields["outra_pessoa"].initial = bool(self.instance.pagador_nome)

    def clean(self):
        dados = super().clean()
        # `pagador_paciente` não é campo da tela; é ajustado aqui, antes de o Django validar o
        # model, para que "participante ou pessoa de fora, nunca os dois" nunca seja violado.
        if dados.get("outra_pessoa"):
            if not dados.get("pagador_nome"):
                self.add_error("pagador_nome", "Informe o nome de quem paga.")
            self.instance.pagador_paciente = None
        else:
            dados["pagador_nome"] = ""
            dados["pagador_cpf"] = ""
            self.instance.pagador_paciente = self.paciente
        return dados


class ResponsavelLegalForm(forms.ModelForm):
    class Meta:
        model = ResponsavelLegal
        fields = ["nome", "parentesco", "cpf", "telefone", "email", "guarda", "detem_guarda"]
        widgets = {
            "nome": forms.TextInput(attrs={**_TEXTO, "autofocus": True}),
            "parentesco": forms.TextInput(attrs={**_TEXTO, "placeholder": "mãe, avô, tutora"}),
            "cpf": forms.TextInput(attrs={**_NUM, "placeholder": "só números"}),
            "telefone": forms.TextInput(attrs={**_NUM, "placeholder": "31988887777"}),
            "email": forms.EmailInput(attrs=_TEXTO),
            "guarda": forms.Select(attrs=_SELECT),
            "detem_guarda": forms.CheckboxInput(attrs=_CHECK),
        }


class CasoColetivoForm(forms.Form):
    """Criar atendimento de casal ou família a partir de pacientes já cadastrados."""

    descricao = forms.CharField(
        label="Descrição", max_length=120, required=False, widget=forms.TextInput(attrs=_TEXTO),
        help_text='Ex.: "Maria e João — casal".')
    # `objetos_todos.none()` na declaração, e não `objects`: o atributo de classe é avaliado na
    # importação do módulo, fora de qualquer requisição, e o `TenantManager` levantaria
    # `EscopoNaoDefinido`. O queryset real — filtrado pelo dono — é posto no `__init__`.
    pacientes = forms.ModelMultipleChoiceField(
        label="Participantes", queryset=Paciente.objetos_todos.none(),
        widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pacientes"].queryset = Paciente.objects.all()

    def clean_pacientes(self):
        pacientes = self.cleaned_data["pacientes"]
        if len(pacientes) < 2:
            raise ValidationError("Atendimento de casal ou família tem pelo menos dois participantes.")
        return pacientes


class TrocaCobrancaForm(CondicaoCobrancaForm):
    """A mesma cobrança do cadastro, mas com valor **obrigatório**: aqui não existe "combinar depois"
    — quem abre esta tela veio justamente mudar o valor ou a forma."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["valor"].required = True
        self.fields["valor"].help_text = ""


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
