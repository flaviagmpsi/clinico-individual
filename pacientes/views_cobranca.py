"""Mudar o valor ou a forma de cobrança de quem já está cadastrado.

Módulo separado de `views.py` porque a regra tem uma consequência que a tela precisa **mostrar**
antes de gravar: a troca não vale na hora, vale no dia 1º do mês seguinte
(`servicos.trocar_condicao`). Uma tela que só dissesse "cobrança atualizada" deixaria o psicólogo
achando que a sessão de amanhã já sai pelo valor novo.
"""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import FormView

from pacientes.forms import TrocaCobrancaForm
from pacientes.models import Paciente
from pacientes.servicos import caso_individual_de, primeiro_dia_do_mes_seguinte, trocar_condicao


class TrocarCobranca(LoginRequiredMixin, FormView):
    form_class = TrocaCobrancaForm
    template_name = "pacientes/cobranca.html"

    def caso(self):
        # Buscado sob demanda, depois do `LoginRequiredMixin`: no `dispatch` o anônimo receberia um
        # erro de escopo em vez de ser mandado para o login.
        if not hasattr(self, "_caso"):
            self.paciente = get_object_or_404(Paciente, pk=self.kwargs["pk"])
            self._caso = caso_individual_de(self.paciente)
            if self._caso is None:
                raise Http404("Paciente sem atendimento individual.")
        return self._caso

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["dia_vencimento_padrao"] = self.request.user.dia_vencimento_mensalidade
        kwargs["tipo_vencimento_padrao"] = self.request.user.tipo_vencimento_mensalidade
        return kwargs

    def get_initial(self):
        condicao = self.caso().condicao_vigente()
        if condicao is None:
            return {}
        inicial = {"modalidade": condicao.modalidade, "valor": condicao.valor}
        if condicao.dia_vencimento:  # por sessão não tem dia: fica o padrão do perfil, para quem trocar para mensal
            inicial["dia_vencimento"] = condicao.dia_vencimento
            inicial["tipo_vencimento"] = condicao.tipo_vencimento
        return inicial

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        caso = self.caso()
        vigente = caso.condicao_vigente()
        inicio = primeiro_dia_do_mes_seguinte() if vigente else None
        contexto.update(
            paciente=self.paciente,
            vigente=vigente,
            agendada=caso.proxima_condicao(),
            inicio=inicio,
            fim_da_atual=inicio - timedelta(days=1) if inicio else None,
        )
        return contexto

    def form_valid(self, form):
        condicao = trocar_condicao(self.caso(), **form.condicao())
        messages.success(
            self.request,
            f"Nova cobrança registrada. Vale a partir de {condicao.vigente_desde:%d/%m/%Y}.")
        return redirect("pacientes:detalhe", pk=self.paciente.pk)
