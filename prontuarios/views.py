"""Telas do prontuário escrito à mão (ADR-064).

Nenhuma view filtra por psicólogo: o `TenantManager` faz isso, e um id alheio na URL dá 404. Abrir um prontuário
que existe entra na trilha de auditoria (ADR-057).
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import FormView, TemplateView

from atendimentos.models import Consulta
from core import auditoria
from pacientes.models import Paciente
from prontuarios import anamneses, ia, redacao, servicos
from prontuarios.forms import AnamneseForm, ProntuarioForm, TemaDeAnamneseForm
from prontuarios.models import Anamnese, TemaDeAnamnese, VersaoProntuario


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
        contexto.update(registro=self.registro(), consulta=consulta, paciente=paciente,
                        # ADR-111: o recurso só aparece com as duas chaves — a do servidor e a da psicóloga.
                        ia_ligada=ia.disponivel() and self.request.user.usa_ia_no_prontuario,
                        pontos=ia.PONTOS, aviso_de_sigilo=ia.AVISO_DE_SIGILO,
                        ia_minutos_maximos=settings.IA_MINUTOS_MAXIMOS)
        return contexto

    def form_valid(self, form):
        consulta, paciente = self.alvo()
        dados = form.cleaned_data
        confirmando = self.request.POST.get("acao") == "confirmar"
        acao = servicos.confirmar if confirmando else servicos.salvar_rascunho
        try:
            acao(consulta, paciente, texto=dados["texto"])   # `origem` fica como estava (ADR-111)
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


class _ComIA(LoginRequiredMixin, _ComAlvo, View):
    """Base das duas chamadas de IA (ADR-111): as duas respondem JSON, e as duas recusam pelos mesmos motivos."""

    http_method_names = ["post"]

    def recusar(self, recado: str, status: int = 400) -> JsonResponse:
        return JsonResponse({"erro": recado}, status=status)

    def post(self, request, *args, **kwargs):
        if not request.user.usa_ia_no_prontuario:
            return self.recusar("A escrita assistida está desligada. Ligue em Configurações.", status=403)
        if not ia.disponivel():
            return self.recusar("Este servidor não tem chave de IA configurada.", status=503)
        try:
            return self.responder(request)
        except ia.IAIndisponivel as erro:
            # Falha de IA nunca derruba a tela: o registro escrito à mão continua ali, intacto.
            return self.recusar(str(erro), status=502)


class TranscreverRelato(_ComIA):
    """Áudio → texto, já sem os nomes que o sistema conhece. O áudio **não** é guardado em lugar nenhum."""

    def responder(self, request) -> JsonResponse:
        audio = request.FILES.get("audio")
        if audio is None:
            return self.recusar("Nenhum áudio chegou.")
        _, paciente = self.alvo()
        texto = redacao.transcrever_sessao(audio, paciente, request.user, nome=audio.name or "sessao.webm")
        if not texto:
            return self.recusar("Não consegui entender o áudio. Grave de novo, mais perto do microfone.")
        return JsonResponse({"texto": texto})


class RedigirRegistro(_ComIA):
    """Relato → corpo do registro de evolução, gravado como rascunho para o psicólogo revisar."""

    def responder(self, request) -> JsonResponse:
        relato = (request.POST.get("relato") or "").strip()
        if not relato:
            return self.recusar("Escreva ou grave o relato da sessão antes de gerar o registro.")
        # ADR-114: teto mensal por conta. Fica aqui, e não na transcrição, porque é a síntese que custa caro —
        # e porque recusar depois de a pessoa já ter gravado seria a pior hora de avisar.
        if redacao.passou_do_teto():
            return self.recusar(
                f"Você chegou ao limite de {redacao.teto_do_mes()} registros com IA neste mês. "
                "O registro escrito à mão continua funcionando, e o limite volta no dia 1º.", status=429)
        consulta, paciente = self.alvo()
        texto = redacao.redigir(relato, consulta, paciente, request.user)
        servicos.salvar_rascunho(consulta, paciente, texto=texto,
                                 origem=VersaoProntuario.Origem.IA)
        return JsonResponse({"texto": texto})


class AnamneseDoPaciente(LoginRequiredMixin, FormView):
    """A sub-aba de anamnese na ficha do paciente (ADR-085), por blocos que o psicólogo edita (ADR-101).

    Opcional: enquanto ninguém escreve, nada é gravado. A mesma tela é onde o roteiro se organiza — acrescentar,
    arquivar e mover tema acontecem aqui, porque é aqui que ele percebe o que falta.
    """

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
        return {**super().get_form_kwargs(), "blocos": anamneses.blocos(self.anamnese())}

    def get_context_data(self, **kwargs):
        contexto = {**super().get_context_data(**kwargs), "paciente": self.paciente(), "anamnese": self.anamnese()}
        contexto.setdefault("tema_novo", TemaDeAnamneseForm())
        contexto["arquivados"] = TemaDeAnamnese.objects.filter(arquivado=True)
        return contexto

    def post(self, request, *args, **kwargs):
        acao = request.POST.get("acao", "")
        if acao.startswith("tema:"):
            return self._mexer_no_roteiro(request, acao)
        return super().post(request, *args, **kwargs)

    def _mexer_no_roteiro(self, request, acao: str):
        """`tema:novo`, `tema:arquivar:<pk>`, `tema:voltar:<pk>`, `tema:subir:<pk>`, `tema:descer:<pk>`."""
        partes = acao.split(":")
        if partes[1] == "novo":
            formulario = TemaDeAnamneseForm(request.POST)
            if formulario.is_valid():
                try:
                    tema = anamneses.criar_tema(**formulario.cleaned_data)
                except ValidationError as erro:
                    formulario.add_error("titulo", erro.messages[0])
                    return self.render_to_response(self.get_context_data(form=self.get_form(), tema_novo=formulario))
                messages.success(request, f"Tema “{tema.titulo}” acrescentado ao seu roteiro de anamnese.")
            else:
                return self.render_to_response(self.get_context_data(form=self.get_form(), tema_novo=formulario))
        else:
            tema = get_object_or_404(TemaDeAnamnese, pk=int(partes[2]))
            if partes[1] in ("arquivar", "voltar"):
                anamneses.arquivar(tema, arquivado=partes[1] == "arquivar")
                messages.success(request, f"Tema “{tema.titulo}” {"arquivado" if tema.arquivado else "de volta ao roteiro"}.")
            else:
                anamneses.mover(tema, para_cima=partes[1] == "subir")
        return redirect("prontuarios:anamnese", pk=self.paciente().pk)

    def form_valid(self, form):
        anamnese = anamneses.salvar(self.paciente(), form.textos())
        if anamnese is None:
            messages.info(self.request, "Nada escrito ainda — a anamnese continua em branco.")
        else:
            messages.success(self.request, "Anamnese salva.")
        return redirect("prontuarios:anamnese", pk=self.paciente().pk)

