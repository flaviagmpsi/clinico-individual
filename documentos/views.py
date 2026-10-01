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
from django.urls import reverse
from django.utils.text import slugify
from django.views import View
from django.views.generic import FormView, TemplateView

from core import auditoria, exportacao
from documentos import guarda, modelos, servicos
from documentos.arquivos import ArquivoGuardado
from documentos.forms import ArquivoGuardadoForm, DocumentoForm
from documentos.models import Documento
from pacientes.models import Paciente
from prontuarios import orientacoes as orientacoes_do_prontuario
from prontuarios import servicos as prontuarios
from prontuarios.forms import FolhaDoProntuarioForm


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
        documentos = list(servicos.documentos(paciente=paciente))
        contexto.update(grupos=_grupos(), paciente=paciente, documentos=documentos,
                        # ADR-112: o que veio de fora aparece na mesma aba — a promessa é "tudo num lugar só".
                        arquivos=guarda.do_paciente(paciente) if paciente else [],
                        form_arquivo=ArquivoGuardadoForm(),
                        rascunhos=sum(1 for d in documentos if d.rascunho),
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


# --- O prontuário geral do paciente (ADR-079, ADR-080) -------------------------------------------------------------
#
# Fica nesta aba porque é **documento**: o que se entrega ao paciente ou a quem solicitar. Os registros de sessão
# continuam na aba Prontuários, e é de lá que vem a evolução. `documentos` lê `prontuarios`; o contrário não existe.

def _contexto_do_prontuario() -> dict:
    return dict(
        grupos=_grupos(), orientacoes=orientacoes_do_prontuario.ORIENTACOES, resumo=orientacoes_do_prontuario.RESUMO,
        antes=orientacoes_do_prontuario.ANTES, titulo_da_folha=orientacoes_do_prontuario.TITULO,
        versao_da_norma=orientacoes_do_prontuario.VERSAO_DA_NORMA,
        resolucao=orientacoes_do_prontuario.RESOLUCAO_01_2009, manual=orientacoes_do_prontuario.MANUAL_CFP,
        pacientes=Paciente.objects.order_by("nome"))


class EscolherProntuario(LoginRequiredMixin, TemplateView):
    """A sub-aba sem paciente: a orientação do CFP e o seletor. Com `?paciente=`, leva direto à folha."""

    template_name = "documentos/prontuario.html"

    def get(self, request, *args, **kwargs):
        paciente = _paciente_do_pedido(request.GET.get("paciente"))
        if paciente is not None:
            return redirect("documentos:prontuario", pk=paciente.pk)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), **_contexto_do_prontuario(), "paciente": None}


class ProntuarioGeral(LoginRequiredMixin, FormView):
    """As quatro partes da Res. CFP nº 001/2009 numa folha. Demanda e encerramento se escrevem aqui; a evolução
    é montada com os registros de sessão confirmados, e só se altera na aba Prontuários."""

    form_class = FolhaDoProntuarioForm
    template_name = "documentos/prontuario.html"

    def paciente(self) -> Paciente:
        if not hasattr(self, "_paciente"):
            self._paciente = get_object_or_404(Paciente.objects.prefetch_related("responsaveis"), pk=self.kwargs["pk"])
        return self._paciente

    def folha(self):
        if not hasattr(self, "_folha"):
            self._folha = prontuarios.folha_do_prontuario(self.paciente())
        return self._folha

    def get(self, request, *args, **kwargs):
        resposta = super().get(request, *args, **kwargs)
        auditoria.registrar(auditoria.Acao.VER, self.folha().ficha or self.paciente())
        return resposta

    def get_initial(self):
        return {"demanda": self.folha().demanda, "encerramento": self.folha().encerramento}

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(_contexto_do_prontuario(), paciente=self.paciente(), folha=self.folha())
        return contexto

    def form_valid(self, form):
        paciente = self.paciente()
        try:
            gravou = prontuarios.salvar_folha(paciente, demanda=form.cleaned_data["demanda"],
                                              encerramento=form.cleaned_data["encerramento"])
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        # Salvar e baixar: o arquivo sai com o que está na folha agora (ADR-078).
        if self.request.POST.get("acao") in exportacao.GERADORES:
            return redirect("documentos:baixar_prontuario", pk=paciente.pk, formato=self.request.POST["acao"])
        messages.success(self.request, "Prontuário salvo." if gravou else "Nada mudou no prontuário.")
        return redirect("documentos:prontuario", pk=paciente.pk)


