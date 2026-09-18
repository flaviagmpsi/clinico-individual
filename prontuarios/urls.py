from django.urls import path

from prontuarios import views

app_name = "prontuarios"

urlpatterns = [
    path("", views.ListaProntuarios.as_view(), name="lista"),
    path("<int:consulta_pk>/<int:paciente_pk>/", views.EscreverProntuario.as_view(), name="escrever"),
    path("<int:consulta_pk>/<int:paciente_pk>/descartar/", views.DescartarRascunho.as_view(), name="descartar"),
]
