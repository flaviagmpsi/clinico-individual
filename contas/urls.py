from django.urls import path

from contas import views

app_name = "contas"

urlpatterns = [
    path("entrar/", views.Entrar.as_view(), name="entrar"),
    path("criar/", views.CriarConta.as_view(), name="criar_conta"),
    path("cadastro/<int:passo>/", views.QuizDeCadastro.as_view(), name="quiz"),
    path("sair/", views.Sair.as_view(), name="sair"),
    path("perfil/", views.Perfil.as_view(), name="perfil"),
    path("configuracoes/", views.Configuracoes.as_view(), name="configuracoes"),
]
