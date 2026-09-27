"""Configurações da conta (ADR-100): o que o psicólogo liga, desliga e troca depois do cadastro.

São duas decisões que mudam o que o sistema faz, e não dados de identificação — por isso saíram do perfil:

- **controlar despesas ou não.** Quem só quer saber o que entra não vê a aba nem o resultado; desligar não apaga
  nada, e religar devolve tudo onde estava.
- **trocar de pessoa física para jurídica, ou o contrário.** A troca tem **data**: o passado continua apurado pelo
  regime que valia (`Psicologo.regime_em`), e a conta muda do dia marcado em diante.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from contas.models import MudancaDeRegime, Psicologo

_CONTROLE = {"class": "form-control"}
_NUMERO = {"class": "form-control", "inputmode": "numeric"}


class DespesasForm(forms.ModelForm):
    class Meta:
        model = Psicologo
        fields = ["usa_despesas"]
        widgets = {"usa_despesas": forms.CheckboxInput(attrs={"class": "form-check-input"})}


class RegimeNovoForm(forms.Form):
    """A troca de regime. Pede o que o regime novo exige, e a data em que ele passa a valer."""

    vigente_desde = forms.DateField(
        label="A partir de quando", widget=forms.DateInput(attrs={**_CONTROLE, "type": "date"}, format="%Y-%m-%d"),
        help_text="O financeiro anterior a esta data continua como está. A mudança vale deste dia em diante.")
    cnpj = forms.CharField(label="CNPJ", required=False, max_length=18,
                           widget=forms.TextInput(attrs={**_NUMERO, "data-mascara": "cnpj",
                                                         "placeholder": "00.000.000/0000-00"}))
    razao_social = forms.CharField(label="Razão social", required=False, max_length=255,
                                   widget=forms.TextInput(attrs=_CONTROLE))
    crp_empresa = forms.CharField(label="CRP da empresa", required=False, max_length=20,
                                  widget=forms.TextInput(attrs=_CONTROLE),
                                  help_text="Opcional. Clínica tem registro próprio no CRP.")

    def __init__(self, *args, psicologo: Psicologo, **kwargs):
        super().__init__(*args, **kwargs)
        self.psicologo = psicologo
        self.destino = (Psicologo.Regime.PJ if psicologo.regime == Psicologo.Regime.PF else Psicologo.Regime.PF)
        self.vira_pj = self.destino == Psicologo.Regime.PJ
        self.fields["vigente_desde"].initial = timezone.localdate()
        if not self.vira_pj:
            # Virando pessoa física, não há o que pedir: o que sai é o CNPJ, e ele sai sozinho.
            for campo in ("cnpj", "razao_social", "crp_empresa"):
                self.fields.pop(campo)

    def clean_cnpj(self):
        return "".join(c for c in self.cleaned_data.get("cnpj", "") if c.isdigit())

    def clean(self):
        dados = super().clean()
        if self.vira_pj:
            if not dados.get("cnpj"):
                self.add_error("cnpj", "Pessoa jurídica precisa do CNPJ.")
            elif len(dados["cnpj"]) != 14:
                self.add_error("cnpj", "CNPJ tem 14 números.")
            if not dados.get("razao_social"):
                self.add_error("razao_social", "Informe a razão social da empresa.")
        dia = dados.get("vigente_desde")
        if dia and dia < timezone.localdate():
            # Mesmo motivo da ADR-022: o passado não se reescreve por tela.
            self.add_error("vigente_desde", "A mudança vale de hoje em diante.")
        ultima = self.psicologo.mudancas_de_regime.first()
        if dia and ultima and dia < ultima.vigente_desde:
            self.add_error("vigente_desde",
                           f"A última mudança vale desde {ultima.vigente_desde:%d/%m/%Y}; a nova não pode ser antes.")
        return dados

    def aplicar(self) -> MudancaDeRegime:
        """Grava a mudança e o que o regime novo exige. Uma transação só — quem chama abre."""
        dados = self.cleaned_data
        mudanca = MudancaDeRegime.objects.create(
            regime_anterior=self.psicologo.regime, regime_novo=self.destino,
            vigente_desde=dados["vigente_desde"])
        self.psicologo.regime = self.destino
        if self.vira_pj:
            self.psicologo.cnpj = dados["cnpj"]
            self.psicologo.razao_social = dados["razao_social"]
            self.psicologo.crp_empresa = dados.get("crp_empresa", "")
        else:
            # Pessoa física com CNPJ é recusada pelo próprio perfil (ADR-067): sair de PJ limpa os dados da empresa.
            self.psicologo.cnpj = ""
            self.psicologo.razao_social = ""
            self.psicologo.crp_empresa = ""
        try:
            self.psicologo.save()
        except ValidationError as erro:
            raise ValidationError(erro.messages[0]) from erro
        return mudanca
