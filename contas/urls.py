from django.urls import path

from contas import views

app_name = "contas"

urlpatterns = [
    path("entrar/", views.Entrar.as_view(), name="entrar"),
    path("sair/", views.Sair.as_view(), name="sair"),
    path("perfil/", views.Perfil.as_view(), name="perfil"),
]
