"""Tranca a tabela de pagamentos ao dono da sessão.

Separada da criação pela mesma razão das anteriores: o dia em que uma tabela nova esquecer o RLS, o diff
mostra a ausência desta migração.

Quanto cada paciente pagou, quando e como — pelo SQL cru de uma tabela sem policy sairia a receita de todos os
psicólogos do produto.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "financeiro_pagamento"


class Migration(migrations.Migration):
    dependencies = [("financeiro", "0001_initial")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
