"""Telas da agenda.

Moram em `atendimentos`, e não em `agenda`, porque mostram consultas — e `agenda` não conhece
consulta (regra 5 de dependência). Dono do dado e lugar na tela são coisas diferentes.

Toda busca de objeto pela URL acontece depois do `LoginRequiredMixin`, nunca no `dispatch`: buscar antes
faria o visitante anônimo receber um erro de escopo em vez de ser mandado ao login.
"""

from datetime import date, time, timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import FormView, TemplateView

from atendimentos import servicos
from atendimentos.forms import ConsultaAvulsaForm, FrequenciaForm, RegistroForm, RemarcarForm
from atendimentos.models import Consulta
from pacientes.models import Caso


def _segunda(dia: date) -> date:
    return dia - timedelta(days=dia.weekday())


def _semana_de(dia: date) -> str:
    return f"{reverse('atendimentos:agenda')}?semana={_segunda(dia):%Y-%m-%d}"


class Agenda(LoginRequiredMixin, TemplateView):
    template_name = "atendimentos/agenda.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        hoje = timezone.localdate()
        try:
            base = date.fromisoformat(self.request.GET.get("semana", ""))
        except ValueError:
            base = hoje
        segunda = _segunda(base)

        # ADR-022: a janela de previsão avança quando a agenda abre — sem agendador (ADR-018).
        nao_geradas = servicos.gerar_consultas(hoje)

        inicio = servicos.momento(segunda, time.min)
        consultas = list(
            Consulta.objects.filter(inicio__gte=inicio, inicio__lt=inicio + timedelta(days=7))
            .select_related("caso").prefetch_related("caso__pacientes")
        )
        dias = []
        for n in range(7):
            dia = segunda + timedelta(days=n)
            dias.append((dia, [c for c in consultas if timezone.localtime(c.inicio).date() == dia]))

        contexto.update(
            dias=dias, segunda=segunda, domingo=segunda + timedelta(days=6), hoje=hoje,
            anterior=segunda - timedelta(days=7), proxima=segunda + timedelta(days=7), esta=_segunda(hoje),
            pendentes=list(servicos.consultas_sem_registro()[:10]), nao_geradas=nao_geradas,
        )
        return contexto


class NovaConsulta(LoginRequiredMixin, FormView):
    form_class = ConsultaAvulsaForm
    template_name = "atendimentos/consulta_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["duracao_padrao"] = self.request.user.duracao_sessao
        return kwargs

    def get_initial(self):
        inicial = super().get_initial()
        caso = self.request.GET.get("caso", "")
        if caso.isdigit():
            inicial["caso"] = int(caso)  # id alheio não faz nada: não está entre as opções
        return inicial

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["titulo"] = "Nova consulta avulsa"
        return contexto

    def form_valid(self, form):
        try:
            consulta = servicos.marcar_avulsa(
                form.cleaned_data["caso"], inicio=form.inicio(), duracao=form.cleaned_data["duracao"])
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, "Consulta marcada.")
        return redirect(_semana_de(timezone.localtime(consulta.inicio).date()))


class _ComConsulta:
    def consulta(self) -> Consulta:
        if not hasattr(self, "_consulta"):
            self._consulta = get_object_or_404(Consulta.objects.select_related("caso"), pk=self.kwargs["pk"])
        return self._consulta

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["consulta"] = self.consulta()
        return contexto


class RemarcarConsulta(LoginRequiredMixin, _ComConsulta, FormView):
    form_class = RemarcarForm
    template_name = "atendimentos/consulta_form.html"

    def get_initial(self):
        consulta = self.consulta()
        local = timezone.localtime(consulta.inicio)
        return {"data": local.date(), "hora": local.time().replace(second=0, microsecond=0),
                "duracao": consulta.duracao}

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["titulo"] = "Remarcar consulta"
        return contexto

    def form_valid(self, form):
        try:
            consulta = servicos.remarcar(self.consulta(), inicio=form.inicio(), duracao=form.cleaned_data["duracao"])
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, "Consulta remarcada.")
        return redirect(_semana_de(timezone.localtime(consulta.inicio).date()))


class RegistrarConsulta(LoginRequiredMixin, _ComConsulta, FormView):
    form_class = RegistroForm
    template_name = "atendimentos/registrar.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["cobra_falta"] = self.request.user.cobra_falta
        return kwargs

    def get_initial(self):
        consulta = self.consulta()
        if consulta.estado == Consulta.Estado.AGENDADA:
            return {"cobranca": "padrao"}
        return {"estado": consulta.estado, "cobranca": "sim" if consulta.contabilizada else "nao"}

    def form_valid(self, form):
        consulta = self.consulta()
        try:
            servicos.registrar(consulta, form.cleaned_data["estado"], contabilizada=form.contabilizada())
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, f"Consulta registrada como {consulta.get_estado_display().lower()}.")
        return redirect(_semana_de(timezone.localtime(consulta.inicio).date()))


class FrequenciaDoCaso(LoginRequiredMixin, FormView):
    """Semanal, quinzenal ou avulso (ADR-053) — do paciente individual ou do atendimento de casal."""

    form_class = FrequenciaForm
    template_name = "atendimentos/frequencia.html"

    def caso(self) -> Caso:
        if not hasattr(self, "_caso"):
            self._caso = get_object_or_404(Caso.objects.prefetch_related("pacientes"), pk=self.kwargs["caso_pk"])
        return self._caso

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["duracao_padrao"] = self.request.user.duracao_sessao
        return kwargs

    def get_initial(self):
        regra = self.caso().regra_aberta()
        inicial = {"a_partir_de": timezone.localdate()}
        if regra is None:
            inicial["frequencia"] = servicos.AVULSO
        else:
            inicial.update(frequencia=regra.frequencia, dia_semana=regra.dia_semana, hora=regra.hora,
                           duracao=regra.duracao)
        return inicial

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        caso = self.caso()
        contexto.update(caso=caso, regra=caso.regra_aberta(), individual=caso.individual,
                        paciente=caso.pacientes.first())
        return contexto

    def form_valid(self, form):
        dados = form.cleaned_data
        caso = self.caso()
        try:
            servicos.definir_frequencia(
                caso, frequencia=dados["frequencia"], dia_semana=dados.get("dia_semana"), hora=dados.get("hora"),
                duracao=dados.get("duracao"), a_partir_de=dados["a_partir_de"])
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, "Frequência atualizada.")
        if caso.individual:
            return redirect("pacientes:detalhe", pk=caso.pacientes.first().pk)
        return redirect("pacientes:caso", pk=caso.pk)
