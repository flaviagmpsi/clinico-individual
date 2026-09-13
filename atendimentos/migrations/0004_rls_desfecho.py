"""Tranca a tabela de desfechos ao dono da sessão.

Separada da criação pela mesma razão das anteriores: o dia em que uma tabela nova esquecer o RLS, o diff
mostra a ausência desta migração.

Desfecho tem motivo em texto livre — "parou de responder depois da crise de junho" é informação clínica,
e sem policy sairia de todos os psicólogos pelo SQL cru.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "atendimentos_desfecho"


class Migration(migrations.Migration):
    dependencies = [("atendimentos", "0003_desfecho")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
