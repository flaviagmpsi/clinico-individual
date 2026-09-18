"""Telas do convite de cadastro (ADR-081): as do psicólogo, e a única tela pública do produto com dado de paciente.

⚠️ `CadastroPeloPaciente` é **anônima**. Ela dispensa o escopo (`core.escopo.dispensa_escopo`) e corre sob
`hamilton_web`, que não tem grant em tabela clínica: a view só alcança a linha do convite cujo token foi
apresentado, e só para respondê-la uma vez. Se alguém um dia escrever aqui uma consulta a `Paciente`, o Postgres
recusa — barulhento, e do lado certo do erro.
"""

from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import FormView, TemplateView

from core.escopo import dispensa_escopo
from pacientes import convites
from pacientes.forms_convite import GENEROS_SUGERIDOS, CadastroPeloPacienteForm
from pacientes.models import ConviteDeCadastro

_CHAVE_DO_LINK = "convite_recem_gerado"


# --- O psicólogo ----------------------------------------------------------------------------------------------------

class Convites(LoginRequiredMixin, TemplateView):
    """Os links gerados: o que espera resposta, o que espera revisão, o que já virou paciente."""

    template_name = "pacientes/convites.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        # O link em claro só existe agora, logo depois de gerar: no banco fica o hash. Sai da sessão ao ser lido.
        recem = self.request.session.pop(_CHAVE_DO_LINK, None)
        if recem:
            link = self.request.build_absolute_uri(reverse("cadastro_pelo_paciente", args=[recem["token"]]))
            mensagem = (f"Olá! Para começarmos, preencha seu cadastro neste link: {link} "
                        f"Ele vale por {convites.VALIDADE.days} dias e só pode ser enviado uma vez.")
            contexto.update(link=link, rotulo_do_link=recem.get("rotulo", ""),
                            whatsapp=f"https://wa.me/?text={quote(mensagem)}")
        contexto.update(convites=convites.convites(), validade=convites.VALIDADE.days)
        return contexto


class GerarConvite(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        rotulo = request.POST.get("rotulo", "")[:120]
        _, token = convites.gerar_convite(rotulo)
        request.session[_CHAVE_DO_LINK] = {"token": token, "rotulo": rotulo}
        return redirect("pacientes:convites")


class CancelarConvite(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        convite = get_object_or_404(ConviteDeCadastro, pk=self.kwargs["pk"])
        try:
            convites.cancelar(convite)
        except ValidationError as erro:
            messages.error(request, erro.messages[0])
        else:
            messages.success(request, "Link cancelado. O que tinha sido respondido nele foi apagado.")
        return redirect("pacientes:convites")


# --- O visitante ----------------------------------------------------------------------------------------------------

@method_decorator(dispensa_escopo, name="dispatch")
class CadastroPeloPaciente(FormView):
    """`/cadastro/<token>/` — o paciente preenche, e a resposta fica esperando a revisão do psicólogo."""

    form_class = CadastroPeloPacienteForm
    template_name = "pacientes/cadastro_publico.html"

    def dispatch(self, request, *args, **kwargs):
        self.convite = convites.apresentar(self.kwargs["token"])
        resposta = self._fora_do_ar() or super().dispatch(request, *args, **kwargs)
        # O token está na URL: nada de mandá-la como referência para CDN ou ViaCEP, nem de guardar a página.
        resposta["Referrer-Policy"] = "no-referrer"
        resposta["Cache-Control"] = "no-store"
        resposta["X-Robots-Tag"] = "noindex, nofollow"
        return resposta

    def _fora_do_ar(self):
        """A mesma página serve os três becos: link que não existe, link vencido e link já usado."""
        if self.convite is None:
            estado, codigo = "invalido", 404
        elif self.convite.respondido_em is not None or self.convite.aceito_em is not None:
            estado, codigo = "respondido", 200
        elif self.convite.expira_em <= timezone.now():
            estado, codigo = "expirado", 410
        else:
            return None
        return self._encerrada(estado, codigo)

    def _encerrada(self, estado: str, codigo: int = 200):
        resposta = self.response_class(
            request=self.request, template="pacientes/cadastro_publico_fim.html", status=codigo,
            context={"estado": estado, "psicologo": getattr(self.convite, "psicologo", None), "esconder_barra": True})
        return resposta.render()

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(psicologo=self.convite.psicologo, generos=GENEROS_SUGERIDOS, esconder_barra=True)
        return contexto

    def form_valid(self, form):
        if not convites.responder(self.convite, form.respostas()):
            return self._encerrada("respondido")
        return self._encerrada("enviado")
