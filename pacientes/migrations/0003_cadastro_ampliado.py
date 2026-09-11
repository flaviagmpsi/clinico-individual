"""Cadastro ampliado do paciente — os campos declarados no escopo.

Quase todos opcionais (ADR-012). O CPF é único **por psicólogo**, não global: dois psicólogos
podem atender a mesma pessoa, e o sistema não pode deixar isso transparecer (ADR-001).
"""

# Gerado por Django 5.2.4 on 2026-09-11 17:04

import django.core.validators
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pacientes', '0002_rls'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='paciente',
            name='bairro',
            field=models.CharField(blank=True, max_length=100, verbose_name='Bairro'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='cep',
            field=models.CharField(blank=True, max_length=8, validators=[django.core.validators.RegexValidator('^\\d*$', 'Informe apenas números, sem pontos ou traços.')], verbose_name='CEP'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='cidade',
            field=models.CharField(blank=True, max_length=100, verbose_name='Cidade'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='complemento',
            field=models.CharField(blank=True, max_length=100, verbose_name='Complemento'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='cpf',
            field=models.CharField(blank=True, max_length=11, validators=[django.core.validators.RegexValidator('^\\d*$', 'Informe apenas números, sem pontos ou traços.')], verbose_name='CPF'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='data_nascimento',
            field=models.DateField(blank=True, null=True, verbose_name='Data de nascimento'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='data_primeira_sessao',
            field=models.DateField(blank=True, null=True, verbose_name='Data da primeira sessão'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='email',
            field=models.EmailField(blank=True, max_length=254, verbose_name='E-mail'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='logradouro',
            field=models.CharField(blank=True, max_length=255, verbose_name='Logradouro'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='medicamento',
            field=models.TextField(blank=True, verbose_name='Medicamento em uso'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='numero',
            field=models.CharField(blank=True, max_length=20, verbose_name='Número'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='observacoes',
            field=models.TextField(blank=True, verbose_name='Observações'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='telefone',
            field=models.CharField(blank=True, max_length=20, validators=[django.core.validators.RegexValidator('^\\d*$', 'Informe apenas números, sem pontos ou traços.')], verbose_name='Telefone'),
        ),
        migrations.AddField(
            model_name='paciente',
            name='uf',
            field=models.CharField(blank=True, choices=[('AC', 'Acre'), ('AL', 'Alagoas'), ('AP', 'Amapá'), ('AM', 'Amazonas'), ('BA', 'Bahia'), ('CE', 'Ceará'), ('DF', 'Distrito Federal'), ('ES', 'Espírito Santo'), ('GO', 'Goiás'), ('MA', 'Maranhão'), ('MT', 'Mato Grosso'), ('MS', 'Mato Grosso do Sul'), ('MG', 'Minas Gerais'), ('PA', 'Pará'), ('PB', 'Paraíba'), ('PR', 'Paraná'), ('PE', 'Pernambuco'), ('PI', 'Piauí'), ('RJ', 'Rio de Janeiro'), ('RN', 'Rio Grande do Norte'), ('RS', 'Rio Grande do Sul'), ('RO', 'Rondônia'), ('RR', 'Roraima'), ('SC', 'Santa Catarina'), ('SP', 'São Paulo'), ('SE', 'Sergipe'), ('TO', 'Tocantins')], max_length=2, verbose_name='UF'),
        ),
        migrations.AlterField(
            model_name='paciente',
            name='nome',
            field=models.CharField(max_length=255, verbose_name='Nome completo'),
        ),
        migrations.AddConstraint(
            model_name='paciente',
            constraint=models.UniqueConstraint(condition=models.Q(('cpf__gt', '')), fields=('psicologo', 'cpf'), name='cpf_unico_por_psicologo'),
        ),
    ]
