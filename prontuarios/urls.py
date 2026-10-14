from django.urls import path

from prontuarios import views

app_name = "prontuarios"

urlpatterns = [
    path("", views.ListaProntuarios.as_view(), name="lista"),
    path("anamnese/<int:pk>/", views.AnamneseDoPaciente.as_view(), name="anamnese"),
    path("<int:consulta_pk>/<int:paciente_pk>/", views.EscreverProntuario.as_view(), name="escrever"),
    path("<int:consulta_pk>/<int:paciente_pk>/descartar/", views.DescartarRascunho.as_view(), name="descartar"),
    # ADR-111: as duas chamadas da escrita assistida. Respondem JSON — a tela não recarrega enquanto a IA pensa.
    # ADR-127: ligar a escrita assistida de onde ela aparece, sem passar por Configurações.
    path("ia/ativar/", views.AtivarEscritaAssistida.as_view(), name="ativar_ia"),
    path("<int:consulta_pk>/<int:paciente_pk>/transcrever/", views.TranscreverRelato.as_view(), name="transcrever"),
    path("<int:consulta_pk>/<int:paciente_pk>/redigir/", views.RedigirRegistro.as_view(), name="redigir"),
]
