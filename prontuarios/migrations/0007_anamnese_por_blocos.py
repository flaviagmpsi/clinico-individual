"""ADR-101: o roteiro da anamnese passa a ser do psicólogo — tema é dado, não coluna.

Cada conta que já tem anamnese recebe os doze temas sugeridos (na ordem em que eram campos) e o texto de cada
campo vira a resposta do tema correspondente. Campo em branco não vira resposta: anamnese pela metade continua
pela metade, e não ganha doze blocos vazios.

O psicólogo que ainda não abriu nenhuma anamnese não ganha tema nenhum aqui — ele os recebe na primeira vez que
abrir a tela (`prontuarios.anamneses.roteiro`), que é também o caminho de toda conta criada daqui em diante.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


from prontuarios.temas import TEMAS_SUGERIDOS


def levar_o_texto_para_os_blocos(apps, schema_editor):
    Anamnese = apps.get_model("prontuarios", "Anamnese")
    Tema = apps.get_model("prontuarios", "TemaDeAnamnese")
    Resposta = apps.get_model("prontuarios", "RespostaDeAnamnese")

    temas_por_dono: dict[int, dict[str, object]] = {}
    for anamnese in Anamnese.objects.all().iterator():
        dono = anamnese.psicologo_id
        if dono not in temas_por_dono:
            temas_por_dono[dono] = {
                chave: Tema.objects.create(psicologo_id=dono, titulo=titulo, ajuda=ajuda,
                                           ordem=(i + 1) * 10, origem=chave)
                for i, (chave, titulo, ajuda) in enumerate(TEMAS_SUGERIDOS)
            }
        for chave, _, _ in TEMAS_SUGERIDOS:
            texto = (getattr(anamnese, chave, "") or "").strip()
            if texto:
                Resposta.objects.create(psicologo_id=dono, anamnese=anamnese,
                                        tema=temas_por_dono[dono][chave], texto=texto)


class Migration(migrations.Migration):

    dependencies = [
        ('prontuarios', '0006_rls_anamnese'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TemaDeAnamnese',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('criado_em', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('atualizado_em', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
                ('titulo', models.CharField(max_length=120, verbose_name='Tema')),
                ('ajuda', models.CharField(blank=True, max_length=255, verbose_name='O que anotar aqui')),
                ('ordem', models.PositiveSmallIntegerField(default=0, verbose_name='Ordem')),
                ('arquivado', models.BooleanField(default=False, verbose_name='Arquivado')),
                ('origem', models.CharField(blank=True, editable=False, max_length=40, verbose_name='Origem')),
                ('psicologo', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s', to=settings.AUTH_USER_MODEL, verbose_name='Psicólogo')),
            ],
            options={
                'verbose_name': 'Tema de anamnese',
                'verbose_name_plural': 'Temas de anamnese',
                'ordering': ['ordem', 'pk'],
            },
        ),
        migrations.CreateModel(
            name='RespostaDeAnamnese',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('criado_em', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('atualizado_em', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
                ('texto', models.TextField(blank=True, verbose_name='Texto')),
                ('anamnese', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='respostas', to='prontuarios.anamnese')),
                ('psicologo', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name='%(app_label)s_%(class)s', to=settings.AUTH_USER_MODEL, verbose_name='Psicólogo')),
                ('tema', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='respostas', to='prontuarios.temadeanamnese')),
            ],
            options={
                'verbose_name': 'Resposta de anamnese',
                'verbose_name_plural': 'Respostas de anamnese',
                'ordering': ['tema__ordem', 'tema__pk'],
            },
        ),
        migrations.AddConstraint(
            model_name='temadeanamnese',
            constraint=models.UniqueConstraint(fields=('psicologo', 'titulo'), name='tema_de_anamnese_sem_repetir'),
        ),
        migrations.AddConstraint(
            model_name='respostadeanamnese',
            constraint=models.UniqueConstraint(fields=('anamnese', 'tema'), name='uma_resposta_por_tema'),
        ),
        # A ordem importa: primeiro as tabelas novas, depois a cópia do que já estava escrito, e só então os
        # campos antigos saem. Ao contrário, o texto de quem já preencheu a anamnese iria embora.
        migrations.RunPython(levar_o_texto_para_os_blocos, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='anamnese',
            name='desenvolvimento',
        ),
        migrations.RemoveField(
            model_name='anamnese',
            name='escolaridade_e_trabalho',
        ),
        migrations.RemoveField(
            model_name='anamnese',
            name='expectativas',
        ),
        migrations.RemoveField(
            model_name='anamnese',
            name='historia_da_queixa',
        ),
        migrations.RemoveField(
            model_name='anamnese',
            name='historia_familiar',
        ),
        migrations.RemoveField(
            model_name='anamnese',
            name='observacoes',
        ),
        migrations.RemoveField(
            model_name='anamnese',
            name='queixa_principal',
        ),
        migrations.RemoveField(
            model_name='anamnese',
            name='relacionamentos',
        ),
        migrations.RemoveField(
            model_name='anamnese',
            name='rotina_e_lazer',
        ),
        migrations.RemoveField(
            model_name='anamnese',
            name='saude_geral',
        ),
        migrations.RemoveField(
            model_name='anamnese',
            name='sono_alimentacao_substancias',
        ),
        migrations.RemoveField(
            model_name='anamnese',
            name='tratamentos_anteriores',
        ),
    ]
