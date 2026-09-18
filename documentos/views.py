"""Telas dos documentos psicológicos (ADR-076).

Nenhuma view filtra por psicólogo: o `TenantManager` faz isso, e um id alheio na URL dá 404. Abrir um documento
que existe entra na trilha de auditoria (ADR-057).

Toda busca de objeto pela URL acontece depois do `LoginRequiredMixin`, nunca no `dispatch`: buscar antes faria o
visitante anônimo receber um erro de escopo em vez de ser mandado ao login.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.text import slugify
from django.views import View
from django.views.generic import FormView, TemplateView

from core import auditoria, exportacao
from documentos import modelos, servicos
from documentos.forms import DocumentoForm
from documentos.models import Documento
from pacientes.models import Paciente


def _paciente_do_pedido(valor: str | None) -> Paciente | None:
    """O paciente escolhido no seletor. Id alheio dá 404; vazio é "sem paciente"."""
    return get_object_or_404(Paciente, pk=int(valor)) if (valor or "").isdigit() else None


def _grupos():
    return [("As modalidades da Res. CFP nº 06/2019", [m for m in modelos.CATALOGO if m.grupo == "documento"]),
            ("Termos de apoio", [m for m in modelos.CATALOGO if m.grupo == "apoio"])]


class Aba(LoginRequiredMixin, TemplateView):
    """A entrada: os modelos disponíveis e os documentos já escritos — rascunhos e emitidos."""

    template_name = "documentos/aba.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        paciente = _paciente_do_pedido(self.request.GET.get("paciente"))
        contexto.update(grupos=_grupos(), paciente=paciente, documentos=servicos.documentos(paciente=paciente),
                        versao_da_norma=modelos.VERSAO_DA_NORMA, manual=modelos.MANUAL_CFP,
                        resolucao=modelos.RESOLUCAO_06_2019)
        return contexto


class _Escrever(LoginRequiredMixin, FormView):
    """O que criar e editar têm em comum: a sub-aba do modelo, com a orientação do CFP e o formulário."""

    form_class = DocumentoForm
    template_name = "documentos/modelo.html"

    def modelo(self) -> modelos.ModeloDeDocumento:
        raise NotImplementedError

    def documento(self) -> Documento | None:
        return None

    def paciente(self) -> Paciente | None:
        raise NotImplementedError

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["modelo"] = self.modelo()
        return kwargs

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(modelo=self.modelo(), documento=self.documento(), paciente=self.paciente(),
                        grupos=_grupos(), pacientes=Paciente.objects.order_by("nome"),
                        versao_da_norma=modelos.VERSAO_DA_NORMA, manual=modelos.MANUAL_CFP,
                        resolucao=modelos.RESOLUCAO_06_2019)
        return contexto

    def form_valid(self, form):
        paciente = _paciente_do_pedido(self.request.POST.get("paciente"))
        try:
            documento = servicos.salvar_rascunho(self.modelo().codigo, form.cleaned_data, paciente=paciente,
                                                 documento=self.documento())
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        if self.request.POST.get("acao") == "emitir":
            try:
                servicos.emitir(documento)
            except ValidationError as erro:
                # O que foi escrito não se perde: a emissão recusada deixa o rascunho salvo. E a volta é para a
                # tela **desse** rascunho — ficar na URL de "novo" criaria outro a cada tentativa.
                messages.error(self.request, f"{erro.messages[0]} O rascunho ficou salvo.")
                return redirect("documentos:editar", pk=documento.pk)
            messages.success(self.request, "Documento emitido. A cópia fica guardada no registro documental.")
            return redirect("documentos:imprimir", pk=documento.pk)
        if self.request.POST.get("acao") in exportacao.GERADORES:
            return redirect("documentos:baixar", pk=documento.pk, formato=self.request.POST["acao"])
        messages.success(self.request, "Rascunho salvo.")
        return redirect("documentos:editar", pk=documento.pk)


class NovoDocumento(_Escrever):
    """A sub-aba de um modelo: como o CFP espera o documento, e o formulário em branco."""

    def modelo(self):
        modelo = modelos.obter(self.kwargs["codigo"])
        if modelo is None:
            raise Http404("Modelo de documento inexistente.")
        return modelo

    def paciente(self):
        if not hasattr(self, "_paciente"):
            origem = self.request.POST if self.request.method == "POST" else self.request.GET
            self._paciente = _paciente_do_pedido(origem.get("paciente"))
        return self._paciente

    def get_initial(self):
        return servicos.sugestoes(self.modelo(), self.request.user, self.paciente())


class EditarDocumento(_Escrever):
    def documento(self):
        if not hasattr(self, "_documento"):
            self._documento = get_object_or_404(Documento.objects.select_related("paciente"), pk=self.kwargs["pk"])
        return self._documento

    def modelo(self):
        return self.documento().definicao

    def paciente(self):
        return self.documento().paciente

    def get(self, request, *args, **kwargs):
        if not self.documento().rascunho:
            return redirect("documentos:imprimir", pk=self.documento().pk)
        auditoria.registrar(auditoria.Acao.VER, self.documento())
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if not self.documento().rascunho:
            messages.error(request, "Documento emitido não se altera. Crie um novo a partir dele.")
            return redirect("documentos:imprimir", pk=self.documento().pk)
        return super().post(request, *args, **kwargs)

    def get_initial(self):
        return dict(self.documento().dados)


class Imprimir(LoginRequiredMixin, TemplateView):
    """O documento composto, pronto para imprimir ou salvar em PDF pelo navegador."""

    template_name = "documentos/imprimir.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        documento = get_object_or_404(Documento.objects.select_related("paciente"), pk=self.kwargs["pk"])
        auditoria.registrar(auditoria.Acao.VER, documento)
        contexto.update(documento=documento, folha=modelos.compor(documento.definicao, documento.dados),
                        faltando=servicos.faltando(documento) if documento.rascunho else [])
        return contexto


class Baixar(LoginRequiredMixin, View):
    """O documento em arquivo — PDF ou DOCX (ADR-078). Sai da mesma composição da folha e da impressão.

    Exportar entra na trilha de auditoria (ADR-057): é o momento em que o conteúdo deixa o sistema. Rascunho pode
    ser baixado, mas sai marcado como rascunho — arquivo solto não pode se passar por documento emitido.
    """

    def get(self, request, *args, **kwargs):
        gerador = exportacao.GERADORES.get(self.kwargs["formato"])
        if gerador is None:
            raise Http404("Formato desconhecido.")
        documento = get_object_or_404(Documento.objects.select_related("paciente"), pk=self.kwargs["pk"])
        gerar, tipo = gerador
        folha = {**modelos.compor(documento.definicao, documento.dados),
                 "timbre": exportacao.timbre_de(request.user), "rascunho": documento.rascunho}
        auditoria.registrar(auditoria.Acao.EXPORTAR, documento)
        nome = slugify(f"{documento.nome} {documento.atendido}") or "documento"
        if documento.rascunho:
            nome = f"rascunho-{nome}"
        resposta = HttpResponse(gerar(folha), content_type=tipo)
        resposta["Content-Disposition"] = f'attachment; filename="{nome}.{self.kwargs["formato"]}"'
        return resposta


class _Acao(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def documento(self) -> Documento:
        return get_object_or_404(Documento, pk=self.kwargs["pk"])


class ExcluirRascunho(_Acao):
    def post(self, request, *args, **kwargs):
        try:
            servicos.excluir_rascunho(self.documento())
        except ValidationError as erro:
            messages.error(request, erro.messages[0])
        else:
            messages.success(request, "Rascunho excluído.")
        return redirect("documentos:aba")


class Duplicar(_Acao):
    def post(self, request, *args, **kwargs):
        novo = servicos.duplicar(self.documento())
        messages.success(request, "Rascunho criado a partir do documento. O original continua guardado como está.")
        return redirect("documentos:editar", pk=novo.pk)
