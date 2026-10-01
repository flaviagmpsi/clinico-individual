"""RLS do arquivo guardado (ADR-112): contrato e anexo são do psicólogo, e de mais ninguém.

`documentos_conteudodearquivo` **não** entra aqui, e é de propósito: ele não tem coluna `psicologo` para a policy
comparar. Quem o protege é o `ArquivoGuardado` de que ele depende — o `OneToOneField` é a chave primária, o
`CASCADE` apaga junto, e nenhuma consulta chega aos bytes sem passar pelo metadado, que a RLS filtra. Pôr uma
segunda cópia do dono ali criaria duas fontes da verdade, e duas fontes discordam um dia.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "documentos_arquivoguardado"


class Migration(migrations.Migration):
    dependencies = [("documentos", "0003_arquivos_guardados")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
    ]
