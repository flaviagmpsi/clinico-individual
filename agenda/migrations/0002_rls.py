"""Tranca a tabela de regras de frequência ao dono da sessão.

Separada da criação pela mesma razão das anteriores: o dia em que uma tabela nova esquecer o RLS, o diff
mostra a ausência desta migração. Enterrada no `0001_initial`, ninguém veria.

A regra diz "toda terça às 14h, com a Maria" — é a grade de atendimento de um psicólogo, e pelo SQL cru
de uma tabela sem policy sairia a de todos.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "agenda_recorrencia"


class Migration(migrations.Migration):
    dependencies = [("agenda", "0001_initial")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
