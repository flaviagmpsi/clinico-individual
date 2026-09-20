"""ADR-094: a conta nasce só com login e CRP, e a abordagem passa a ser escrita à mão — quantas forem.

A ordem importa: as colunas novas entram **antes** de as antigas saírem, e no meio a abordagem já respondida é
levada para a lista. Feito em SQL, e não com o ORM, porque a tabela tem RLS forçada (ADR-046) e a migração não
roda no escopo de nenhum psicólogo — o `UPDATE` de quem migra é o do dono do banco.
"""

import django.core.validators
from django.db import migrations, models

_ROTULOS = {
    "PSICANALISE": "Psicanálise",
    "TCC": "Terapia cognitivo-comportamental",
    "ANALITICA": "Psicologia analítica (junguiana)",
    "GESTALT": "Gestalt-terapia",
    "HUMANISTA": "Abordagem centrada na pessoa / humanista",
    "FENOMENOLOGICA": "Fenomenológico-existencial",
    "COMPORTAMENTAL": "Análise do comportamento",
    "SISTEMICA": "Sistêmica / familiar",
    "PSICODRAMA": "Psicodrama",
}


def levar_a_abordagem_para_a_lista(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for codigo, rotulo in _ROTULOS.items():
            cursor.execute("UPDATE contas_psicologo SET abordagens = jsonb_build_array(%s::text) WHERE abordagem = %s",
                           [rotulo, codigo])
        cursor.execute("UPDATE contas_psicologo SET abordagens = jsonb_build_array(abordagem_outra) "
                       "WHERE abordagem = 'OUTRA' AND abordagem_outra <> ''")


class Migration(migrations.Migration):

    dependencies = [
        ('contas', '0008_como_atende_e_quiz'),
    ]

    operations = [
        migrations.AddField(
            model_name='psicologo',
            name='abordagens',
            field=models.JSONField(blank=True, default=list, verbose_name='Abordagens'),
        ),
        migrations.AddField(
            model_name='psicologo',
            name='outras_areas',
            field=models.JSONField(blank=True, default=list, verbose_name='Outras áreas de atuação'),
        ),
        migrations.RunPython(levar_a_abordagem_para_a_lista, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='psicologo',
            name='abordagem',
        ),
        migrations.RemoveField(
            model_name='psicologo',
            name='abordagem_outra',
        ),
        migrations.AlterField(
            model_name='psicologo',
            name='cpf',
            field=models.CharField(blank=True, max_length=11, null=True, unique=True, validators=[django.core.validators.RegexValidator('^\\d{11}$', 'CPF tem 11 números, sem pontos ou traços.')], verbose_name='CPF'),
        ),
        migrations.AlterField(
            model_name='psicologo',
            name='nome_completo',
            field=models.CharField(blank=True, max_length=255, verbose_name='Nome completo'),
        ),
        migrations.AlterField(
            model_name='psicologo',
            name='telefone',
            field=models.CharField(blank=True, max_length=20, validators=[django.core.validators.RegexValidator('^\\d{10,11}$', 'Telefone com DDD: 10 ou 11 números, sem espaços ou traços.')], verbose_name='Telefone'),
        ),
    ]
