from django.urls import path

from prontuarios import views

app_name = "prontuarios"

urlpatterns = [
    path("", views.ListaProntuarios.as_view(), name="lista"),
    path("paciente/", views.AbrirProntuario.as_view(), name="abrir"),
    path("paciente/<int:pk>/", views.ProntuarioDoPaciente.as_view(), name="paciente"),
    path("paciente/<int:pk>/baixar/<str:formato>/", views.BaixarProntuario.as_view(), name="baixar"),
    path("<int:consulta_pk>/<int:paciente_pk>/", views.EscreverProntuario.as_view(), name="escrever"),
    path("<int:consulta_pk>/<int:paciente_pk>/descartar/", views.DescartarRascunho.as_view(), name="descartar"),
]
