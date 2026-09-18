from django.urls import path

from pacientes import views, views_cobranca, views_convite

app_name = "pacientes"

urlpatterns = [
    path("", views.ListaPacientes.as_view(), name="lista"),
    path("novo/", views.NovoPaciente.as_view(), name="novo"),
    path("convites/", views_convite.Convites.as_view(), name="convites"),
    path("convites/gerar/", views_convite.GerarConvite.as_view(), name="convite_gerar"),
    path("convites/<int:pk>/cancelar/", views_convite.CancelarConvite.as_view(), name="convite_cancelar"),
    path("<int:pk>/", views.DetalhePaciente.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.EditarPaciente.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.ExcluirPaciente.as_view(), name="excluir"),
    path("<int:pk>/historico/", views.HistoricoPaciente.as_view(), name="historico"),
    path("<int:pk>/atendimento/", views.EditarAtendimento.as_view(), name="atendimento"),
    path("<int:pk>/responsaveis/novo/", views.NovoResponsavel.as_view(), name="responsavel_novo"),
    path("responsaveis/<int:pk>/editar/", views.EditarResponsavel.as_view(), name="responsavel_editar"),
    path("responsaveis/<int:pk>/excluir/", views.ExcluirResponsavel.as_view(), name="responsavel_excluir"),
    path("casos/novo/", views.NovoCasoColetivo.as_view(), name="caso_novo"),
    path("casos/<int:pk>/", views.DetalheCaso.as_view(), name="caso"),
    path("casos/<int:pk>/excluir/", views.ExcluirCasoColetivo.as_view(), name="caso_excluir"),
    path("<int:pk>/cobranca/", views_cobranca.TrocarCobranca.as_view(), name="cobranca"),
]
