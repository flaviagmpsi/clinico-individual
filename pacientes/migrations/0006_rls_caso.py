"""Tranca as quatro tabelas do caso ao dono da sessão.

Separada da criação pela mesma razão das anteriores: o dia em que uma tabela nova esquecer o RLS,
o diff mostra a ausência desta migração. Enterrada no `0005_caso`, ninguém veria.

Das quatro, a de **participação** é a que mais importa e a mais fácil de esquecer. É uma tabela
de junção — o tipo que se cria sem pensar —, e sem policy o SQL cru dela responderia quem atende
quem, para todos os psicólogos do produto. Foi por isso que ela virou `TenantOwnedModel` em vez
de ser o `ManyToManyField` automático, que não teria coluna de dono para a policy olhar.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELAS = [
    "pacientes_caso",
    "pacientes_participacao",
    "pacientes_condicaocobranca",
    "pacientes_responsavellegal",
]


class Migration(migrations.Migration):
    dependencies = [("pacientes", "0005_caso")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(tabela), reverse_sql=desativar_rls(tabela))
        for tabela in TABELAS
    ]
