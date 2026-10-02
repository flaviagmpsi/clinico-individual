"""Telas do financeiro: o mês, o registro de pagamento e o lembrete (ADR-062, ADR-063).

Nenhuma view filtra por psicólogo: o `TenantManager` faz isso, e um id alheio na URL dá 404. Toda busca de
objeto pela URL acontece depois do `LoginRequiredMixin`.
"""

from datetime import date

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import FormView, TemplateView

from atendimentos.models import Consulta
from financeiro import servicos
from financeiro.forms import PagamentoForm
from financeiro.models import Pagamento
from pacientes.models import Caso


def _url_do_mes(dia: date) -> str:
    return f"{reverse('financeiro:mes')}?mes={dia:%Y-%m}"


class MesFinanceiro(LoginRequiredMixin, TemplateView):
    template_name = "financeiro/mes.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        hoje = timezone.localdate()
        try:
            ano, mes = (int(parte) for parte in self.request.GET.get("mes", "").split("-"))
            inicio = date(ano, mes, 1)
        except ValueError:
            inicio = date(hoje.year, hoje.month, 1)
        fim = servicos.ultimo_dia(inicio.year, inicio.month)

        todas = servicos.cobrancas_do_mes(inicio.year, inicio.month)
        # ADR-092: uma tabela só. Primeiro o que pede ação (vencida), depois o que tem prazo correndo, por fim o pago.
        grupos = {"vencidas": [c for c in todas if c.vencida(hoje)],
                  "pendentes": [c for c in todas if not c.quitada and not c.vencida(hoje)],
                  "pagas": [c for c in todas if c.quitada]}
        filtro = self.request.GET.get("situacao", "")
        cobrancas = (grupos.get(filtro) if filtro in grupos
                     else grupos["vencidas"] + grupos["pendentes"] + grupos["pagas"])
        # O que entrou neste mês mas é cobrança de outro: não repete a tabela, só avisa onde está.
        de_outros_meses: dict = {}
        recebidos = Pagamento.objects.filter(data__gte=inicio, data__lte=fim).select_related("consulta")
        for pagamento in recebidos:
            referencia = pagamento.mes_referencia or timezone.localtime(pagamento.consulta.inicio).date().replace(day=1)
            if referencia != inicio:
                de_outros_meses[referencia] = de_outros_meses.get(referencia, 0) + pagamento.valor
        contexto.update(
            inicio=inicio, hoje=hoje, aba="receitas",
            anterior=servicos.mes_anterior(inicio), proximo=servicos.mes_seguinte(inicio),
            este=date(hoje.year, hoje.month, 1),
            cobrancas=cobrancas, filtro=filtro if filtro in grupos else "",
            contagem={nome: len(lista) for nome, lista in grupos.items()}, total_de_cobrancas=len(todas),
            devido=sum((c.devido for c in todas), 0), pago=sum((c.pago for c in todas), 0),
            saldo=sum((c.saldo for c in todas), 0),
            de_outros_meses=sorted(de_outros_meses.items()),
            # ADR-074: a tabela do mês já marca o que está pendente nele. Só entra à parte o que ela não
            # alcança — cobrança vencida de mês anterior que ninguém quitou.
            vencidas_anteriores=[c for c in servicos.pagamentos_vencidos(hoje) if c.vencimento < inicio],
        )
        return contexto


class _RegistrarPagamento(LoginRequiredMixin, FormView):
    form_class = PagamentoForm
    template_name = "financeiro/pagamento_form.html"

    def cobranca(self) -> servicos.Cobranca:
        raise NotImplementedError

    def get_initial(self):
        cobranca = self.cobranca()
        return {"valor": cobranca.saldo or cobranca.devido, "data": timezone.localdate()}

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["cobranca"] = self.cobranca()
        return contexto

    def registrar(self, dados):
        raise NotImplementedError

    def form_valid(self, form):
        cobranca = self.cobranca()
        try:
            self.registrar(form.cleaned_data)
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, f"Pagamento registrado: {cobranca.descricao.lower()} · {cobranca.caso}.")
        return redirect(_url_do_mes(cobranca.mes or cobranca.vencimento))


class PagarMensalidade(_RegistrarPagamento):
    def cobranca(self) -> servicos.Cobranca:
        if not hasattr(self, "_cobranca"):
            caso = get_object_or_404(Caso.objects.prefetch_related("pacientes"), pk=self.kwargs["caso_pk"])
            try:
                cobranca = servicos.mensalidade(caso, self.kwargs["ano"], self.kwargs["mes"])
            except ValueError:
                raise Http404("Mês inválido.")
            if cobranca is None:
                raise Http404("Não há mensalidade neste mês.")
            self._cobranca = cobranca
        return self._cobranca

    def registrar(self, dados):
        cobranca = self.cobranca()
        servicos.registrar_pagamento_mensalidade(
            cobranca.caso, ano=cobranca.mes.year, mes=cobranca.mes.month, valor=dados["valor"], data=dados["data"],
            forma=dados["forma"], observacao=dados["observacao"])


class PagarSessao(_RegistrarPagamento):
    def cobranca(self) -> servicos.Cobranca:
        if not hasattr(self, "_cobranca"):
            consulta = get_object_or_404(Consulta.objects.select_related("caso"), pk=self.kwargs["consulta_pk"])
            cobranca = servicos.sessao(consulta)
            if cobranca is None:
                raise Http404("Esta consulta não gera pagamento por sessão.")
            self._cobranca = cobranca
        return self._cobranca

    def registrar(self, dados):
        servicos.registrar_pagamento_sessao(
            self.cobranca().consulta, valor=dados["valor"], data=dados["data"], forma=dados["forma"],
            observacao=dados["observacao"])


class ExcluirPagamento(LoginRequiredMixin, View):
    """Registro feito por engano. Só por POST."""

    http_method_names = ["post"]

    def post(self, request, pk):
        pagamento = get_object_or_404(Pagamento.objects.select_related("consulta"), pk=pk)
        # Volta ao mês da **cobrança**, que é onde o pagamento aparece (ADR-092) — e não ao mês em que foi pago.
        mes = pagamento.mes_referencia or timezone.localtime(pagamento.consulta.inicio).date()
        servicos.excluir_pagamento(pagamento)
        messages.success(request, "Pagamento excluído. A cobrança voltou a ficar em aberto.")
        return redirect(_url_do_mes(mes))
