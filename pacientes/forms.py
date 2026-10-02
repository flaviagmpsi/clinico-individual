"""Formulário do paciente.

O `psicologo` **não** está em `fields`, e não é esquecimento: ele é `editable=False` no model e
preenchido a partir do contexto da requisição (`TenantOwnedModel.save`). Não existe campo de dono
na tela, então não existe como errar o dono — nem por engano, nem por quem inspecionar o HTML.
"""

from django import forms
from django.core.exceptions import ValidationError

from core.calendario import MAIOR_DIA_UTIL, TipoDia, descrever_dia
from core.enderecos import no_brasil, telefone_de_qualquer_pais
from core.formularios import LimpaMascara
from pacientes import servicos
from pacientes.models import Caso, CondicaoCobranca, Paciente, ResponsavelLegal

_TEXTO = {"class": "form-control"}
_NUM = {"class": "form-control", "inputmode": "numeric"}
_CPF = {**_NUM, "data-mascara": "cpf", "placeholder": "000.000.000-00"}
_TELEFONE = {**_NUM, "data-mascara": "telefone", "placeholder": "(31) 98888-7777"}
_CEP = {**_NUM, "data-mascara": "cep", "data-busca-cep": "1", "placeholder": "30140-071"}
_VALOR = {"class": "form-control", "inputmode": "numeric", "data-mascara": "valor", "placeholder": "0,00"}
_DATA = {"class": "form-control", "type": "date"}
_SELECT = {"class": "form-select"}
_CHECK = {"class": "form-check-input"}


