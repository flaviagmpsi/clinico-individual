from django.urls import path

from pacientes import views

app_name = "pacientes"

urlpatterns = [
    path("", views.ListaPacientes.as_view(), name="lista"),
    path("novo/", views.NovoPaciente.as_view(), name="novo"),
    path("<int:pk>/", views.DetalhePaciente.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.EditarPaciente.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.ExcluirPaciente.as_view(), name="excluir"),
]