class BaixarProntuario(LoginRequiredMixin, View):
    """O prontuário geral em PDF ou DOCX (ADR-078) — a cópia a que a pessoa atendida tem direito.

    Exportar entra na trilha de auditoria (ADR-057): é quando o dado mais sensível do produto deixa o sistema.
    """

    def get(self, request, *args, **kwargs):
        gerador = exportacao.GERADORES.get(self.kwargs["formato"])
        if gerador is None:
            raise Http404("Formato desconhecido.")
        paciente = get_object_or_404(Paciente.objects.prefetch_related("responsaveis"), pk=self.kwargs["pk"])
        gerar, tipo = gerador
        folha = {**prontuarios.folha_para_arquivo(paciente, request.user), "timbre": exportacao.timbre_de(request.user)}
        auditoria.registrar(auditoria.Acao.EXPORTAR, prontuarios.ficha_de(paciente) or paciente)
        nome = slugify(f"prontuario {paciente.nome}") or "prontuario"
        resposta = HttpResponse(gerar(folha), content_type=tipo)
        resposta["Content-Disposition"] = f'attachment; filename="{nome}.{self.kwargs["formato"]}"'
        return resposta


class GuardarArquivo(LoginRequiredMixin, FormView):
    """Sobe um arquivo feito fora do sistema e o prende ao paciente (ADR-112).

    A tela de destino é a aba de Documentos dele, com ou sem erro: é lá que o arquivo aparece, e mandar para outro
    lugar faria procurar o que acabou de guardar.
    """

    form_class = ArquivoGuardadoForm
    template_name = "documentos/aba.html"

    def paciente(self) -> Paciente:
        if not hasattr(self, "_paciente"):
            self._paciente = get_object_or_404(Paciente, pk=self.kwargs["paciente_pk"])
        return self._paciente

    def destino(self) -> str:
        return f"{reverse('documentos:aba')}?paciente={self.paciente().pk}"

    def form_valid(self, form):
        dados = form.cleaned_data
        try:
            recebido = guarda.conferir(self.request.FILES.get("arquivo"))
            guarda.guardar(self.paciente(), recebido, titulo=dados["titulo"], tipo=dados["tipo"],
                           restrito=dados["restrito"])
        except ValidationError as erro:
            form.add_error("arquivo" if "arquivo" in str(erro.messages[0]).lower() else None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, "Arquivo guardado.")
        return redirect(self.destino())

    def form_invalid(self, form):
        # Sem `render_to_response` da própria view: a aba precisa do contexto dela inteiro para desenhar.
        for erro in form.errors.values():
            messages.error(self.request, erro[0])
        return redirect(self.destino())


class BaixarArquivo(LoginRequiredMixin, View):
    """Devolve os bytes guardados. `Content-Disposition` com o nome já limpo em `guarda._nome_seguro`."""

    def get(self, request, *args, **kwargs):
        arquivo = get_object_or_404(ArquivoGuardado, pk=self.kwargs["pk"])
        resposta = HttpResponse(guarda.conteudo(arquivo), content_type=arquivo.tipo_mime)
        resposta["Content-Disposition"] = f'attachment; filename="{arquivo.nome_do_arquivo}"'
        return resposta


class ExcluirArquivo(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        arquivo = get_object_or_404(ArquivoGuardado, pk=self.kwargs["pk"])
        paciente_pk = arquivo.paciente_id
        arquivo.delete()      # o conteúdo morre junto, por CASCADE
        messages.success(request, "Arquivo excluído.")
        return redirect(f"{reverse('documentos:aba')}?paciente={paciente_pk}")
