"""Vencimento da mensalidade vira dia do mês (ADR-059) e "cobro falta" sai do perfil (ADR-060).

A conversão roda entre a criação do campo novo e a remoção do antigo: "início do mês" vira dia 1, e "fim do mês"
vira dia 31 — que em mês mais curto vale o último dia.
"""

import django.core.validators
from django.db import migrations, models


def converter(apps, schema_editor):
    Psicologo = apps.get_model("contas", "Psicologo")
    Psicologo.objects.filter(vencimento_mensalidade="INICIO").update(dia_vencimento_mensalidade=1)
    Psicologo.objects.filter(vencimento_mensalidade="FIM").update(dia_vencimento_mensalidade=31)


class Migration(migrations.Migration):
    dependencies = [("contas", "0004_padroes_de_atendimento")]

    operations = [
        migrations.AddField(
            model_name="psicologo",
            name="dia_vencimento_mensalidade",
            field=models.PositiveSmallIntegerField(
                default=10, verbose_name="Dia de vencimento da mensalidade",
                help_text="Proposto a cada paciente que pagar por mês. Em mês mais curto, vale o último dia.",
                validators=[django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(31)]),
        ),
        migrations.RunPython(converter, migrations.RunPython.noop),
        migrations.RemoveField(model_name="psicologo", name="vencimento_mensalidade"),
        migrations.RemoveField(model_name="psicologo", name="cobra_falta"),
    ]
