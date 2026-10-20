"""Tranca as mensalidades quitadas à mão ao dono da sessão (ADR-133, ADR-001).

Separada da criação pela mesma razão das outras: o dia em que uma tabela nova esquecer o RLS, o diff mostra a
ausência desta migração. A tabela diz quais mensalidades de quais pacientes foram dadas como quitadas — pelo SQL
cru de uma tabela sem policy sairia dado financeiro de todos os assinantes.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "financeiro_mensalidadequitada"


class Migration(migrations.Migration):
    dependencies = [("financeiro", "0007_mensalidade_quitada_a_mao")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
