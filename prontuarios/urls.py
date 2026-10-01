from django.urls import path

from prontuarios import views

app_name = "prontuarios"

urlpatterns = [
    path("", views.ListaProntuarios.as_view(), name="lista"),
    path("anamnese/<int:pk>/", views.AnamneseDoPaciente.as_view(), name="anamnese"),
    path("<int:consulta_pk>/<int:paciente_pk>/", views.EscreverProntuario.as_view(), name="escrever"),
    path("<int:consulta_pk>/<int:paciente_pk>/descartar/", views.DescartarRascunho.as_view(), name="descartar"),
    # ADR-111: as duas chamadas da escrita assistida. Respondem JSON — a tela não recarrega enquanto a IA pensa.
    path("<int:consulta_pk>/<int:paciente_pk>/transcrever/", views.TranscreverRelato.as_view(), name="transcrever"),
    path("<int:consulta_pk>/<int:paciente_pk>/redigir/", views.RedigirRegistro.as_view(), name="redigir"),
]
