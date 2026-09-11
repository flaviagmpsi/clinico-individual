from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Fundação"

    def ready(self):
        from core import checks  # noqa: F401  — registra o check de papel de conexão
