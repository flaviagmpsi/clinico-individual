"""Tranca as receitas externas e os recebimentos ao dono da sessão (ADR-136, ADR-001).

Separada da criação pela mesma razão das outras tabelas: o dia em que uma tabela nova esquecer o RLS, o diff
mostra a ausência desta migração. As duas guardam **quanto** o psicólogo ganha fora da clínica — pelo SQL cru de
uma tabela sem policy sairia renda de todos os assinantes. As duas têm `psicologo_id` (TenantOwnedModel), então
é o `ativar_rls` padrão.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELAS = ("financeiro_receitaexterna", "financeiro_recebimentoexterno")


class Migration(migrations.Migration):
    dependencies = [("financeiro", "0009_receitaexterna_recebimentoexterno")]

    operations = [
        operacao
        for tabela in TABELAS
        for operacao in [migrations.RunSQL(sql=ativar_rls(tabela), reverse_sql=desativar_rls(tabela))]
    ]
