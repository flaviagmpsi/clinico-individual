"""Telas do prontuário escrito à mão (ADR-064).

Nenhuma view filtra por psicólogo: o `TenantManager` faz isso, e um id alheio na URL dá 404. Abrir um prontuário
que existe entra na trilha de auditoria (ADR-057).
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.text import slugify
from django.views import View
from django.views.generic import FormView, TemplateView

from atendimentos.models import Consulta
from core import auditoria, exportacao
from pacientes.models import Paciente
from prontuarios import orientacoes, servicos
from prontuarios.forms import FolhaDoProntuarioForm, ProntuarioForm


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


# --- O prontuário inteiro do paciente, preenchido dentro da folha (ADR-079) ----------------------------------------

class AbrirProntuario(LoginRequiredMixin, View):
    """O seletor da aba: recebe `?paciente=` e leva à folha dele."""

    def get(self, request, *args, **kwargs):
        codigo = request.GET.get("paciente", "")
        if not codigo.isdigit():
            return redirect("prontuarios:lista")
        return redirect("prontuarios:paciente", pk=get_object_or_404(Paciente, pk=int(codigo)).pk)


class ProntuarioDoPaciente(LoginRequiredMixin, FormView):
    """As quatro partes da Res. CFP nº 001/2009 numa folha só, com a orientação do CFP ao lado."""

    form_class = FolhaDoProntuarioForm
    template_name = "prontuarios/paciente.html"

    def paciente(self) -> Paciente:
        if not hasattr(self, "_paciente"):
            self._paciente = get_object_or_404(Paciente.objects.prefetch_related("responsaveis"), pk=self.kwargs["pk"])
        return self._paciente

    def folha(self) -> servicos.FolhaDoProntuario:
        if not hasattr(self, "_folha"):
            self._folha = servicos.folha_do_prontuario(self.paciente())
        return self._folha

    def get(self, request, *args, **kwargs):
        resposta = super().get(request, *args, **kwargs)
        auditoria.registrar(auditoria.Acao.VER, self.folha().ficha or self.paciente())
        return resposta

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "evolucao": self.folha().evolucao}

    def get_initial(self):
        folha = self.folha()
        inicial = {"demanda": folha.demanda, "encerramento": folha.encerramento}
        for registro in folha.evolucao:
            versao = registro.rascunho or registro.vigente
            if versao is not None:
                inicial[f"evolucao_{registro.consulta.pk}"] = versao.texto
        return inicial

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(
            paciente=self.paciente(), folha=self.folha(), orientacoes=orientacoes.ORIENTACOES,
            resumo=orientacoes.RESUMO, antes=orientacoes.ANTES, titulo_da_folha=orientacoes.TITULO,
            versao_da_norma=orientacoes.VERSAO_DA_NORMA, resolucao=orientacoes.RESOLUCAO_01_2009,
            manual=orientacoes.MANUAL_CFP, ajuda_evolucao=orientacoes.AJUDA_EVOLUCAO,
            pacientes=Paciente.objects.order_by("nome"))
        return contexto

    def form_valid(self, form):
        paciente = self.paciente()
        try:
            mudancas = servicos.salvar_folha(
                paciente, demanda=form.cleaned_data["demanda"], encerramento=form.cleaned_data["encerramento"],
                evolucoes=form.evolucoes())
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        # Salvar e baixar: o arquivo sai com o que está na folha agora (ADR-078).
        if self.request.POST.get("acao") in exportacao.GERADORES:
            return redirect("prontuarios:baixar", pk=paciente.pk, formato=self.request.POST["acao"])
        messages.success(self.request, "Prontuário salvo." if mudancas else "Nada mudou no prontuário.")
        return redirect("prontuarios:paciente", pk=paciente.pk)


class BaixarProntuario(LoginRequiredMixin, View):
    """O prontuário em PDF ou DOCX (ADR-078) — a cópia a que a pessoa atendida tem direito.

    Exportar entra na trilha de auditoria (ADR-057): é quando o dado mais sensível do produto deixa o sistema.
    """

    def get(self, request, *args, **kwargs):
        gerador = exportacao.GERADORES.get(self.kwargs["formato"])
        if gerador is None:
            raise Http404("Formato desconhecido.")
        paciente = get_object_or_404(Paciente.objects.prefetch_related("responsaveis"), pk=self.kwargs["pk"])
        gerar, tipo = gerador
        folha = {**servicos.folha_para_arquivo(paciente, request.user), "timbre": exportacao.timbre_de(request.user)}
        auditoria.registrar(auditoria.Acao.EXPORTAR, servicos.ficha_de(paciente) or paciente)
        nome = slugify(f"prontuario {paciente.nome}") or "prontuario"
        resposta = HttpResponse(gerar(folha), content_type=tipo)
        resposta["Content-Disposition"] = f'attachment; filename="{nome}.{self.kwargs["formato"]}"'
        return resposta
