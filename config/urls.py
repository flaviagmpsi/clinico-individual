from django.contrib import admin
from django.urls import include, path

from contas.views import Sair
from indicadores.views import Painel

urlpatterns = [
    path("", Painel.as_view(), name="painel"),
    path("pacientes/", include("pacientes.urls")),
    path("conta/", include("contas.urls")),
    path("agenda/", include("atendimentos.urls")),
    path("horarios/", include("agenda.urls")),
    path("financeiro/", include("financeiro.urls")),
    path("prontuarios/", include("prontuarios.urls")),

    # ⚠️ Precisa vir **antes** de `admin/`: o logout do admin apaga a linha da sessão durante a
    # view, e `hamilton_app` não alcança `django_session` desde a ADR-046. Esta rota entrega a
    # view decorada com `dispensa_escopo`, que roda sob `hamilton_web`. O admin é superfície
    # temporária de conferência do passo 0 e sai quando não fizer mais falta.
    path("admin/logout/", Sair.as_view()),
    path("admin/", admin.site.urls),
]
