"""Ver o isolamento acontecer: a lista de pacientes de quem está logado, e só dela."""

from django.contrib import admin

from pacientes.models import Paciente


@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ["nome", "criado_em"]
    search_fields = ["nome"]
    readonly_fields = ["criado_em", "atualizado_em"]
    # `psicologo` é `editable=False` e preenchido pelo contexto no `save()`: não há campo de
    # dono no formulário, e portanto não há como errar o dono ao cadastrar.
