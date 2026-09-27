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

from financeiro import carne_leao, despesas, servicos
from indicadores import estatisticas, periodo
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


class _ExigeDespesas(LoginRequiredMixin):
    """ADR-100: desligado o controle de despesas, estas telas não existem — nem por link guardado."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.usa_despesas:
            messages.info(request, "O controle de despesas está desligado. Ligue aqui para usá-lo.")
            return redirect("contas:configuracoes")
        return super().dispatch(request, *args, **kwargs)


class Despesas(_ExigeDespesas, TemplateView):
    template_name = "financeiro/despesas.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        inicio = mes_do_pedido(self.request)
        ocorrencias = despesas.despesas_do_mes(inicio.year, inicio.month)
        contexto.update(
            navegacao(inicio), aba="despesas", ocorrencias=ocorrencias,
            total=sum((o.valor for o in ocorrencias), despesas.ZERO),
            pago=sum((o.valor for o in ocorrencias if o.paga), despesas.ZERO),
            a_pagar=sum((o.valor for o in ocorrencias if not o.paga), despesas.ZERO),
            # ADR-099: o que a Receita admite no livro-caixa, separado do que simplesmente saiu do caixa.
            dedutivel=sum((o.valor for o in ocorrencias if o.despesa.deduz), despesas.ZERO))
        return contexto


class _EscreverDespesa(_ExigeDespesas):
    model = Despesa
    form_class = DespesaForm
    template_name = "financeiro/despesa_form.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "aba": "despesas",
                "fonte_receita": carne_leao.FONTE_RECEITA, "fonte_rir": carne_leao.FONTE_RIR,
                "consultado_em": carne_leao.CONSULTADO_EM}

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


class _AcaoNaDespesa(_ExigeDespesas, View):
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


class FluxoDeCaixa(_ExigeDespesas, TemplateView):
    template_name = "financeiro/fluxo.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        inicio = mes_do_pedido(self.request)
        contexto.update(navegacao(inicio), aba="fluxo", fluxo=despesas.fluxo_de_caixa(inicio.year, inicio.month))
        # ADR-103: o resultado previsto — do mês e do ano — mora no financeiro, e não numa aba de estatísticas.
        contexto.update(periodo.contexto_do_seletor(self.request))
        previsto = estatisticas.resultado_previsto(contexto["periodo"])
        contexto.update(previsto=previsto, grafico={
            "meses": estatisticas.MESES, "mes_em_foco": contexto["periodo"].mes,
            "receitas_recebidas": [float(f.receitas_recebidas) for f in previsto.fluxos],
            "receitas_a_receber": [float(f.receitas_a_receber) for f in previsto.fluxos],
            "despesas_pagas": [float(f.despesas_pagas) for f in previsto.fluxos],
            "despesas_a_pagar": [float(f.despesas_a_pagar) for f in previsto.fluxos],
            "resultado": [float(f.resultado) for f in previsto.fluxos],
        })
        return contexto
