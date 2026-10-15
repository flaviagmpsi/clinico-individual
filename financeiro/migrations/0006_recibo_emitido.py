"""O pagamento registra se o recibo já foi emitido (ADR-132).

`default=True`: emitir recibo (Receita Saúde) é obrigação legal, mas os pagamentos que já existem foram feitos
antes de o sistema perguntar — nascê-los como "recibo a emitir" criaria uma pendência falsa para cada um. Daqui
em diante, o formulário de pagamento pergunta, e quem marca "não" ganha o lembrete.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0005_categoria_do_carne_leao'),
    ]

    operations = [
        migrations.AddField(
            model_name='pagamento',
            name='recibo_emitido',
            field=models.BooleanField(default=True, verbose_name='Recibo emitido'),
        ),
    ]
