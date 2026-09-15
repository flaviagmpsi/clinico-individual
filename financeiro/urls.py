from django.urls import path

from financeiro import views

app_name = "financeiro"

urlpatterns = [
    path("", views.MesFinanceiro.as_view(), name="mes"),
    path("mensalidade/<int:caso_pk>/<int:ano>/<int:mes>/", views.PagarMensalidade.as_view(), name="pagar_mensalidade"),
    path("sessao/<int:consulta_pk>/", views.PagarSessao.as_view(), name="pagar_sessao"),
    path("pagamentos/<int:pk>/excluir/", views.ExcluirPagamento.as_view(), name="excluir"),
]
