from django.apps import AppConfig


class LembretesConfig(AppConfig):
    """Lembretes por WhatsApp (ADR-144).

    Como `indicadores`, depende dos apps de domínio e **ninguém depende dele**: lê a agenda, o financeiro e os
    pacientes e aciona os avisos. A conversa com a Meta mora só em `lembretes.meta` (o adaptador).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "lembretes"
    verbose_name = "Lembretes por WhatsApp"
