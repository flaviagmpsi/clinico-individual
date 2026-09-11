"""Cria `hamilton_web`: o papel com que a aplicação **conecta** (ADR-046, resolve P-67).

O passo 0 rebaixava a requisição autenticada para `hamilton_app` e parava aí. Faltavam duas
coisas, e as duas apareceram quando os testes tentaram atravessar a fronteira de propósito:

1. **A requisição anônima nunca descia de papel.** Login, cadastro e healthcheck rodavam como
   dono do banco. Um `SELECT` cru numa view pública devolvia a tabela de pacientes inteira.

2. **`SET LOCAL ROLE` é reversível.** A conexão continuava *autenticada* como dono, com
   `BYPASSRLS`; um `RESET ROLE` emendado numa injeção de SQL devolvia tudo. Rebaixar o papel
   corrente não adianta enquanto o papel de origem for privilegiado.

A resposta é separar **papel de conexão** de **papel de requisição**:

| Papel | Quando | Alcança |
|---|---|---|
| `hamilton_owner` | só migração (DDL) | tudo |
| `hamilton_web` | conexão da aplicação e requisição anônima | login e sessão. **Nada de clínico** |
| `hamilton_app` | `SET LOCAL ROLE` na requisição autenticada | domínio, filtrado pelo RLS |

Agora `RESET ROLE` cai em `hamilton_web`, que não tem *grant* em tabela de domínio: a fuga
deixa de ser proibida e passa a ser impossível.

Esta migração também retira `django_session` de `hamilton_app`. A tabela guarda o
`session_key` em claro — lê-la é se passar por qualquer psicólogo logado —, e quem precisa
dela é o `SessionMiddleware`, que roda fora da transação do escopo, sob o papel de conexão.

⚠️ A senha de `hamilton_web` **não** vive aqui. Defina-a fora do repositório:
`ALTER ROLE hamilton_web PASSWORD '...'` e aponte a `DATABASE_URL` para ele.
"""

from django.db import migrations

from core.rls import PAPEL_APLICACAO, PAPEL_WEB

# Tabelas que a superfície anônima precisa: autenticar alguém é procurar um usuário que ainda
# não se sabe qual é, e guardar a sessão de quem entrou. A lista é curta de propósito — o que
# não estiver aqui é inalcançável por uma requisição sem dono.
CRIAR = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PAPEL_WEB}') THEN
        CREATE ROLE {PAPEL_WEB} NOLOGIN NOBYPASSRLS NOINHERIT;
    END IF;
END
$$;

-- Papéis são globais ao cluster, não ao banco: o `IF NOT EXISTS` acima pula a criação quando
-- o papel sobrou de outro banco (ou de uma versão anterior desta migração). Sem este ALTER,
-- um `hamilton_web` legado com INHERIT continuaria enxergando o domínio, e a migração
-- reportaria sucesso. Declarar os atributos é mais barato que confiar no histórico.
--
-- ⚠️ Só os atributos de **segurança**. Repetir `NOLOGIN` aqui apagaria o `ALTER ROLE ... LOGIN`
-- que o operador concede fora do repositório, e o `migrate` seguinte trancaria a aplicação para
-- fora do próprio banco. Aconteceu na primeira execução: o servidor subiu, morreu em
-- "role is not permitted to log in", e o erro só aparece depois do deploy.
ALTER ROLE {PAPEL_WEB} NOBYPASSRLS NOINHERIT;

-- O papel de conexão precisa poder **subir** para o da requisição autenticada — e só isso.
-- `NOINHERIT` é o que separa "posso virar" de "já sou": sem ele, ser membro de
-- `hamilton_app` daria a `hamilton_web` os privilégios de `hamilton_app` o tempo todo, e a
-- requisição anônima voltaria a enxergar o domínio. Foi o que o teste de `RESET ROLE` pegou.
REVOKE {PAPEL_APLICACAO} FROM {PAPEL_WEB};
GRANT {PAPEL_APLICACAO} TO {PAPEL_WEB};
GRANT {PAPEL_WEB} TO CURRENT_USER;

GRANT USAGE ON SCHEMA public TO {PAPEL_WEB};

GRANT SELECT, INSERT, UPDATE, DELETE ON django_session TO {PAPEL_WEB};
GRANT SELECT, INSERT, UPDATE ON contas_psicologo TO {PAPEL_WEB};
GRANT USAGE, SELECT ON SEQUENCE contas_psicologo_id_seq TO {PAPEL_WEB};
GRANT SELECT ON django_content_type, auth_permission, auth_group TO {PAPEL_WEB};
GRANT SELECT ON contas_psicologo_groups, contas_psicologo_user_permissions TO {PAPEL_WEB};

-- `django_migrations` nasce antes do ALTER DEFAULT PRIVILEGES da 0001 — é a primeira tabela
-- que o Django cria —, então nenhum dos dois papéis a alcançava, e o `runserver` não subia.
-- Só leitura, e não há nada sensível nela.
GRANT SELECT ON django_migrations TO {PAPEL_WEB}, {PAPEL_APLICACAO};

-- O sequestro de sessão sai do alcance da requisição autenticada.
REVOKE ALL ON django_session FROM {PAPEL_APLICACAO};
"""

REMOVER = f"""
GRANT SELECT, INSERT, UPDATE, DELETE ON django_session TO {PAPEL_APLICACAO};
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {PAPEL_WEB};
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {PAPEL_WEB};
REVOKE ALL ON SCHEMA public FROM {PAPEL_WEB};
REVOKE {PAPEL_APLICACAO} FROM {PAPEL_WEB};
DROP ROLE IF EXISTS {PAPEL_WEB};
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_papel_aplicacao"),
        ("contas", "0001_initial"),
        ("sessions", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER),
    ]
