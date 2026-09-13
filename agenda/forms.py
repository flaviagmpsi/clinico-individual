"""Formulário da grade. Sem campo de dono: ele vem do contexto da requisição (ADR-001)."""

from django import forms

from agenda.models import HorarioDisponivel


class HorarioDisponivelForm(forms.ModelForm):
    class Meta:
        model = HorarioDisponivel
        fields = ["dia_semana", "inicio", "fim"]
        widgets = {
            "dia_semana": forms.Select(attrs={"class": "form-select"}),
            "inicio": forms.TimeInput(attrs={"class": "form-control", "type": "time"}, format="%H:%M"),
            "fim": forms.TimeInput(attrs={"class": "form-control", "type": "time"}, format="%H:%M"),
        }
