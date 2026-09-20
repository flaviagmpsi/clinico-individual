"""RLS da assinatura (ADR-094): cada psicólogo enxerga a sua, e só a sua.

⚠️ Quando o webhook do Asaas chegar (S-01b), ele vai precisar atualizar a assinatura **sem** psicólogo autenticado.
Isso pede uma policy endereçada, como a do convite de cadastro (ADR-081) — não o afrouxamento desta.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "assinaturas_assinatura"


class Migration(migrations.Migration):
    dependencies = [("assinaturas", "0001_initial")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
