"""A tela de horários: a grade declarada e o mapa da semana (ADR-029, ADR-056).

Mora em `agenda` porque só precisa de regra de frequência e de grade — nenhuma consulta. Nenhuma view filtra
por psicólogo: o `TenantManager` faz isso, e um id alheio na URL dá 404.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.urls import reverse
from django.views.generic import CreateView, UpdateView


def contexto_dos_horarios() -> dict:
    """O que as duas telas de Horários mostram: a grade, os blocos declarados e os compromissos."""
    return {"mapa": mapa_da_semana(),
            "blocos": HorarioDisponivel.objects.all(),
            "compromissos": Compromisso.objects.all()}

from agenda.forms import CompromissoForm, HorarioDisponivelForm
from agenda.grade import mapa_da_semana
from agenda.models import Compromisso, HorarioDisponivel


class Horarios(LoginRequiredMixin, CreateView):
    """O mapa da semana e, ao lado, o formulário de bloco novo — na mesma tela, para ver o efeito na hora."""

    model = HorarioDisponivel
    form_class = HorarioDisponivelForm
    template_name = "agenda/horarios.html"
    success_url = reverse_lazy("agenda:horarios")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(contexto_dos_horarios(), compromisso=CompromissoForm())
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


class NovoCompromisso(LoginRequiredMixin, CreateView):
    """Compromisso fora da clínica — mora na tela de Horários, a pedido do usuário (ADR-122).

    Em `agenda` e não em `atendimentos` porque ele não é atendimento: é tempo ocupado, e nenhum app clínico
    precisa saber que ele existe.
    """

    model = Compromisso
    form_class = CompromissoForm
    template_name = "agenda/horarios.html"
    success_url = reverse_lazy("agenda:horarios")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(contexto_dos_horarios(), compromisso=contexto.pop("form"), abrir_compromisso=True)
        contexto.setdefault("form", HorarioDisponivelForm())
        return contexto

    def form_valid(self, form):
        resposta = super().form_valid(form)
        messages.success(self.request, f"Compromisso adicionado: {self.object.titulo}.")
        return resposta


class ExcluirCompromisso(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        compromisso = get_object_or_404(Compromisso, pk=pk)
        titulo = compromisso.titulo
        compromisso.delete()
        messages.success(request, f"Compromisso removido: {titulo}.")
        return redirect("agenda:horarios")


class EditarCompromisso(LoginRequiredMixin, UpdateView):
    """O mesmo formulário, na mesma tela, preenchido com o que já existe.

    Editar e não versionar, ao contrário da frequência do paciente (ADR-022): aquela explica o passado — uma
    sessão de março precisa da regra que valia em março. Esta é um lembrete visual do próprio psicólogo, e
    guardar o histórico de uma supervisão que mudou de horário não serviria a ninguém.
    """

    model = Compromisso
    form_class = CompromissoForm
    template_name = "agenda/horarios.html"
    success_url = reverse_lazy("agenda:horarios")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(contexto_dos_horarios(), compromisso=contexto.pop("form"),
                        editando=self.object,
                        acao_compromisso=reverse("agenda:compromisso_editar", args=[self.object.pk]))
        contexto.setdefault("form", HorarioDisponivelForm())
        return contexto

    def form_valid(self, form):
        resposta = super().form_valid(form)
        messages.success(self.request, f"Compromisso atualizado: {self.object.titulo}.")
        return resposta
