from django.urls import path

from financeiro import views, views_despesas

app_name = "financeiro"

urlpatterns = [
    path("", views.MesFinanceiro.as_view(), name="mes"),
    path("mensalidade/<int:caso_pk>/<int:ano>/<int:mes>/", views.PagarMensalidade.as_view(), name="pagar_mensalidade"),
    path("sessao/<int:consulta_pk>/", views.PagarSessao.as_view(), name="pagar_sessao"),
    path("pagamentos/<int:pk>/excluir/", views.ExcluirPagamento.as_view(), name="excluir"),
    path("despesas/", views_despesas.Despesas.as_view(), name="despesas"),
    path("despesas/nova/", views_despesas.NovaDespesa.as_view(), name="despesa_nova"),
    path("despesas/<int:pk>/editar/", views_despesas.EditarDespesa.as_view(), name="despesa_editar"),
    path("despesas/<int:pk>/pagar/", views_despesas.PagarDespesa.as_view(), name="despesa_pagar"),
    path("despesas/<int:pk>/desfazer/", views_despesas.DesfazerPagamentoDeDespesa.as_view(), name="despesa_desfazer"),
    path("despesas/<int:pk>/encerrar/", views_despesas.EncerrarDespesa.as_view(), name="despesa_encerrar"),
    path("despesas/<int:pk>/excluir/", views_despesas.ExcluirDespesa.as_view(), name="despesa_excluir"),
    path("fluxo/", views_despesas.FluxoDeCaixa.as_view(), name="fluxo"),
]
