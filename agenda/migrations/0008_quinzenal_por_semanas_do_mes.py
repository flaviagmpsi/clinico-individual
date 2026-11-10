"""Quinzenal passa a ser "par de semanas do mês", não mais "de 14 em 14 dias" (ADR-146).

Toda quinzenal que já existe tem de ganhar um par antes de a constraint entrar, ou o banco recusaria a linha.
Em vez de escolher um par fixo para todas, derivo de cada regra o par mais próximo do que ela já previa: a
semana do mês em que caía a primeira ocorrência do dia fixo. Assim a agenda não dá um salto brusco entre o
deploy e o momento em que o psicólogo reabre "Alterar frequência" e escolhe o par de propósito.

Usa o model **histórico**, que não carrega `TenantManager` nem `ValidaAoSalvar`; a migração roda como dono do
banco e enxerga as regras de todos os psicólogos, que é o que ela precisa. A volta não desfaz nada: o par é um
dado legítimo, e apagá-lo quebraria a regra que passou a depender dele.
"""

from datetime import timedelta

from django.db import migrations, models


def preencher_semanas_do_mes(apps, schema_editor):
    Recorrencia = apps.get_model("agenda", "Recorrencia")
    for regra in Recorrencia.objects.filter(frequencia="QUINZENAL"):
        primeira = regra.inicio + timedelta(days=(regra.dia_semana - regra.inicio.weekday()) % 7)
        ordinal = (primeira.day - 1) // 7 + 1  # 1ª..5ª ocorrência do dia no mês
        regra.semanas_do_mes = "1E3" if ordinal in (1, 3) else "2E4"
        regra.save(update_fields=["semanas_do_mes"])


class Migration(migrations.Migration):
    dependencies = [("agenda", "0007_rls_compromisso")]

    operations = [
        migrations.AddField(
            model_name="recorrencia",
            name="semanas_do_mes",
            field=models.CharField(
                blank=True, default="", max_length=3, verbose_name="Semanas do mês",
                choices=[("1E3", "1ª e 3ª semana do mês"), ("2E4", "2ª e 4ª semana do mês")],
                help_text="Só na quinzenal: em quais duas semanas do mês cai a sessão (ADR-146)."),
            # O default "" é só para dar valor às linhas que já existem ao adicionar a coluna; o campo do model
            # não tem default, então não o preservamos no estado (senão o makemigrations pediria uma alteração).
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="recorrencia",
            name="inicio",
            field=models.DateField(
                verbose_name="Vale a partir de",
                help_text="Sessões anteriores a esta data não mudam (ADR-022)."),
        ),
        migrations.RunPython(preencher_semanas_do_mes, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="recorrencia",
            constraint=models.CheckConstraint(
                condition=(models.Q(frequencia="QUINZENAL") & ~models.Q(semanas_do_mes=""))
                          | (~models.Q(frequencia="QUINZENAL") & models.Q(semanas_do_mes="")),
                name="recorrencia_semanas_do_mes_so_na_quinzenal",
            ),
        ),
    ]
