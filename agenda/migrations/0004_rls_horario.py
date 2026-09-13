"""Tranca a grade de horários ao dono da sessão.

Separada da criação pela mesma razão das anteriores: o dia em que uma tabela nova esquecer o RLS, o diff
mostra a ausência desta migração.

A grade diz quando cada psicólogo atende — pelo SQL cru de uma tabela sem policy sairia a rotina de todos.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "agenda_horariodisponivel"


class Migration(migrations.Migration):
    dependencies = [("agenda", "0003_horariodisponivel")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
