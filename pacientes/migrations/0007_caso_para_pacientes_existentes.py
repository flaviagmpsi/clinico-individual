"""Dá a cada paciente já cadastrado o caso individual que o cadastro novo cria em silêncio.

Sem isto, o invariante "todo paciente tem caso" (ADR-026) valeria só para quem entrasse daqui em
diante, e toda tela futura teria de perguntar "este paciente tem caso?" — os dois caminhos que a
ADR existe para evitar.

Usa os models **históricos**, que não carregam `TenantManager` nem `ValidaAoSalvar`: por isso o
`psicologo_id` é preenchido à mão, a partir do próprio paciente. A migração roda como dono do
banco, então enxerga os pacientes de todos os psicólogos — que é justamente o que ela precisa.

O caminho de volta não apaga nada. Apagar "os casos criados aqui" apagaria também, sem distinção,
os que o cadastro criou depois desta migração.
"""

from django.db import migrations


def criar_casos_individuais(apps, schema_editor):
    Paciente = apps.get_model("pacientes", "Paciente")
    Caso = apps.get_model("pacientes", "Caso")
    Participacao = apps.get_model("pacientes", "Participacao")

    for paciente in Paciente.objects.all().iterator():
        if Participacao.objects.filter(paciente_id=paciente.pk).exists():
            continue
        caso = Caso.objects.create(
            psicologo_id=paciente.psicologo_id,
            pagador_paciente_id=paciente.pk,
        )
        Participacao.objects.create(
            psicologo_id=paciente.psicologo_id,
            caso=caso,
            paciente_id=paciente.pk,
        )


class Migration(migrations.Migration):
    dependencies = [("pacientes", "0006_rls_caso")]

    operations = [
        migrations.RunPython(criar_casos_individuais, migrations.RunPython.noop),
    ]
