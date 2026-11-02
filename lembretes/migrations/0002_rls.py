"""RLS do registro de lembretes (ADR-144, ADR-001): cada envio é do seu psicólogo, e de mais ninguém."""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "lembretes_lembreteenviado"


class Migration(migrations.Migration):
    dependencies = [("lembretes", "0001_initial")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
