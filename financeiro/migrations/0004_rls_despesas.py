"""RLS das despesas e das baixas (ADR-083): o que o psicólogo gasta é dele, e de mais ninguém."""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELAS = ["financeiro_despesa", "financeiro_baixadedespesa"]


class Migration(migrations.Migration):
    dependencies = [("financeiro", "0003_despesas")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(tabela), reverse_sql=desativar_rls(tabela)) for tabela in TABELAS
    ]
