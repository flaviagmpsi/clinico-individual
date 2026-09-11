"""Tranca a tabela do psicólogo — a última que ficou aberta (ADR-046).

`pacientes_paciente` tinha policy desde o passo 0. `contas_psicologo` não, porque ela não tem
coluna de dono: ela *é* o dono. O resultado era que, sob o escopo da Ana, um `SELECT` cru
devolvia e-mail, CPF, telefone e **hash de senha** de todos os assinantes do produto — a
tabela mais sensível do sistema era a única sem a terceira camada.

Separada do `0001_initial` pela mesma razão que em `pacientes`: o dia em que faltar, o diff
mostra a ausência.
"""

from django.db import migrations

from core.rls import ativar_rls_no_tenant_raiz, desativar_rls

TABELA = "contas_psicologo"


class Migration(migrations.Migration):
    dependencies = [
        ("contas", "0001_initial"),
        ("core", "0002_papel_web"),
    ]

    operations = [
        migrations.RunSQL(sql=ativar_rls_no_tenant_raiz(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
