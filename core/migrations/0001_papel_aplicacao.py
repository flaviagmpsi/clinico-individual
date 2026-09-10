"""Cria o papel sob o qual a aplicação roda — e que **não pode** ignorar o RLS.

Descoberto ao executar o passo 0: o papel dono do banco no Neon (`hamilton_owner`) tem o
atributo **`BYPASSRLS`**. Esse atributo passa por cima de tudo, inclusive de
`FORCE ROW LEVEL SECURITY`. Ou seja: a policy existia, a tabela estava trancada, e a
aplicação lia dado de todos os psicólogos assim mesmo — o pior cenário possível, porque
*parecia* protegido.

A migração cria `hamilton_app`, sem login e sem `BYPASSRLS`, com apenas os privilégios de
leitura e escrita nas tabelas. As migrações continuam rodando como dono (DDL exige isso);
o que muda é que **cada requisição desce para este papel** antes de tocar em dado
(`core.db.assumir_papel_da_aplicacao`).

Roda antes de qualquer migração de domínio para que o `ALTER DEFAULT PRIVILEGES` alcance
todas as tabelas criadas depois — inclusive as que ainda não existem.
"""

from django.db import migrations

PAPEL = "hamilton_app"

CRIAR = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PAPEL}') THEN
        CREATE ROLE {PAPEL} NOLOGIN NOBYPASSRLS;
    END IF;
END
$$;

-- Sem a associação, o dono não consegue SET ROLE para este papel.
GRANT {PAPEL} TO CURRENT_USER;

GRANT USAGE ON SCHEMA public TO {PAPEL};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {PAPEL};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {PAPEL};

-- Para as tabelas que ainda serão criadas pelas migrações seguintes.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {PAPEL};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO {PAPEL};
"""

REMOVER = f"""
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {PAPEL};
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {PAPEL};
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {PAPEL};
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {PAPEL};
REVOKE ALL ON SCHEMA public FROM {PAPEL};
DROP ROLE IF EXISTS {PAPEL};
"""


class Migration(migrations.Migration):
    initial = True

    run_before = [
        ("contas", "0001_initial"),
        ("pacientes", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER),
    ]
