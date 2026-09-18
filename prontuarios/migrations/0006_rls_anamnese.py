"""RLS da anamnese (ADR-085): dado clínico, trancado ao dono como todo o resto do app."""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "prontuarios_anamnese"


class Migration(migrations.Migration):
    dependencies = [("prontuarios", "0005_anamnese")]

    operations = [migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA))]
