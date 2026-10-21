"""Telas de "Outros ganhos" — renda do psicólogo fora da clínica (ADR-136).

Não filtram por psicólogo: o `TenantManager` faz isso. Não exigem o controle de despesas ligado — ganho é ganho,
e todo mundo tem direito de ver quanto recebe de verdade no mês.
"""

from datetime import date

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, TemplateView, UpdateView

from financeiro import receitas_externas
from financeiro.forms import ReceitaExternaForm
from financeiro.models import ReceitaExterna
from financeiro.views_despesas import mes_do_pedido, navegacao

ZERO = receitas_externas.ZERO


class OutrosGanhos(LoginRequiredMixin, TemplateView):
    template_name = "financeiro/outros_ganhos.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        inicio = mes_do_pedido(self.request)
        ocorrencias = receitas_externas.receitas_do_mes(inicio.year, inicio.month)
        contexto.update(
            navegacao(inicio), aba="outros_ganhos", ocorrencias=ocorrencias,
            total=sum((o.valor for o in ocorrencias), ZERO),
            recebido=sum((o.valor for o in ocorrencias if o.recebida), ZERO),
            a_receber=sum((o.valor for o in ocorrencias if not o.recebida), ZERO))
        return contexto


class _EscreverReceita(LoginRequiredMixin):
    model = ReceitaExterna
    form_class = ReceitaExternaForm
    template_name = "financeiro/receita_externa_form.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "aba": "outros_ganhos"}

    def get_success_url(self):
        return f"{reverse('financeiro:outros_ganhos')}?mes={self.object.vencimento:%Y-%m}"


class NovaReceita(_EscreverReceita, CreateView):
    def get_initial(self):
        return {"vencimento": timezone.localdate()}

    def form_valid(self, form):
        messages.success(self.request, f"Ganho cadastrado: {form.instance.descricao}.")
        return super().form_valid(form)


class EditarReceita(_EscreverReceita, UpdateView):
    def form_valid(self, form):
        messages.success(self.request, "Ganho atualizado.")
        return super().form_valid(form)


class _AcaoNaReceita(LoginRequiredMixin, View):
    """Tudo por POST, com o mês vindo do formulário — é dele que a tela volta para o lugar certo."""

    http_method_names = ["post"]

    def mes(self) -> date:
        try:
            ano, mes = (int(parte) for parte in self.request.POST.get("mes", "").split("-"))
            return date(ano, mes, 1)
        except ValueError:
            hoje = timezone.localdate()
            return date(hoje.year, hoje.month, 1)

    def agir(self, receita: ReceitaExterna, mes: date) -> str:
        raise NotImplementedError

    def post(self, request, *args, **kwargs):
        receita = get_object_or_404(ReceitaExterna, pk=self.kwargs["pk"])
        mes = self.mes()
        try:
            messages.success(request, self.agir(receita, mes))
        except ValidationError as erro:
            messages.error(request, erro.messages[0])
        return redirect(f"{reverse('financeiro:outros_ganhos')}?mes={mes:%Y-%m}")


class ReceberReceita(_AcaoNaReceita):
    def agir(self, receita, mes):
        informada = self.request.POST.get("recebido_em", "")
        try:
            recebido_em = date.fromisoformat(informada) if informada else None
        except ValueError:
            raise ValidationError("Data de recebimento inválida.")
        receitas_externas.receber(receita, mes, recebido_em=recebido_em)
        return f"{receita.descricao}: marcado como recebido."


class DesfazerRecebimento(_AcaoNaReceita):
    def agir(self, receita, mes):
        receitas_externas.desfazer_recebimento(receita, mes)
        return f"{receita.descricao}: voltou a ficar a receber."


class EncerrarReceita(_AcaoNaReceita):
    def agir(self, receita, mes):
        receitas_externas.encerrar(receita, mes)
        return f"{receita.descricao}: {mes:%m/%Y} é o último mês em que ele aparece."


class ExcluirReceita(_AcaoNaReceita):
    def agir(self, receita, mes):
        descricao = receita.descricao
        receitas_externas.excluir(receita)
        return f"Ganho excluído: {descricao}."
