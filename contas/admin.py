"""Superfície mínima para **ver** a fundação funcionando.

O passo 0 não tem tela: ele é fundação. Sem nenhum model registrado, o `/admin/` mostra uma
página vazia e o isolamento continua sendo uma afirmação em documento. Registrar os dois
models existentes transforma a garantia em algo que dá para conferir com os olhos — entre como
um psicólogo e a lista mostra só o que é dele.

Não é a interface do produto (ADR-004 descreve outra coisa). É instrumento de verificação do
passo 0, e sai quando as telas de verdade chegarem.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from contas.models import Psicologo


@admin.register(Psicologo)
class PsicologoAdmin(UserAdmin):
    """A lista mostra **um** psicólogo: o que está logado.

    Não por filtro escrito aqui — por RLS. A policy de `contas_psicologo` responde ao papel
    `hamilton_app` com a própria linha e nada mais (ADR-046). Se um dia esta lista mostrar
    dois nomes, a terceira camada caiu.
    """

    ordering = ["email"]
    list_display = ["email", "nome_completo", "crp", "regime", "situacao_registro"]
    search_fields = ["email", "nome_completo", "cpf"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Identificação", {"fields": ("nome_completo", "cpf", "telefone")}),
        ("Registro profissional", {"fields": ("crp_regiao", "crp_numero", "situacao_registro", "verificado_em")}),
        ("Regime", {"fields": ("regime", "cnpj", "crp_empresa")}),
        ("Permissões", {"fields": ("is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2", "nome_completo", "cpf",
                       "telefone", "crp_regiao", "crp_numero"),
        }),
    )
