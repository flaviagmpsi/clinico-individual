"""Mensalidade vence em dia fixo ou em dia útil (ADR-063).

Toda mensalidade existente tinha um dia fixo — é o único tipo que havia —, então ganha `DIA_FIXO`.
"""

from django.db import migrations, models


def converter(apps, schema_editor):
    Condicao = apps.get_model("pacientes", "CondicaoCobranca")
    Condicao.objects.filter(modalidade="MENSAL", dia_vencimento__isnull=False).update(tipo_vencimento="DIA_FIXO")


class Migration(migrations.Migration):
    dependencies = [("pacientes", "0008_dia_vencimento")]

    operations = [
        migrations.AddField(
            model_name="condicaocobranca",
            name="tipo_vencimento",
            field=models.CharField(
                blank=True, max_length=8, verbose_name="Tipo de vencimento",
                choices=[("DIA_FIXO", "Dia fixo do mês"), ("DIA_UTIL", "Dia útil do mês")],
                help_text="Dia fixo (todo dia 10) ou dia útil (todo 5º dia útil). Só para mensalidade."),
        ),
        migrations.RunPython(converter, migrations.RunPython.noop),
    ]
