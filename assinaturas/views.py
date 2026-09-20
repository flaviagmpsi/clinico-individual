"""As duas telas da assinatura: como começar (ou em que pé está) e o pagamento."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.views.generic import TemplateView

from assinaturas import servicos
from assinaturas.models import DIAS_DE_TESTE, Assinatura


class _TelaDeAssinatura(LoginRequiredMixin, TemplateView):
    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        assinatura = servicos.assinatura_atual()
        contexto.update(
            assinatura=assinatura, dias_de_teste=DIAS_DE_TESTE,
            valor_mensal=getattr(settings, "ASSINATURA_VALOR_MENSAL", None),
            # Sem assinatura que libere o sistema não há para onde ir: a barra lateral só mostraria portas trancadas.
            esconder_barra=assinatura is None or not assinatura.libera_o_sistema()
            or not self.request.user.cadastro_completo,
        )
        return contexto


class Plano(_TelaDeAssinatura):
    """Quem acabou de criar a conta escolhe aqui como começar; quem já escolheu vê em que pé está."""

    template_name = "assinaturas/plano.html"

    def post(self, request, *args, **kwargs):
        if request.POST.get("acao") != "teste":
            return redirect("assinaturas:pagamento")
        try:
            servicos.comecar_teste()
        except servicos.TesteJaUsado:
            messages.error(request, "O teste grátis desta conta já foi usado.")
            return redirect("assinaturas:plano")
        messages.success(request, f"Seu teste grátis de {DIAS_DE_TESTE} dias começou.")
        return redirect("painel")  # o quiz intercepta quem ainda não o respondeu (ADR-071)


class Pagamento(_TelaDeAssinatura):
    """A escolha do meio de pagamento — e, hoje, a confirmação **simulada**.

    Com o Asaas (S-01), o `post` deixa de ativar: ele cria o checkout hospedado e redireciona para a página do
    Asaas, onde o cartão é digitado. Quem ativa a assinatura passa a ser o webhook de pagamento confirmado.
    """

    template_name = "assinaturas/pagamento.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            assinatura = servicos.assinatura_atual()
            if assinatura is not None and assinatura.estado == Assinatura.Estado.ATIVA:
                return redirect("assinaturas:plano")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(meios=Assinatura.Meio.choices, simulado=servicos.pagamento_simulado())
        return contexto

    def post(self, request, *args, **kwargs):
        if not servicos.pagamento_simulado():
            raise Http404("A cobrança da assinatura ainda não está ligada.")
        meio = request.POST.get("meio")
        if meio not in Assinatura.Meio.values:
            messages.error(request, "Escolha o meio de pagamento.")
            return redirect("assinaturas:pagamento")
        servicos.ativar(meio, id_no_gateway="simulado")
        messages.success(request, "Pagamento confirmado (simulação). Sua assinatura está ativa.")
        return redirect("painel")
