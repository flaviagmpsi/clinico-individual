from django.urls import path

from atendimentos import views

app_name = "atendimentos"

urlpatterns = [
    path("", views.Agenda.as_view(), name="agenda"),
    path("consultas/nova/", views.CadastrarAvulsa.as_view(), name="nova"),
    path("previstas/<int:regra_pk>/<str:data>/", views.CadastrarPrevista.as_view(), name="cadastrar_prevista"),
    path("remarcadas/<int:pk>/", views.CadastrarRemarcada.as_view(), name="cadastrar_remarcada"),
    path("consultas/<int:pk>/", views.EditarConsulta.as_view(), name="editar"),
    path("consultas/<int:pk>/excluir/", views.ExcluirConsulta.as_view(), name="excluir"),
    path("frequencia/<int:caso_pk>/", views.FrequenciaDoCaso.as_view(), name="frequencia"),
    path("desfecho/<int:caso_pk>/", views.RegistrarDesfecho.as_view(), name="desfecho"),
    path("desfecho/<int:caso_pk>/retomar/", views.RetomarAtendimento.as_view(), name="retomar"),
]
