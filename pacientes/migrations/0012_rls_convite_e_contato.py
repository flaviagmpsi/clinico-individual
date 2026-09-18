"""RLS do contato de emergência e do convite de cadastro — e a única fresta do visitante anônimo (ADR-081).

As duas tabelas ganham a policy de sempre: só o dono enxerga.

O convite ganha **mais uma**, endereçada a `hamilton_web` — o papel de quem abre o link sem estar logado. Ela é
estreita de propósito:

- **Uma linha só:** a do token que a requisição apresentou. O hash vai numa variável de transação
  (`core.db.aplicar_convite`), como o escopo do psicólogo. Sem a variável, não volta linha nenhuma: nem um
  `SELECT *` escrito à mão lista os convites, e muito menos as respostas dos outros.
- **Responder uma vez só:** a policy de `UPDATE` só alcança convite ainda sem resposta. O uso único do link não
  depende de a view lembrar de checar.
- **Só as colunas da resposta:** o grant de `UPDATE` é por coluna. O visitante não troca o dono, o paciente, o
  prazo nem o hash.

`hamilton_web` continua sem grant em tabela clínica. O que o paciente preenche fica no convite até o psicólogo
revisar e salvar — aí sim, sob `hamilton_app` e dentro do escopo dele.
"""

from django.db import migrations

from core.rls import PAPEL_WEB, VARIAVEL_CONVITE, ativar_rls, desativar_rls

CONTATO = "pacientes_contatodeemergencia"
CONVITE = "pacientes_convitedecadastro"

_HASH_DA_REQUISICAO = f"NULLIF(current_setting('{VARIAVEL_CONVITE}', true), '')"

FRESTA = f"""
GRANT SELECT ON {CONVITE} TO {PAPEL_WEB};
GRANT UPDATE (respostas, respondido_em, atualizado_em) ON {CONVITE} TO {PAPEL_WEB};

DROP POLICY IF EXISTS convite_pelo_token ON {CONVITE};
CREATE POLICY convite_pelo_token ON {CONVITE}
    FOR SELECT TO {PAPEL_WEB}
    USING (token_hash = {_HASH_DA_REQUISICAO});

DROP POLICY IF EXISTS resposta_unica_pelo_token ON {CONVITE};
CREATE POLICY resposta_unica_pelo_token ON {CONVITE}
    FOR UPDATE TO {PAPEL_WEB}
    USING (token_hash = {_HASH_DA_REQUISICAO} AND respondido_em IS NULL AND aceito_em IS NULL)
    WITH CHECK (token_hash = {_HASH_DA_REQUISICAO});
"""

FECHAR_FRESTA = f"""
DROP POLICY IF EXISTS resposta_unica_pelo_token ON {CONVITE};
DROP POLICY IF EXISTS convite_pelo_token ON {CONVITE};
REVOKE ALL ON {CONVITE} FROM {PAPEL_WEB};
"""


class Migration(migrations.Migration):
    dependencies = [("pacientes", "0011_cadastro_pelo_paciente"), ("core", "0002_papel_web")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(CONTATO), reverse_sql=desativar_rls(CONTATO)),
        migrations.RunSQL(sql=ativar_rls(CONVITE), reverse_sql=desativar_rls(CONVITE)),
        migrations.RunSQL(sql=FRESTA, reverse_sql=FECHAR_FRESTA),
    ]
