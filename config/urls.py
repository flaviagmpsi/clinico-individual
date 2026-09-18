from django.contrib import admin
from django.urls import include, path

from contas.views import Sair
from indicadores.views import Estatisticas, Painel
from pacientes.views_convite import CadastroPeloPaciente

urlpatterns = [
    path("", Painel.as_view(), name="painel"),
    path("estatisticas/", Estatisticas.as_view(), name="estatisticas"),
    path("pacientes/", include("pacientes.urls")),
    # Pública e sem login: o link que o psicólogo manda ao paciente (ADR-081). Fora de `pacientes/` de
    # propósito — o endereço que o paciente vê não diz nada sobre a estrutura do sistema.
    path("cadastro/<str:token>/", CadastroPeloPaciente.as_view(), name="cadastro_pelo_paciente"),
    path("conta/", include("contas.urls")),
    path("agenda/", include("atendimentos.urls")),
    path("horarios/", include("agenda.urls")),
    path("financeiro/", include("financeiro.urls")),
    path("prontuarios/", include("prontuarios.urls")),
    path("documentos/", include("documentos.urls")),

    # ⚠️ Precisa vir **antes** de `admin/`: o logout do admin apaga a linha da sessão durante a
    # view, e `hamilton_app` não alcança `django_session` desde a ADR-046. Esta rota entrega a
    # view decorada com `dispensa_escopo`, que roda sob `hamilton_web`. O admin é superfície
    # temporária de conferência do passo 0 e sai quando não fizer mais falta.
    path("admin/logout/", Sair.as_view()),
    path("admin/", admin.site.urls),
]
