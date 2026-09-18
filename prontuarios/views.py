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
from prontuarios.forms import AnamneseForm, ProntuarioForm
from prontuarios.models import Anamnese


class ListaProntuarios(LoginRequiredMixin, TemplateView):
    """Sem filtro: os pendentes. Com `?paciente=`: todas as sessões realizadas daquele paciente."""

    template_name = "prontuarios/lista.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        codigo = self.request.GET.get("paciente", "")
        paciente = get_object_or_404(Paciente, pk=int(codigo)) if codigo.isdigit() else None
        contexto.update(paciente=paciente, pacientes=Paciente.objects.order_by("nome"),
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

    def get_initial(self):
        registro = self.registro()
        if registro.rascunho is not None:
            return {"texto": registro.rascunho.texto}
        if registro.vigente is not None:
            return {"texto": registro.vigente.texto}  # editar parte do texto vigente
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
            acao(consulta, paciente, texto=dados["texto"])
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, "Prontuário salvo." if confirmando else "Rascunho salvo.")
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


class AnamneseDoPaciente(LoginRequiredMixin, FormView):
    """A sub-aba de anamnese na ficha do paciente (ADR-085). Opcional: enquanto ninguém escreve, nada é gravado."""

    form_class = AnamneseForm
    template_name = "prontuarios/anamnese.html"

    def paciente(self) -> Paciente:
        if not hasattr(self, "_paciente"):
            self._paciente = get_object_or_404(Paciente, pk=self.kwargs["pk"])
        return self._paciente

    def anamnese(self) -> Anamnese | None:
        if not hasattr(self, "_anamnese"):
            self._anamnese = Anamnese.objects.filter(paciente=self.paciente()).first()
        return self._anamnese

    def get(self, request, *args, **kwargs):
        resposta = super().get(request, *args, **kwargs)
        if self.anamnese() is not None:
            auditoria.registrar(auditoria.Acao.VER, self.anamnese())
        return resposta

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "instance": self.anamnese() or Anamnese(paciente=self.paciente())}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "paciente": self.paciente(), "anamnese": self.anamnese()}

    def form_valid(self, form):
        # Formulário em branco numa anamnese que ainda não existe não cria registro vazio.
        if self.anamnese() is None and not form.tem_conteudo():
            messages.info(self.request, "Nada escrito ainda — a anamnese continua em branco.")
        else:
            form.save()
            messages.success(self.request, "Anamnese salva.")
        return redirect("prontuarios:anamnese", pk=self.paciente().pk)

