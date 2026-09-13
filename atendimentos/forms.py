"""Formulários da agenda. Nenhum tem campo de dono: ele vem do contexto da requisição (ADR-001)."""

from datetime import datetime

from django import forms
from django.utils import timezone

from agenda.models import Recorrencia
from atendimentos.models import DURACAO_MAXIMA, Consulta
from atendimentos.servicos import AVULSO
from pacientes.models import Caso

_TEXTO = {"class": "form-control"}
_SELECT = {"class": "form-select"}
_RADIO = {"class": "form-check-input"}


class _Horario(forms.Form):
    data = forms.DateField(label="Data", widget=forms.DateInput(attrs={**_TEXTO, "type": "date"}, format="%Y-%m-%d"))
    hora = forms.TimeField(label="Horário", widget=forms.TimeInput(attrs={**_TEXTO, "type": "time"}, format="%H:%M"))
    duracao = forms.IntegerField(
        label="Duração (minutos)", min_value=10, max_value=DURACAO_MAXIMA,
        widget=forms.NumberInput(attrs={**_TEXTO, "step": 5}))

    def inicio(self) -> datetime:
        return timezone.make_aware(datetime.combine(self.cleaned_data["data"], self.cleaned_data["hora"]))


class ConsultaAvulsaForm(_Horario):
    # `objetos_todos.none()` na declaração: o atributo de classe é avaliado na importação, fora de
    # requisição, e o `TenantManager` levantaria `EscopoNaoDefinido`. O queryset real vem no `__init__`.
    caso = forms.ModelChoiceField(
        label="Paciente ou atendimento", queryset=Caso.objetos_todos.none(), widget=forms.Select(attrs=_SELECT))

    field_order = ["caso", "data", "hora", "duracao"]

    def __init__(self, *args, duracao_padrao: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["caso"].queryset = Caso.objects.prefetch_related("pacientes")
        self.fields["caso"].label_from_instance = str
        self.fields["duracao"].initial = duracao_padrao
        self.fields["duracao"].help_text = f"Padrão do seu perfil: {duracao_padrao} minutos."


class RemarcarForm(_Horario):
    pass


class RegistroForm(forms.Form):
    estado = forms.ChoiceField(
        label="O que aconteceu",
        choices=[(Consulta.Estado.REALIZADA, "Realizada"), (Consulta.Estado.FALTA, "Falta"),
                 (Consulta.Estado.CANCELADA, "Cancelada")],
        widget=forms.RadioSelect(attrs=_RADIO))
    cobranca = forms.ChoiceField(
        label="Entra na cobrança",
        choices=[("padrao", "Como no meu perfil"), ("sim", "Sim"), ("nao", "Não")],
        initial="padrao", widget=forms.RadioSelect(attrs=_RADIO))

    def __init__(self, *args, cobra_falta: bool, **kwargs):
        super().__init__(*args, **kwargs)
        falta = "entra, porque você cobra falta" if cobra_falta else "não entra, porque você não cobra falta"
        self.fields["cobranca"].help_text = (
            f"Pelo seu perfil: realizada entra; falta {falta}; cancelada não entra. Comparecimento e "
            "cobrança são independentes — uma sessão de cortesia é realizada e não entra (ADR-023).")

    def contabilizada(self) -> bool | None:
        return {"padrao": None, "sim": True, "nao": False}[self.cleaned_data["cobranca"]]


class FrequenciaForm(forms.Form):
    frequencia = forms.ChoiceField(
        label="Frequência",
        choices=[(Recorrencia.Frequencia.SEMANAL, "Semanal"),
                 (Recorrencia.Frequencia.QUINZENAL, "Quinzenal — semana sim, semana não"),
                 (AVULSO, "Avulso — sem sessão prevista")],
        widget=forms.RadioSelect(attrs=_RADIO))
    dia_semana = forms.TypedChoiceField(
        label="Dia da semana", choices=[("", "—")] + list(Recorrencia.DiaSemana.choices),
        coerce=int, empty_value=None, required=False, widget=forms.Select(attrs=_SELECT))
    hora = forms.TimeField(
        label="Horário", required=False, widget=forms.TimeInput(attrs={**_TEXTO, "type": "time"}, format="%H:%M"))
    duracao = forms.IntegerField(
        label="Duração (minutos)", required=False, min_value=10, max_value=DURACAO_MAXIMA,
        widget=forms.NumberInput(attrs={**_TEXTO, "step": 5}))
    a_partir_de = forms.DateField(
        label="Vale a partir de", widget=forms.DateInput(attrs={**_TEXTO, "type": "date"}, format="%Y-%m-%d"),
        help_text="Sessões anteriores a esta data não mudam (ADR-022).")

    def __init__(self, *args, duracao_padrao: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["duracao"].help_text = f"Vazio: padrão do seu perfil, {duracao_padrao} minutos."

    def clean(self):
        dados = super().clean()
        if dados.get("frequencia") in (Recorrencia.Frequencia.SEMANAL, Recorrencia.Frequencia.QUINZENAL):
            if dados.get("dia_semana") is None:
                self.add_error("dia_semana", "Informe o dia da semana.")
            if not dados.get("hora"):
                self.add_error("hora", "Informe o horário.")
        return dados
