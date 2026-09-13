"""Ver o isolamento acontecer: cada lista mostra só o que é de quem está logado.

Nenhum formulário daqui tem campo de dono. `psicologo` é `editable=False` e preenchido pelo
contexto no `save()` — e isso vale também para as linhas criadas pelos inlines.
"""

from django.contrib import admin

from pacientes.models import Caso, CondicaoCobranca, Paciente, Participacao, ResponsavelLegal

_SO_LEITURA = ["criado_em", "atualizado_em"]


class ResponsavelInline(admin.TabularInline):
    model = ResponsavelLegal
    extra = 0
    fields = ["nome", "parentesco", "telefone", "guarda", "detem_guarda"]


class ParticipacaoInline(admin.TabularInline):
    model = Participacao
    extra = 0
    fields = ["paciente"]


class CondicaoInline(admin.TabularInline):
    model = CondicaoCobranca
    extra = 0
    fields = ["modalidade", "valor", "vencimento", "vigente_desde"]


@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ["nome", "criado_em"]
    search_fields = ["nome"]
    readonly_fields = _SO_LEITURA
    inlines = [ResponsavelInline]


@admin.register(Caso)
class CasoAdmin(admin.ModelAdmin):
    list_display = ["__str__", "criado_em"]
    readonly_fields = _SO_LEITURA
    fields = ["descricao", "pagador_paciente", "pagador_nome", "pagador_cpf", *_SO_LEITURA]
    inlines = [ParticipacaoInline, CondicaoInline]
