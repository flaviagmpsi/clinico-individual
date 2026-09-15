"""O padrão de vencimento do perfil ganha o tipo: dia fixo ou dia útil (ADR-063).

Quem já tinha padrão tinha um dia fixo — o único tipo que existia —, e o `default` cobre isso.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("contas", "0005_dia_vencimento_sem_cobra_falta")]

    operations = [
        migrations.AddField(
            model_name="psicologo",
            name="tipo_vencimento_mensalidade",
            field=models.CharField(
                default="DIA_FIXO", max_length=8, verbose_name="Vencimento da mensalidade em",
                choices=[("DIA_FIXO", "Dia fixo do mês"), ("DIA_UTIL", "Dia útil do mês")],
                help_text="Dia fixo (todo dia 10) ou dia útil (todo 5º dia útil) — ADR-063."),
        ),
    ]
