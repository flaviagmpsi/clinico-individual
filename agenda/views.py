"""A tela de horários: a grade declarada e o mapa da semana (ADR-029, ADR-056).

Mora em `agenda` porque só precisa de regra de frequência e de grade — nenhuma consulta. Nenhuma view filtra
por psicólogo: o `TenantManager` faz isso, e um id alheio na URL dá 404.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView

from agenda.forms import HorarioDisponivelForm
from agenda.grade import mapa_da_semana
from agenda.models import HorarioDisponivel


class Horarios(LoginRequiredMixin, CreateView):
    """O mapa da semana e, ao lado, o formulário de bloco novo — na mesma tela, para ver o efeito na hora."""

    model = HorarioDisponivel
    form_class = HorarioDisponivelForm
    template_name = "agenda/horarios.html"
    success_url = reverse_lazy("agenda:horarios")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["mapa"] = mapa_da_semana()
        contexto["blocos"] = HorarioDisponivel.objects.all()
        return contexto

    def form_valid(self, form):
        resposta = super().form_valid(form)
        messages.success(self.request, f"Horário adicionado: {self.object}.")
        return resposta


class ExcluirHorario(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        bloco = get_object_or_404(HorarioDisponivel, pk=pk)
        descricao = str(bloco)
        bloco.delete()
        messages.success(request, f"Horário removido: {descricao}.")
        return redirect("agenda:horarios")
