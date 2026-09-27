"""Formulário de pagamento. Sem campo de dono nem de referência: o dono vem da requisição (ADR-001), e a
referência — o mês ou a sessão — vem da URL, já filtrada pelo dono."""

from decimal import Decimal

from django import forms

from core.formularios import LimpaMascara
from financeiro import carne_leao
from financeiro.models import Despesa, Pagamento

_TEXTO = {"class": "form-control"}


class PagamentoForm(forms.Form):
    valor = forms.DecimalField(
        label="Valor", min_value=Decimal("0.01"), max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={**_TEXTO, "step": "0.01"}))
    data = forms.DateField(
        label="Pago em", widget=forms.DateInput(attrs={**_TEXTO, "type": "date"}, format="%Y-%m-%d"))
    forma = forms.ChoiceField(
        label="Forma de pagamento", choices=Pagamento.Forma.choices,
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}))
    observacao = forms.CharField(
        label="Observação", required=False, widget=forms.Textarea(attrs={**_TEXTO, "rows": 2}))


class DespesaForm(LimpaMascara, forms.ModelForm):
    """A despesa tem **categoria** do carnê-leão (ADR-099) e nome livre (ADR-083).

    A categoria diz o que a Receita faz com o gasto; a descrição continua sendo do psicólogo, porque "aluguel" dele
    pode ser "sala da terça com a Bete" — e nenhum catálogo escreve isso por ele.
    """

    CAMPOS_DECIMAIS = ("valor",)

    class Meta:
        model = Despesa
        fields = ["categoria", "descricao", "valor", "vencimento", "mensal", "fim"]
        widgets = {
            "categoria": forms.Select(attrs={"class": "form-select", "autofocus": True}),
            "descricao": forms.TextInput(attrs={**_TEXTO,
                                                "placeholder": "Ex.: sala da rua Bahia, internet do consultório"}),
            "valor": forms.TextInput(attrs={**_TEXTO, "inputmode": "numeric", "data-mascara": "valor",
                                            "placeholder": "0,00"}),
            "vencimento": forms.DateInput(attrs={**_TEXTO, "type": "date"}, format="%Y-%m-%d"),
            "mensal": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "fim": forms.DateInput(attrs={**_TEXTO, "type": "date"}, format="%Y-%m-%d"),
        }
        help_texts = {
            "descricao": "O nome que você dá a ela. Aparece na lista e no fluxo de caixa.",
            "vencimento": "Na despesa que repete, é o primeiro vencimento: o dia vale para os meses seguintes.",
            "mensal": "Marque se ela aparece todo mês — aluguel, internet, contador.",
            "fim": "Opcional. Só para despesa mensal que tem data para acabar.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].choices = [("", "Escolha a categoria")] + list(carne_leao.ESCOLHAS)
        self.fields["categoria"].required = True
        # A tela precisa saber, para cada opção, o que a Receita diz dela — sem repetir o catálogo no template.
        self.categorias = carne_leao.por_grupo()

    def clean(self):
        dados = super().clean()
        if not dados.get("mensal"):
            dados["fim"] = None
        return dados

