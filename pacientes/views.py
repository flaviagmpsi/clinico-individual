"""Telas do cadastro de pacientes.

Nenhuma view filtra por psicólogo. Não é descuido: `Paciente.objects` é o `TenantManager`, que
filtra sozinho e **levanta exceção** se não souber de quem é o dado (ADR-001). Uma view que
esquecesse o filtro não vazaria — ela quebraria. É a diferença entre confiar no programador e
confiar na fundação.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from pacientes.forms import PacienteForm
from pacientes.models import Paciente


class ListaPacientes(LoginRequiredMixin, ListView):
    model = Paciente
    template_name = "pacientes/lista.html"
    context_object_name = "pacientes"
    paginate_by = 25

    def get_queryset(self):
        pacientes = super().get_queryset()
        busca = self.request.GET.get("q", "").strip()
        if busca:
            pacientes = pacientes.filter(
                Q(nome__icontains=busca) | Q(cpf__contains=busca) | Q(email__icontains=busca)
            )
        return pacientes

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["busca"] = self.request.GET.get("q", "")
        return contexto


class DetalhePaciente(LoginRequiredMixin, DetailView):
    model = Paciente
    template_name = "pacientes/detalhe.html"
    context_object_name = "paciente"


class NovoPaciente(LoginRequiredMixin, CreateView):
    model = Paciente
    form_class = PacienteForm
    template_name = "pacientes/formulario.html"

    def form_valid(self, form):
        messages.success(self.request, f"Paciente {form.instance.nome} cadastrado.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("pacientes:detalhe", args=[self.object.pk])


class EditarPaciente(LoginRequiredMixin, UpdateView):
    model = Paciente
    form_class = PacienteForm
    template_name = "pacientes/formulario.html"

    def form_valid(self, form):
        messages.success(self.request, "Cadastro atualizado.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("pacientes:detalhe", args=[self.object.pk])


class ExcluirPaciente(LoginRequiredMixin, DeleteView):
    """⚠️ Exclusão definitiva, e só enquanto o paciente não tem prontuário.

    A partir do passo 3 isto precisa virar arquivamento: prontuário é peça de defesa legal com
    guarda mínima de 5 anos (ADR-005, Res. CFP 001/2009 Art. 4º), e apagar o paciente levaria o
    prontuário junto pelo CASCADE. Ver P-70.
    """

    model = Paciente
    template_name = "pacientes/excluir.html"
    success_url = reverse_lazy("pacientes:lista")

    def form_valid(self, form):
        messages.success(self.request, f"Paciente {self.object.nome} excluído.")
        return super().form_valid(form)
