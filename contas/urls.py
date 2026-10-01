from django.urls import path

from contas import senha, views

app_name = "contas"

urlpatterns = [
    path("entrar/", views.Entrar.as_view(), name="entrar"),
    path("criar/", views.CriarConta.as_view(), name="criar_conta"),
    path("cadastro/<int:passo>/", views.QuizDeCadastro.as_view(), name="quiz"),
    path("sair/", views.Sair.as_view(), name="sair"),
    path("perfil/", views.Perfil.as_view(), name="perfil"),
    path("configuracoes/", views.Configuracoes.as_view(), name="configuracoes"),
    # ADR-114: recuperação de senha. Sem ela, quem esquece fica trancado para sempre.
    path("senha/", senha.Pedir.as_view(), name="senha_pedir"),
    path("senha/enviada/", senha.Enviada.as_view(), name="senha_enviada"),
    path("senha/trocar/<uidb64>/<token>/", senha.Trocar.as_view(), name="senha_trocar"),
    path("senha/trocada/", senha.Trocada.as_view(), name="senha_trocada"),
]
