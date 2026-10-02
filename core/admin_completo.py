"""Registra no `/admin/` tudo o que ainda não estava lá (ADR-115).

O admin nasceu como instrumento de conferência do passo 0, com três models. A administradora da plataforma
precisa de mais: ver quem se cadastrou, o que cada um está usando, e corrigir à mão o que o produto ainda não
tem tela para corrigir.

**Registro automático, de propósito.** Escrever uma classe por model seria vinte arquivos para manter em dia, e
o que falhasse em silêncio seria justamente o model novo — que é quando a administradora mais precisa olhar. Aqui
o que entra é "todo model que já não tenha dono", e um model novo aparece sozinho.

O que o admin mostra continua filtrado pelo banco: psicólogo comum vê o que é dele; a superusuária vê tudo,
porque a ADR-115 abriu essa exceção no RLS. Não há filtro escrito aqui, e não deve haver — a garantia mora numa
camada que o código não consegue esquecer.
"""

from django.apps import apps
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered

# Models com tela própria em outro lugar, ou que não fazem sentido editar à mão.
FORA = {
    ("contas", "Psicologo"),        # já tem `contas.admin`, com os campos agrupados
    ("pacientes", "Paciente"),      # já tem `pacientes.admin`
    ("pacientes", "Caso"),          # já tem `pacientes.admin`
    # Bytes crus: o formulário do admin não sabe desenhar, e ninguém edita um PDF à mão. O arquivo em si
    # se baixa pela tela do paciente; o metadado (`ArquivoGuardado`) continua aqui.
    ("documentos", "ConteudoDeArquivo"),
    ("admin", "LogEntry"),
    ("sessions", "Session"),
    ("contenttypes", "ContentType"),
}

# Campos que nunca ajudam numa lista: texto longo, binário e JSON viram parede.
_RUINS_NA_LISTA = {"TextField", "BinaryField", "JSONField"}


def _colunas(model, quantas=5):
    """As primeiras colunas curtas do model — o suficiente para reconhecer a linha."""
    nomes = []
    for campo in model._meta.concrete_fields:
        if campo.get_internal_type() in _RUINS_NA_LISTA or campo.primary_key:
            continue
        nomes.append(campo.name)
        if len(nomes) == quantas:
            break
    return nomes or ["pk"]


def registrar_o_resto() -> int:
    quantos = 0
    for model in apps.get_models():
        rotulo = (model._meta.app_label, model.__name__)
        if rotulo in FORA or model._meta.app_label in {"auth", "contenttypes", "sessions", "admin"}:
            continue
        classe = type(f"{model.__name__}Admin", (admin.ModelAdmin,), {
            "list_display": _colunas(model),
            "list_per_page": 50,
            # `show_full_result_count=False` evita um COUNT(*) na tabela inteira a cada abertura de lista —
            # contra um banco remoto, é o que deixa a tela lenta sem motivo.
            "show_full_result_count": False,
        })
        try:
            admin.site.register(model, classe)
            quantos += 1
        except AlreadyRegistered:
            pass
    return quantos
