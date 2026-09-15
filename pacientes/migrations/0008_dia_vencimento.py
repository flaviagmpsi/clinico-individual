"""O vencimento da mensalidade passa a ser um dia do mês (ADR-059).

A conversão roda entre a criação do campo novo e a remoção do antigo: "início do mês" vira dia 1, e "fim do mês"
vira dia 31 — que em mês mais curto vale o último dia.
"""

import django.core.validators
from django.db import migrations, models


def converter(apps, schema_editor):
    Condicao = apps.get_model("pacientes", "CondicaoCobranca")
    Condicao.objects.filter(vencimento="INICIO").update(dia_vencimento=1)
    Condicao.objects.filter(vencimento="FIM").update(dia_vencimento=31)


class Migration(migrations.Migration):
    dependencies = [("pacientes", "0007_caso_para_pacientes_existentes")]

    operations = [
        migrations.AddField(
            model_name="condicaocobranca",
            name="dia_vencimento",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="Dia do vencimento",
                help_text="Só para mensalidade. Em mês mais curto, vale o último dia.",
                validators=[django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(31)]),
        ),
        migrations.RunPython(converter, migrations.RunPython.noop),
        migrations.RemoveField(model_name="condicaocobranca", name="vencimento"),
    ]
