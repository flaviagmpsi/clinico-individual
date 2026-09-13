from django.urls import path

from atendimentos import views

app_name = "atendimentos"

urlpatterns = [
    path("", views.Agenda.as_view(), name="agenda"),
    path("consultas/nova/", views.NovaConsulta.as_view(), name="nova"),
    path("consultas/<int:pk>/remarcar/", views.RemarcarConsulta.as_view(), name="remarcar"),
    path("consultas/<int:pk>/registrar/", views.RegistrarConsulta.as_view(), name="registrar"),
    path("frequencia/<int:caso_pk>/", views.FrequenciaDoCaso.as_view(), name="frequencia"),
]
