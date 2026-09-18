from django.urls import path

from documentos import views

app_name = "documentos"

urlpatterns = [
    path("", views.Aba.as_view(), name="aba"),
    path("modelos/<slug:codigo>/", views.NovoDocumento.as_view(), name="modelo"),
    path("prontuario/", views.EscolherProntuario.as_view(), name="escolher_prontuario"),
    path("prontuario/<int:pk>/", views.ProntuarioGeral.as_view(), name="prontuario"),
    path("prontuario/<int:pk>/baixar/<str:formato>/", views.BaixarProntuario.as_view(), name="baixar_prontuario"),
    path("<int:pk>/", views.EditarDocumento.as_view(), name="editar"),
    path("<int:pk>/imprimir/", views.Imprimir.as_view(), name="imprimir"),
    path("<int:pk>/baixar/<str:formato>/", views.Baixar.as_view(), name="baixar"),
    path("<int:pk>/excluir/", views.ExcluirRascunho.as_view(), name="excluir"),
    path("<int:pk>/duplicar/", views.Duplicar.as_view(), name="duplicar"),
]
