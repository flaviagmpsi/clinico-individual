"""RLS da mudança de regime (ADR-100): o histórico fiscal do psicólogo é dele, e de mais ninguém."""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "contas_mudancaderegime"


class Migration(migrations.Migration):
    dependencies = [("contas", "0010_despesas_opcionais_e_mudanca_de_regime")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
