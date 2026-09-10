"""Row-Level Security: a terceira camada da ADR-001.

As duas primeiras camadas vivem em Python e protegem contra esquecimento. Esta vive no
Postgres e protege contra **tudo o mais**: `.raw()`, `cursor.execute()`, shell do Django,
uma view nova escrita às pressas. Se a policy está no lugar, a linha do outro psicólogo não
volta — nem que a consulta peça.

Duas armadilhas que tornam RLS inútil se ignoradas, e por isso estão tratadas aqui:

1. **O dono da tabela ignora RLS por padrão.** No Neon, a aplicação costuma conectar com o
   papel que criou as tabelas. Sem `FORCE ROW LEVEL SECURITY`, a policy existe e não vale
   nada — o pior dos mundos, porque parece protegido.

2. **A variável de sessão vaza pelo pool** (I-01). Resolvido em `core/db.py` usando
   `set_config(..., is_local => true)`, que o Postgres descarta ao fim da transação.
"""

VARIAVEL_SESSAO = "hamilton.psicologo_id"

_NOME_POLICY = "isolamento_por_psicologo"


def ativar_rls(tabela: str, coluna_dono: str = "psicologo_id") -> str:
    """SQL que tranca uma tabela ao dono da sessão.

    O `current_setting(..., true)` usa `missing_ok = true` para devolver NULL em vez de erro
    quando a variável não foi definida. NULL faz a comparação falhar e a policy não devolver
    linha nenhuma — negar por omissão, que é o padrão seguro.
    """
    return f"""
        ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS {_NOME_POLICY} ON {tabela};
        CREATE POLICY {_NOME_POLICY} ON {tabela}
            USING ({coluna_dono} = NULLIF(current_setting('{VARIAVEL_SESSAO}', true), '')::bigint)
            WITH CHECK ({coluna_dono} = NULLIF(current_setting('{VARIAVEL_SESSAO}', true), '')::bigint);
    """


def desativar_rls(tabela: str) -> str:
    """Reverso de `ativar_rls`, para a migração poder voltar atrás."""
    return f"""
        DROP POLICY IF EXISTS {_NOME_POLICY} ON {tabela};
        ALTER TABLE {tabela} NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE {tabela} DISABLE ROW LEVEL SECURITY;
    """
