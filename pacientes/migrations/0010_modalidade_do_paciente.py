"""Modalidade padrão do paciente: online ou presencial (ADR-065).

Presencial como padrão porque é o que o cadastro sempre supôs até aqui — ninguém escolheu online.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("pacientes", "0009_tipo_vencimento")]

    operations = [
        migrations.AddField(
            model_name="paciente",
            name="modalidade",
            field=models.CharField(
                default="PRESENCIAL", max_length=10, verbose_name="Modalidade padrão",
                choices=[("PRESENCIAL", "Presencial"), ("ONLINE", "Online")]),
        ),
    ]
