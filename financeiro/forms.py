"""Formulário de pagamento. Sem campo de dono nem de referência: o dono vem da requisição (ADR-001), e a
referência — o mês ou a sessão — vem da URL, já filtrada pelo dono."""

from decimal import Decimal

from django import forms

from financeiro.models import Pagamento

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
