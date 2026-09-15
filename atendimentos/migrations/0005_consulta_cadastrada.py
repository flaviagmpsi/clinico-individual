"""A consulta passa a existir só quando o psicólogo a cadastra (ADR-060).

Ordem das operações, e por quê:

1. **Alarga `estado`** antes de converter: "FALTA_REMARCADA" não cabe nos 10 caracteres antigos.
2. **Converte** enquanto `contabilizada` ainda existe — é ela que diz se a falta era cobrada:
   - `AGENDADA` e `CANCELADA` saem: eram previsão, não registro, e a previsão agora é calculada;
   - `FALTA` que entrava na cobrança vira falta cobrada; a que não entrava, falta remarcada.
3. **Remove** os campos que a ADR-060 aposentou: a cobrança deriva da situação, e remarcar deixou de existir.
"""

from django.db import migrations, models


def converter(apps, schema_editor):
    Consulta = apps.get_model("atendimentos", "Consulta")
    Consulta.objects.filter(estado__in=["AGENDADA", "CANCELADA"]).delete()
    Consulta.objects.filter(estado="FALTA", contabilizada=True).update(estado="FALTA_COBRADA")
    Consulta.objects.filter(estado="FALTA").update(estado="FALTA_REMARCADA")


class Migration(migrations.Migration):
    dependencies = [("atendimentos", "0004_rls_desfecho")]

    operations = [
        migrations.AlterField(
            model_name="consulta",
            name="estado",
            field=models.CharField(
                max_length=16, verbose_name="Situação",
                choices=[("REALIZADA", "Realizada"), ("FALTA_COBRADA", "Falta cobrada"),
                         ("FALTA_REMARCADA", "Falta remarcada")]),
        ),
        migrations.RunPython(converter, migrations.RunPython.noop),
        migrations.RemoveField(model_name="consulta", name="contabilizada"),
        migrations.RemoveField(model_name="consulta", name="remarcada"),
        migrations.RemoveField(model_name="consulta", name="registrada_em"),
        migrations.AlterField(
            model_name="consulta",
            name="data_prevista",
            field=models.DateField(blank=True, null=True, verbose_name="Data prevista pela frequência"),
        ),
    ]
