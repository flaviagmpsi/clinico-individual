"""Formulários da agenda. Sem campo de dono: ele vem do contexto da requisição (ADR-001)."""

from django import forms
from django.utils import timezone

from agenda.models import Compromisso, HorarioDisponivel


class HorarioDisponivelForm(forms.ModelForm):
    class Meta:
        model = HorarioDisponivel
        fields = ["dia_semana", "inicio", "fim"]
        widgets = {
            "dia_semana": forms.Select(attrs={"class": "form-select"}),
            "inicio": forms.TimeInput(attrs={"class": "form-control", "type": "time"}, format="%H:%M"),
            "fim": forms.TimeInput(attrs={"class": "form-control", "type": "time"}, format="%H:%M"),
        }


class CompromissoForm(forms.ModelForm):
    """O compromisso fora da clínica (ADR-122). O dia da semana some no de uma vez só — quem manda é a data."""

    class Meta:
        model = Compromisso
        fields = ["titulo", "frequencia", "dia_semana", "inicio", "hora", "duracao", "fim"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Supervisão do Arthur"}),
            "frequencia": forms.Select(attrs={"class": "form-select", "data-frequencia": ""}),
            "dia_semana": forms.Select(attrs={"class": "form-select"}),
            "inicio": forms.DateInput(attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"),
            "hora": forms.TimeInput(attrs={"class": "form-control", "type": "time"}, format="%H:%M"),
            "duracao": forms.NumberInput(attrs={"class": "form-control", "min": 10, "max": 480, "step": 5}),
            "fim": forms.DateInput(attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inicio"].initial = timezone.localdate()
        self.fields["dia_semana"].required = False
        self.fields["fim"].required = False

    def clean(self):
        dados = super().clean()
        if dados.get("frequencia") == Compromisso.Frequencia.UNICO:
            dados["dia_semana"] = None
        elif dados.get("dia_semana") is None:
            self.add_error("dia_semana", "Diga em que dia da semana ele acontece.")
        fim, inicio = dados.get("fim"), dados.get("inicio")
        if fim and inicio and fim < inicio:
            self.add_error("fim", "A data de término não pode ser anterior à de início.")
        return dados
