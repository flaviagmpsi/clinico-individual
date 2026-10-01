"""RLS no conteúdo do arquivo (ADR-113, corrige a ADR-112).

A ADR-112 deixou `documentos_conteudodearquivo` sem RLS, com o argumento de que nenhuma consulta chega aos bytes
sem passar pelo metadado, que é filtrado. O argumento é verdadeiro **do código** — e é exatamente contra o código
errado que esta camada existe: `.raw()`, `cursor.execute()`, shell do Django, uma view nova escrita às pressas
(ver `core/rls.py`). Sem policy aqui, um `SELECT * FROM documentos_conteudodearquivo` dentro de uma requisição
autenticada devolvia o contrato de todos os psicólogos.

A tabela não tem `psicologo_id` de propósito — duplicar o dono criaria duas fontes da verdade. Então a policy
pergunta ao pai, por chave primária, que é o índice que já existe.
"""

from django.db import migrations

from core.rls import ativar_rls_por_tabela_pai, desativar_rls

TABELA = "documentos_conteudodearquivo"


class Migration(migrations.Migration):
    dependencies = [("documentos", "0004_rls_arquivos_guardados")]

    operations = [
        migrations.RunSQL(
            sql=ativar_rls_por_tabela_pai(TABELA, pai="documentos_arquivoguardado", coluna_ligacao="arquivo_id"),
            reverse_sql=desativar_rls(TABELA),
        ),
    ]
