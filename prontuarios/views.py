"""Telas do prontuário escrito à mão (ADR-064).

Nenhuma view filtra por psicólogo: o `TenantManager` faz isso, e um id alheio na URL dá 404. Abrir um prontuário
que existe entra na trilha de auditoria (ADR-057).
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import FormView, TemplateView

from atendimentos.models import Consulta
from core import auditoria
from pacientes.models import Paciente
from prontuarios import servicos
from prontuarios.forms import ProntuarioForm


class ListaProntuarios(LoginRequiredMixin, TemplateView):
    """Sem filtro: os pendentes. Com `?paciente=`: todas as sessões realizadas daquele paciente."""

    template_name = "prontuarios/lista.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        codigo = self.request.GET.get("paciente", "")
        paciente = get_object_or_404(Paciente, pk=int(codigo)) if codigo.isdigit() else None
        contexto.update(paciente=paciente,
                        registros=servicos.registros(paciente=paciente, somente_pendentes=paciente is None))
        return contexto


class _ComAlvo:
    def alvo(self) -> tuple[Consulta, Paciente]:
        if not hasattr(self, "_alvo"):
            consulta = get_object_or_404(Consulta.objects.select_related("caso"), pk=self.kwargs["consulta_pk"],
                                         estado=Consulta.Estado.REALIZADA)
            paciente = get_object_or_404(Paciente, pk=self.kwargs["paciente_pk"], participacoes__caso=consulta.caso)
            self._alvo = (consulta, paciente)
        return self._alvo


class EscreverProntuario(LoginRequiredMixin, _ComAlvo, FormView):
    form_class = ProntuarioForm
    template_name = "prontuarios/escrever.html"

    def registro(self) -> servicos.Registro:
        if not hasattr(self, "_registro"):
            self._registro = servicos.registro_de(*self.alvo())
        return self._registro

    def get(self, request, *args, **kwargs):
        resposta = super().get(request, *args, **kwargs)
        if self.registro().prontuario is not None:
            auditoria.registrar(auditoria.Acao.VER, self.registro().prontuario)
        return resposta

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["correcao"] = bool(self.registro().confirmadas)
        return kwargs

    def get_initial(self):
        registro = self.registro()
        if registro.rascunho is not None:
            return {"texto": registro.rascunho.texto, "motivo": registro.rascunho.motivo}
        if registro.vigente is not None:
            return {"texto": registro.vigente.texto}  # a correção parte do texto vigente
        return {}

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        consulta, paciente = self.alvo()
        contexto.update(registro=self.registro(), consulta=consulta, paciente=paciente)
        return contexto

    def form_valid(self, form):
        consulta, paciente = self.alvo()
        dados = form.cleaned_data
        confirmando = self.request.POST.get("acao") == "confirmar"
        acao = servicos.confirmar if confirmando else servicos.salvar_rascunho
        try:
            acao(consulta, paciente, texto=dados["texto"], motivo=dados.get("motivo", ""))
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, "Prontuário confirmado." if confirmando else "Rascunho salvo.")
        return redirect("prontuarios:escrever", consulta_pk=consulta.pk, paciente_pk=paciente.pk)


class DescartarRascunho(LoginRequiredMixin, _ComAlvo, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        consulta, paciente = self.alvo()
        try:
            servicos.descartar_rascunho(consulta, paciente)
        except ValidationError as erro:
            messages.error(request, erro.messages[0])
        else:
            messages.success(request, "Rascunho descartado.")
        return redirect("prontuarios:escrever", consulta_pk=consulta.pk, paciente_pk=paciente.pk)
