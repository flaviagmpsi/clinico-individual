"""Telas de despesas e do fluxo de caixa (ADR-083). Nenhuma filtra por psicólogo: o `TenantManager` faz isso."""

from datetime import date

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, TemplateView, UpdateView

from financeiro import despesas, servicos
from financeiro.forms import DespesaForm
from financeiro.models import Despesa


def mes_do_pedido(request) -> date:
    """`?mes=2026-09`; sem isso ou com lixo, o mês corrente."""
    hoje = timezone.localdate()
    try:
        ano, mes = (int(parte) for parte in request.GET.get("mes", "").split("-"))
        return date(ano, mes, 1)
    except ValueError:
        return date(hoje.year, hoje.month, 1)


def navegacao(inicio: date) -> dict:
    hoje = timezone.localdate()
    return dict(inicio=inicio, hoje=hoje, anterior=servicos.mes_anterior(inicio),
                proximo=servicos.mes_seguinte(inicio), este=date(hoje.year, hoje.month, 1))


def _voltar(nome: str, mes: date):
    return redirect(f"{reverse(nome)}?mes={mes:%Y-%m}")


class Despesas(LoginRequiredMixin, TemplateView):
    template_name = "financeiro/despesas.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        inicio = mes_do_pedido(self.request)
        ocorrencias = despesas.despesas_do_mes(inicio.year, inicio.month)
        contexto.update(
            navegacao(inicio), aba="despesas", ocorrencias=ocorrencias,
            total=sum((o.valor for o in ocorrencias), despesas.ZERO),
            pago=sum((o.valor for o in ocorrencias if o.paga), despesas.ZERO),
            a_pagar=sum((o.valor for o in ocorrencias if not o.paga), despesas.ZERO))
        return contexto


class _EscreverDespesa(LoginRequiredMixin):
    model = Despesa
    form_class = DespesaForm
    template_name = "financeiro/despesa_form.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "aba": "despesas"}

    def get_success_url(self):
        return f"{reverse('financeiro:despesas')}?mes={self.object.vencimento:%Y-%m}"


class NovaDespesa(_EscreverDespesa, CreateView):
    def get_initial(self):
        return {"vencimento": timezone.localdate()}

    def form_valid(self, form):
        messages.success(self.request, f"Despesa cadastrada: {form.instance.descricao}.")
        return super().form_valid(form)


class EditarDespesa(_EscreverDespesa, UpdateView):
    def form_valid(self, form):
        messages.success(self.request, "Despesa atualizada.")
        return super().form_valid(form)


class _AcaoNaDespesa(LoginRequiredMixin, View):
    """Tudo por POST, com o mês vindo do formulário — é dele que a tela volta para o lugar certo."""

    http_method_names = ["post"]

    def mes(self) -> date:
        try:
            ano, mes = (int(parte) for parte in self.request.POST.get("mes", "").split("-"))
            return date(ano, mes, 1)
        except ValueError:
            hoje = timezone.localdate()
            return date(hoje.year, hoje.month, 1)

    def agir(self, despesa: Despesa, mes: date) -> str:
        raise NotImplementedError

    def post(self, request, *args, **kwargs):
        despesa = get_object_or_404(Despesa, pk=self.kwargs["pk"])
        mes = self.mes()
        try:
            messages.success(request, self.agir(despesa, mes))
        except ValidationError as erro:
            messages.error(request, erro.messages[0])
        return _voltar("financeiro:despesas", mes)


class PagarDespesa(_AcaoNaDespesa):
    def agir(self, despesa, mes):
        informada = self.request.POST.get("pago_em", "")
        try:
            pago_em = date.fromisoformat(informada) if informada else None
        except ValueError:
            raise ValidationError("Data de pagamento inválida.")
        despesas.pagar(despesa, mes, pago_em=pago_em)
        return f"{despesa.descricao}: marcada como paga."


class DesfazerPagamentoDeDespesa(_AcaoNaDespesa):
    def agir(self, despesa, mes):
        despesas.desfazer_pagamento(despesa, mes)
        return f"{despesa.descricao}: voltou a ficar em aberto."


class EncerrarDespesa(_AcaoNaDespesa):
    def agir(self, despesa, mes):
        despesas.encerrar(despesa, mes)
        return f"{despesa.descricao}: {mes:%m/%Y} é o último mês em que ela aparece."


class ExcluirDespesa(_AcaoNaDespesa):
    def agir(self, despesa, mes):
        descricao = despesa.descricao
        despesas.excluir(despesa)
        return f"Despesa excluída: {descricao}."


class FluxoDeCaixa(LoginRequiredMixin, TemplateView):
    template_name = "financeiro/fluxo.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        inicio = mes_do_pedido(self.request)
        contexto.update(navegacao(inicio), aba="fluxo", fluxo=despesas.fluxo_de_caixa(inicio.year, inicio.month))
        return contexto
