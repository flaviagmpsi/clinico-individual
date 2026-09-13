from django.urls import path

from agenda import views

app_name = "agenda"

urlpatterns = [
    path("", views.Horarios.as_view(), name="horarios"),
    path("<int:pk>/excluir/", views.ExcluirHorario.as_view(), name="excluir"),
]
