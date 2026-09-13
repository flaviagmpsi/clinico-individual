"""Tranca a tabela de consultas ao dono da sessão.

Separada da criação pela mesma razão das anteriores: o dia em que uma tabela nova esquecer o RLS, o diff
mostra a ausência desta migração.

É a tabela que mais cresce e a que mais vai ser consultada — agenda, painel, prontuário e financeiro
dependem dela. Sem policy, cada uma dessas telas seria uma chance a mais de uma consulta sem filtro de
dono devolver a agenda inteira do produto.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "atendimentos_consulta"


class Migration(migrations.Migration):
    dependencies = [("atendimentos", "0001_initial")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
