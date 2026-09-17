"""As cinco situações da sessão, a cobrança e a modalidade (ADR-065).

A conversão roda depois de `cobrada` existir e de `estado` caber nas palavras novas:

- "falta cobrada" vira **faltou sem avisar**, que continua cobrando;
- "falta remarcada" vira **remarcada**, que não cobra;
- "realizada" vira **presente**, com o mesmo código, e continua cobrando.
"""

from django.db import migrations, models

SITUACOES = [
    ("REALIZADA", "Presente"),
    ("FALTOU", "Faltou sem avisar"),
    ("CANCELADA_CLIENTE", "Cliente cancelou"),
    ("CANCELADA_PROFISSIONAL", "Profissional cancelou"),
    ("REMARCADA", "Remarcada"),
]


def converter(apps, schema_editor):
    Consulta = apps.get_model("atendimentos", "Consulta")
    Consulta.objects.filter(estado="FALTA_COBRADA").update(estado="FALTOU", cobrada=True)
    Consulta.objects.filter(estado="FALTA_REMARCADA").update(estado="REMARCADA", cobrada=False)
    Consulta.objects.filter(estado="REALIZADA").update(cobrada=True)


class Migration(migrations.Migration):
    dependencies = [
        ("atendimentos", "0005_consulta_cadastrada"),
        ("pacientes", "0010_modalidade_do_paciente"),
    ]

    operations = [
        migrations.AddField(
            model_name="consulta",
            name="cobrada",
            field=models.BooleanField(
                default=True, verbose_name="Entra na cobrança",
                help_text="Vem da situação. Só o cancelamento pelo cliente admite escolha (ADR-065)."),
        ),
        migrations.AddField(
            model_name="consulta",
            name="modalidade",
            field=models.CharField(
                default="PRESENCIAL", max_length=10, verbose_name="Modalidade",
                choices=[("PRESENCIAL", "Presencial"), ("ONLINE", "Online")]),
        ),
        migrations.AlterField(
            model_name="consulta",
            name="estado",
            field=models.CharField(max_length=24, choices=SITUACOES, verbose_name="Situação"),
        ),
        migrations.RunPython(converter, migrations.RunPython.noop),
    ]
