from django.urls import path

from documentos import views

app_name = "documentos"

urlpatterns = [
    path("", views.Aba.as_view(), name="aba"),
    path("modelos/<slug:codigo>/", views.NovoDocumento.as_view(), name="modelo"),
    path("<int:pk>/", views.EditarDocumento.as_view(), name="editar"),
    path("<int:pk>/imprimir/", views.Imprimir.as_view(), name="imprimir"),
    path("<int:pk>/baixar/<str:formato>/", views.Baixar.as_view(), name="baixar"),
    path("<int:pk>/excluir/", views.ExcluirRascunho.as_view(), name="excluir"),
    path("<int:pk>/duplicar/", views.Duplicar.as_view(), name="duplicar"),
]
