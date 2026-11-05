from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from contas.views import Sair
from core.saude import saude
from indicadores.views import Painel, Vitrine
from lembretes.views import disparar as disparar_lembretes
from lembretes.views import webhook as webhook_whatsapp
from pacientes.views_convite import CadastroPeloPaciente

urlpatterns = [
    path("", Painel.as_view(), name="painel"),
    # ADR-140: a vitrine de componentes do redesign. Só para conta logada; é a referência visual depois da migração.
    path("vitrine/", Vitrine.as_view(), name="vitrine"),
    # ADR-114: a verificação de saúde do Render. Não toca o banco, de propósito.
    path("saude/", saude, name="saude"),
    # ADR-144: o cron externo bate aqui (protegida por segredo) para disparar os lembretes por WhatsApp.
    path("lembretes/disparar/", disparar_lembretes, name="lembretes_disparar"),
    # ADR-144: a Meta bate aqui (GET verifica a inscrição, POST traz o Sim/Não do paciente). Assinada por HMAC.
    path("whatsapp/webhook/", webhook_whatsapp, name="whatsapp_webhook"),
    path("pacientes/", include("pacientes.urls")),
    # Pública e sem login: o link que o psicólogo manda ao paciente (ADR-081). Fora de `pacientes/` de
    # propósito — o endereço que o paciente vê não diz nada sobre a estrutura do sistema.
    path("cadastro/<str:token>/", CadastroPeloPaciente.as_view(), name="cadastro_pelo_paciente"),
    path("conta/", include("contas.urls")),
    path("assinatura/", include("assinaturas.urls")),
    path("agenda/", include("atendimentos.urls")),
    # ADR-098: os horários declarados moram **dentro** da agenda. A rota antiga continua levando lá, para link
    # guardado ou favoritado não quebrar.
    path("agenda/horarios/", include("agenda.urls")),
    path("horarios/", RedirectView.as_view(pattern_name="agenda:horarios", permanent=False)),
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
