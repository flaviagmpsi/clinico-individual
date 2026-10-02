"""Tranca os compromissos ao dono da sessão.

Separada da criação pela mesma razão das anteriores: o dia em que uma tabela nova esquecer o RLS, o diff mostra
a ausência desta migração.

O compromisso não tem dado clínico — é um título escrito pelo psicólogo e um horário. Mas diz **quando ele
trabalha e com quem**: "Supervisão do Arthur, terça 10h" é a rotina dele e o nome de um terceiro. Pelo SQL cru
de uma tabela sem policy sairia a semana inteira de todos os assinantes.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "agenda_compromisso"


class Migration(migrations.Migration):
    dependencies = [("agenda", "0006_compromisso")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
