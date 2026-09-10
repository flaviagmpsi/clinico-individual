"""Tranca a tabela de pacientes ao dono da sessão.

Migração separada da criação da tabela de propósito: o dia em que um modelo novo esquecer o
RLS, o diff mostra a ausência desta migração. Enterrado dentro do `0001_initial`, ninguém veria.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "pacientes_paciente"


class Migration(migrations.Migration):
    dependencies = [("pacientes", "0001_initial")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
