from django.urls import path

from financeiro import views, views_despesas, views_receitas

app_name = "financeiro"

urlpatterns = [
    path("", views.MesFinanceiro.as_view(), name="mes"),
    path("mensalidade/<int:caso_pk>/<int:ano>/<int:mes>/", views.PagarMensalidade.as_view(), name="pagar_mensalidade"),
    path("sessao/<int:consulta_pk>/", views.PagarSessao.as_view(), name="pagar_sessao"),
    path("mensalidade/<int:caso_pk>/<int:ano>/<int:mes>/quitar/", views.QuitarMensalidade.as_view(), name="quitar_mensalidade"),
    path("mensalidade/<int:caso_pk>/<int:ano>/<int:mes>/reabrir/", views.ReabrirMensalidade.as_view(), name="reabrir_mensalidade"),
    path("pagamentos/<int:pk>/editar/", views.EditarPagamento.as_view(), name="editar_pagamento"),
    path("pagamentos/<int:pk>/excluir/", views.ExcluirPagamento.as_view(), name="excluir"),
    path("despesas/", views_despesas.Despesas.as_view(), name="despesas"),
    path("despesas/nova/", views_despesas.NovaDespesa.as_view(), name="despesa_nova"),
    path("despesas/<int:pk>/editar/", views_despesas.EditarDespesa.as_view(), name="despesa_editar"),
    path("despesas/<int:pk>/pagar/", views_despesas.PagarDespesa.as_view(), name="despesa_pagar"),
    path("despesas/<int:pk>/desfazer/", views_despesas.DesfazerPagamentoDeDespesa.as_view(), name="despesa_desfazer"),
    path("despesas/<int:pk>/encerrar/", views_despesas.EncerrarDespesa.as_view(), name="despesa_encerrar"),
    path("despesas/<int:pk>/excluir/", views_despesas.ExcluirDespesa.as_view(), name="despesa_excluir"),
    path("fluxo/", views_despesas.FluxoDeCaixa.as_view(), name="fluxo"),
    path("outros-ganhos/", views_receitas.OutrosGanhos.as_view(), name="outros_ganhos"),
    path("outros-ganhos/novo/", views_receitas.NovaReceita.as_view(), name="receita_nova"),
    path("outros-ganhos/<int:pk>/editar/", views_receitas.EditarReceita.as_view(), name="receita_editar"),
    path("outros-ganhos/<int:pk>/receber/", views_receitas.ReceberReceita.as_view(), name="receita_receber"),
    path("outros-ganhos/<int:pk>/desfazer/", views_receitas.DesfazerRecebimento.as_view(), name="receita_desfazer"),
    path("outros-ganhos/<int:pk>/encerrar/", views_receitas.EncerrarReceita.as_view(), name="receita_encerrar"),
    path("outros-ganhos/<int:pk>/excluir/", views_receitas.ExcluirReceita.as_view(), name="receita_excluir"),
]
