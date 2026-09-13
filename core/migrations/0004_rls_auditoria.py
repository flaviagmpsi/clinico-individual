"""Tranca a trilha de auditoria ao dono **e** tira do papel da requisição o poder de mudar o passado (ADR-057).

Duas coisas, e a segunda é o que distingue esta tabela de todas as outras:

1. **RLS**, como em toda tabela de domínio: o psicólogo só lê a própria trilha.
2. **`REVOKE UPDATE, DELETE`** de `hamilton_app`. O `ALTER DEFAULT PRIVILEGES` da 0001 deu leitura e escrita
   completas a toda tabela nova; aqui a requisição fica só com `SELECT` e `INSERT`. O model já recusa regravar
   e apagar, mas uma trilha que serve de prova não pode depender só de Python — uma injeção de SQL numa view
   qualquer não pode apagar o rastro do que fez.

Quem ainda apaga é o papel dono, e só no descarte da conta (ADR-038): a exclusão em cascata a partir do
psicólogo roda com os privilégios do dono da tabela.
"""

from django.db import migrations

from core.rls import PAPEL_APLICACAO, PAPEL_WEB, ativar_rls, desativar_rls

TABELA = "core_registroauditoria"

SO_ACRESCENTA = f"REVOKE UPDATE, DELETE, TRUNCATE ON {TABELA} FROM {PAPEL_APLICACAO}, {PAPEL_WEB};"
DEVOLVER = f"GRANT UPDATE, DELETE ON {TABELA} TO {PAPEL_APLICACAO};"


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_registroauditoria"),
        # O papel web nasce na 0002 do core; a dependência explícita deixa claro que o REVOKE o encontra.
        ("core", "0002_papel_web"),
    ]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA) + SO_ACRESCENTA, reverse_sql=DEVOLVER + desativar_rls(TABELA)),
    ]
