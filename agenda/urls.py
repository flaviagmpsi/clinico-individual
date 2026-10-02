from django.urls import path

from agenda import views

app_name = "agenda"

urlpatterns = [
    path("", views.Horarios.as_view(), name="horarios"),
    path("<int:pk>/excluir/", views.ExcluirHorario.as_view(), name="excluir"),
    # ADR-122: o compromisso fora da clínica mora dentro de Horários, a pedido do usuário.
    path("compromissos/novo/", views.NovoCompromisso.as_view(), name="compromisso_novo"),
    path("compromissos/<int:pk>/editar/", views.EditarCompromisso.as_view(), name="compromisso_editar"),
    path("compromissos/<int:pk>/excluir/", views.ExcluirCompromisso.as_view(), name="compromisso_excluir"),
]
