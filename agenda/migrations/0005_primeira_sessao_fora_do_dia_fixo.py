"""A primeira sessão pode cair fora do dia da semana do horário fixo (ADR-120).

O psicólogo informa no cadastro do paciente a data da primeira sessão e, à parte, o horário fixo semanal. Quando
a primeira cai noutro dia — "começamos nesta sexta, depois é toda terça" —, ela não existia para o sistema: a
agenda só desenhava a série semanal, e a sessão combinada sumia. Foi relatado por uma psicóloga de verdade, que
cadastrou a paciente numa sexta e não encontrou nada na agenda daquele dia.

Campo **anulável e em branco por padrão**: toda regra que já existe continua exatamente como está, e nenhuma
sessão nova aparece retroativamente em agenda nenhuma. Só passa a valer para quem informar a data daqui em diante.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agenda', '0004_rls_horario'),
    ]

    operations = [
        migrations.AddField(
            model_name='recorrencia',
            name='primeira_sessao_em',
            field=models.DateField(blank=True, help_text='Só quando a primeira sessão cai em outro dia da semana. Vale uma vez; depois segue o fixo.', null=True, verbose_name='Primeira sessão'),
        ),
    ]