class CondicaoCobrancaForm(LimpaMascara, forms.Form):
    """Valor e forma de cobrança, no mesmo cadastro do paciente — sem a palavra "caso" (ADR-026).

    `Form`, e não `ModelForm`, de propósito: o valor é **opcional** no cadastro (ADR-012), e o model
    exige valor. Um `ModelForm` rodaria a validação do model mesmo com o campo vazio e recusaria o
    cadastro de quem ainda não combinou preço. A validação de verdade acontece no `save()` do
    serviço, que só cria a condição quando há valor.
    """

    CAMPOS_DECIMAIS = ("valor",)

    modalidade = forms.ChoiceField(
        label="Forma de cobrança", choices=CondicaoCobranca.Modalidade.choices,
        initial=CondicaoCobranca.Modalidade.POR_SESSAO, required=False,
        widget=forms.Select(attrs=_SELECT),
        # Rodada 80: a diferença entre as duas decide **quando** a cobrança aparece no financeiro, e era
        # invisível. Por sessão só cobra o que já foi registrado; mensal cobra o mês no dia 1º.
        help_text="Por sessão cobra o que você registrar como realizado. Mensal cobra o mês no dia 1º, "
                  "com vencimento no dia escolhido.")
    # `required=False` na forma de cobrança também: um POST que não traga o bloco de cobrança —
    # uma importação, um cliente antigo — tem de continuar cadastrando o paciente. Sem valor, a
    # forma não importa; com valor e sem forma, vale o padrão "por sessão".
    valor = forms.DecimalField(
        label="Valor", required=False, min_value=0, max_digits=10, decimal_places=2,
        widget=forms.TextInput(attrs=_VALOR),
        help_text="Opcional. Pode ser combinado depois.")
    tipo_vencimento = forms.ChoiceField(
        label="Vence em", required=False, choices=TipoDia.choices, initial=TipoDia.DIA_FIXO,
        widget=forms.Select(attrs={**_SELECT, "data-so-mensal": ""}),
        # ADR-123: por sessão não tem o que escolher — vence no dia do atendimento. O campo some na tela, em vez
        # de ficar visível sem efeito, que foi o que fez o usuário perguntar para que ele servia.
        help_text="Só para mensalidade.")
    dia_vencimento = forms.IntegerField(
        label="Dia do vencimento", required=False, min_value=1, max_value=31,
        widget=forms.NumberInput(attrs={**_TEXTO, "placeholder": "10", "data-so-mensal": ""}),
        help_text="Só para mensalidade. Em mês mais curto, vale o último dia.")

    def __init__(self, *args, dia_vencimento_padrao: int | None = None, tipo_vencimento_padrao: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        if dia_vencimento_padrao:
            # C-04 / ADR-025: o valor herdado do perfil vem preenchido **e diz de onde veio**.
            # Um campo que aparece marcado sem explicação faz o psicólogo achar que escolheu algo
            # que não escolheu.
            self.fields["dia_vencimento"].initial = dia_vencimento_padrao
            tipo = tipo_vencimento_padrao or TipoDia.DIA_FIXO
            self.fields["tipo_vencimento"].initial = tipo
            self.fields["dia_vencimento"].help_text = (
                f"Padrão do seu perfil: {descrever_dia(tipo, dia_vencimento_padrao)}. Só para mensalidade.")

    def clean(self):
        dados = super().clean()
        if dados.get("valor") is None:
            return dados
        dados["modalidade"] = dados.get("modalidade") or CondicaoCobranca.Modalidade.POR_SESSAO
        if dados["modalidade"] == CondicaoCobranca.Modalidade.MENSAL:
            dados["tipo_vencimento"] = dados.get("tipo_vencimento") or TipoDia.DIA_FIXO
            if not dados.get("dia_vencimento"):
                self.add_error("dia_vencimento", "Mensalidade precisa do dia de vencimento.")
            elif dados["tipo_vencimento"] == TipoDia.DIA_UTIL and dados["dia_vencimento"] > MAIOR_DIA_UTIL:
                self.add_error("dia_vencimento", f"Nenhum mês tem mais que {MAIOR_DIA_UTIL} dias úteis.")
        return dados

    def condicao(self) -> dict:
        """Argumentos de cobrança para `servicos.cadastrar_paciente` — vazio se não houver valor."""
        dados = self.cleaned_data
        if dados.get("valor") is None:
            return {}
        return {"valor": dados["valor"],
                "modalidade": dados.get("modalidade") or CondicaoCobranca.Modalidade.POR_SESSAO,
                "dia_vencimento": dados.get("dia_vencimento"), "tipo_vencimento": dados.get("tipo_vencimento") or ""}


class PagadorForm(LimpaMascara, forms.ModelForm):
    """Quem paga o atendimento individual: o próprio paciente, ou outra pessoa (ADR-009).

    O caso comum não pede campo nenhum. Os de nome e CPF só importam quando "outra pessoa" está
    marcado — pai pagando pelo filho, empresa custeando funcionário.
    """

    CAMPOS_NUMERICOS = ("pagador_cpf",)

    outra_pessoa = forms.BooleanField(
        label="Quem paga é outra pessoa", required=False, widget=forms.CheckboxInput(attrs=_CHECK))

    class Meta:
        model = Caso
        fields = ["pagador_nome", "pagador_cpf"]
        widgets = {
            "pagador_nome": forms.TextInput(attrs=_TEXTO),
            "pagador_cpf": forms.TextInput(attrs=_CPF),
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


class ResponsavelLegalForm(LimpaMascara, forms.ModelForm):
    CAMPOS_NUMERICOS = ("cpf", "telefone")

    class Meta:
        model = ResponsavelLegal
        fields = ["nome", "parentesco", "cpf", "telefone", "email", "guarda", "detem_guarda"]
        widgets = {
            "nome": forms.TextInput(attrs={**_TEXTO, "autofocus": True}),
            "parentesco": forms.TextInput(attrs={**_TEXTO, "placeholder": "mãe, avô, tutora"}),
            "cpf": forms.TextInput(attrs=_CPF),
            "telefone": forms.TextInput(attrs=_TELEFONE),
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


GENEROS_SUGERIDOS = ["Mulher cisgênero", "Homem cisgênero", "Mulher transgênero", "Homem transgênero",
                     "Pessoa não binária", "Prefiro não informar"]


def _campo_de_emergencia(rotulo: str, **atributos) -> forms.CharField:
    return forms.CharField(label=rotulo, required=False, max_length=255,
                           widget=forms.TextInput(attrs={**_TEXTO, **atributos}))


class PacienteForm(LimpaMascara, forms.ModelForm):
    """O cadastro feito pelo psicólogo. Traz os mesmos dados que o paciente pode informar pelo link (ADR-081):
    as duas portas chegam ao mesmo cadastro. Os contatos de emergência têm model próprio e entram aqui como
    campos avulsos — até dois, que é o que a tela pública pede."""

    CAMPOS_NUMERICOS = ("cpf", "telefone", "cep", "emergencia1_telefone", "emergencia2_telefone")

    def campos_numericos(self):
        # O código postal de fora do Brasil pode ter letra: não se tira nada dele (ADR-082).
        aqui = no_brasil(self.data.get(self.add_prefix("pais"), ""))
        return tuple(c for c in self.CAMPOS_NUMERICOS if c != "cep" or aqui)

    emergencia1_nome = _campo_de_emergencia("Nome")
    emergencia1_parentesco = _campo_de_emergencia("Parentesco", placeholder="mãe, irmão, amiga")
    emergencia1_telefone = forms.CharField(label="Telefone", required=False, max_length=20,
                                           validators=[telefone_de_qualquer_pais], widget=forms.TextInput(attrs=_TELEFONE))
    emergencia2_nome = _campo_de_emergencia("Nome")
    emergencia2_parentesco = _campo_de_emergencia("Parentesco", placeholder="mãe, irmão, amiga")
    emergencia2_telefone = forms.CharField(label="Telefone", required=False, max_length=20,
                                           validators=[telefone_de_qualquer_pais], widget=forms.TextInput(attrs=_TELEFONE))

    class Meta:
        model = Paciente
        fields = ["nome", "nome_social", "cpf", "documento_estrangeiro", "data_nascimento", "telefone", "email",
                  "estado_civil", "genero", "raca_cor", "profissao",
                  "pais", "cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf", "estado_exterior",
                  "medicamento", "modalidade", "data_primeira_sessao", "observacoes"]
        widgets = {
            "nome": forms.TextInput(attrs={**_TEXTO, "autofocus": True}),
            "nome_social": forms.TextInput(attrs=_TEXTO),
            "documento_estrangeiro": forms.TextInput(attrs=_TEXTO),
            "estado_civil": forms.Select(attrs=_SELECT),
            "genero": forms.TextInput(attrs={**_TEXTO, "list": "generos-sugeridos"}),
            "raca_cor": forms.Select(attrs=_SELECT),
            "profissao": forms.TextInput(attrs=_TEXTO),
            "pais": forms.TextInput(attrs=_TEXTO),
            "estado_exterior": forms.TextInput(attrs=_TEXTO),
            "cpf": forms.TextInput(attrs=_CPF),
            "data_nascimento": forms.DateInput(attrs=_DATA),
            "telefone": forms.TextInput(attrs=_TELEFONE),
            "email": forms.EmailInput(attrs=_TEXTO),
            "cep": forms.TextInput(attrs=_CEP),
            "logradouro": forms.TextInput(attrs=_TEXTO),
            "numero": forms.TextInput(attrs=_TEXTO),
            "complemento": forms.TextInput(attrs=_TEXTO),
            "bairro": forms.TextInput(attrs=_TEXTO),
            "cidade": forms.TextInput(attrs=_TEXTO),
            "uf": forms.Select(attrs={"class": "form-select"}),
            "medicamento": forms.Textarea(attrs={**_TEXTO, "rows": 2,
                "placeholder": "O que o paciente relata usar. Deixe vazio se não houver."}),
            "modalidade": forms.Select(attrs=_SELECT),
            "data_primeira_sessao": forms.DateInput(attrs=_DATA),
            "observacoes": forms.Textarea(attrs={**_TEXTO, "rows": 3}),
        }
        help_texts = {
            "cpf": "Opcional. Quem nasceu antes de 2018 pode não ter.",
            "nome_social": "Opcional. Como a pessoa prefere ser chamada.",
            "raca_cor": "Opcional. Dado sensível: só o que a pessoa declarar.",
            "genero": "Opcional. Como a pessoa se identifica.",
            "medicamento": "Registro do relato do paciente — o psicólogo não prescreve.",
            "modalidade": "Proposta a cada sessão deste paciente, e ajustável sessão a sessão (ADR-065).",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A modalidade tem padrão no model, e o `<select>` da tela nunca chega vazio. Exigi-la no
        # formulário só quebraria quem grava sem passar pela tela — importação, comando, teste.
        self.fields["modalidade"].required = False
        if self.instance.pk and not self.is_bound:
            for posicao, contato in enumerate(self.instance.contatos_de_emergencia.all()[:2], start=1):
                for campo in ("nome", "parentesco", "telefone"):
                    self.fields[f"emergencia{posicao}_{campo}"].initial = getattr(contato, campo)

    def clean_modalidade(self):
        return self.cleaned_data.get("modalidade") or Paciente.Modalidade.PRESENCIAL

    def clean_cpf(self):
        """CPF repetido vira erro no campo, com o nome de quem já o tem.

        A unicidade é por psicólogo e está no banco; mas o `psicologo` não é campo do formulário, então o Django
        não a valida aqui — e o cadastro repetido estourava como erro de servidor. Com o link de cadastro (ADR-081)
        isso deixa de ser raro: o paciente que já está cadastrado preenche de novo.
        """
        cpf = self.cleaned_data.get("cpf", "")
        if cpf:
            outro = Paciente.objects.filter(cpf=cpf).exclude(pk=self.instance.pk).first()
            if outro is not None:
                raise ValidationError(f"Você já tem um paciente com este CPF: {outro.nome}.")
        return cpf

    def clean(self):
        dados = super().clean()
        for posicao in (1, 2):
            nome, telefone = dados.get(f"emergencia{posicao}_nome"), dados.get(f"emergencia{posicao}_telefone")
            if nome and not telefone and f"emergencia{posicao}_telefone" not in self.errors:
                self.add_error(f"emergencia{posicao}_telefone", "Contato de emergência precisa de telefone.")
            if telefone and not nome:
                self.add_error(f"emergencia{posicao}_nome", "De quem é este telefone?")
        return dados

    def emergencias(self) -> list:
        return [(self[f"emergencia{n}_nome"], self[f"emergencia{n}_parentesco"], self[f"emergencia{n}_telefone"])
                for n in (1, 2)]

    def salvar_contatos_de_emergencia(self, paciente: Paciente) -> None:
        """Depois de o paciente estar gravado — é o serviço que compara e só regrava o que mudou."""
        dados = self.cleaned_data
        servicos.definir_contatos_de_emergencia(paciente, [
            {"nome": dados[f"emergencia{n}_nome"], "parentesco": dados.get(f"emergencia{n}_parentesco", ""),
             "telefone": dados.get(f"emergencia{n}_telefone", "")}
            for n in (1, 2) if dados.get(f"emergencia{n}_nome")])
