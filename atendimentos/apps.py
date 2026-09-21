from django.apps import AppConfig


class AtendimentosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "atendimentos"
    verbose_name = "Atendimentos"

    def ready(self):
        # O horário de atendimento é perguntado **dentro** do cadastro do paciente (ADR-095). `pacientes` só
        # oferece o encaixe; quem sabe de agenda é este app, e a seta de dependência continua apontando para lá.
        from atendimentos.horario_no_cadastro import BlocoDeHorario
        from pacientes.cadastro import registrar_bloco

        registrar_bloco(BlocoDeHorario)
