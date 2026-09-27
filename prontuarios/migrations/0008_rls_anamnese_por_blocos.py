"""RLS dos temas e das respostas da anamnese (ADR-101): o roteiro e o que se escreve nele são dados clínicos."""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELAS = ["prontuarios_temadeanamnese", "prontuarios_respostadeanamnese"]


class Migration(migrations.Migration):
    dependencies = [("prontuarios", "0007_anamnese_por_blocos")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(tabela), reverse_sql=desativar_rls(tabela)) for tabela in TABELAS
    ]
