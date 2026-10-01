"""Row-Level Security: a terceira camada da ADR-001.

As duas primeiras camadas vivem em Python e protegem contra esquecimento. Esta vive no
Postgres e protege contra **tudo o mais**: `.raw()`, `cursor.execute()`, shell do Django,
uma view nova escrita às pressas. Se a policy está no lugar, a linha do outro psicólogo não
volta — nem que a consulta peça.

Três armadilhas que tornam RLS inútil se ignoradas, e por isso estão tratadas aqui:

1. **O dono da tabela ignora RLS por padrão.** No Neon, a aplicação costuma conectar com o
   papel que criou as tabelas. Sem `FORCE ROW LEVEL SECURITY`, a policy existe e não vale
   nada — o pior dos mundos, porque parece protegido.

2. **A variável de sessão vaza pelo pool** (I-01). Resolvido em `core/db.py` usando
   `set_config(..., is_local => true)`, que o Postgres descarta ao fim da transação.

3. **A policy vale para quem?** Uma policy sem `TO` vale para todos os papéis, inclusive o
   que precisa ler a tabela *antes* de existir um psicólogo autenticado — é o caso do login,
   que consulta `contas_psicologo` sem saber ainda quem é o dono. Por isso as policies aqui
   são **endereçadas a papéis** (ADR-046).
"""

VARIAVEL_SESSAO = "hamilton.psicologo_id"
# O hash do convite de cadastro que a requisição anônima apresentou (ADR-081). Mesma mecânica da variável de
# sessão: vale só dentro da transação, e sem ela a policy do convite não devolve linha nenhuma.
VARIAVEL_CONVITE = "hamilton.convite_hash"

PAPEL_APLICACAO = "hamilton_app"
PAPEL_WEB = "hamilton_web"

_NOME_POLICY = "isolamento_por_psicologo"
_NOME_POLICY_AUTENTICACAO = "autenticacao"

_DONO_DA_SESSAO = f"NULLIF(current_setting('{VARIAVEL_SESSAO}', true), '')::bigint"


def ativar_rls(tabela: str, coluna_dono: str = "psicologo_id") -> str:
    """SQL que tranca uma tabela de domínio ao dono da sessão.

    O `current_setting(..., true)` usa `missing_ok = true` para devolver NULL em vez de erro
    quando a variável não foi definida. NULL faz a comparação falhar e a policy não devolver
    linha nenhuma — negar por omissão, que é o padrão seguro.
    """
    return f"""
        ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS {_NOME_POLICY} ON {tabela};
        CREATE POLICY {_NOME_POLICY} ON {tabela}
            USING ({coluna_dono} = {_DONO_DA_SESSAO})
            WITH CHECK ({coluna_dono} = {_DONO_DA_SESSAO});
    """


def ativar_rls_no_tenant_raiz(tabela: str, coluna_id: str = "id") -> str:
    """Tranca a tabela do próprio psicólogo — a única sem coluna de dono.

    Ela *é* o dono, então a comparação é com a própria chave. Sem isto, a tabela que guarda
    CPF, telefone e **hash de senha** de todos os assinantes ficava legível por qualquer
    caminho que chegasse a SQL cru dentro de uma requisição autenticada.

    A exceção endereçada a `hamilton_web` existe porque autenticar é, por definição, procurar
    um usuário que ainda não se sabe qual é. Essa permissão é o preço do login — e o motivo
    de `hamilton_web` não ter grant nenhum em tabela clínica: a superfície anônima do sistema
    (login, cadastro, webhook) precisa do cadastro e de nada mais.
    """
    return f"""
        ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS {_NOME_POLICY} ON {tabela};
        CREATE POLICY {_NOME_POLICY} ON {tabela}
            TO {PAPEL_APLICACAO}
            USING ({coluna_id} = {_DONO_DA_SESSAO})
            WITH CHECK ({coluna_id} = {_DONO_DA_SESSAO});

        DROP POLICY IF EXISTS {_NOME_POLICY_AUTENTICACAO} ON {tabela};
        CREATE POLICY {_NOME_POLICY_AUTENTICACAO} ON {tabela}
            TO {PAPEL_WEB}
            USING (true)
            WITH CHECK (true);
    """


def ativar_rls_por_tabela_pai(tabela: str, pai: str, coluna_ligacao: str,
                              coluna_dono: str = "psicologo_id") -> str:
    """Tranca uma tabela que não tem coluna de dono, pelo dono da linha de que ela depende.

    O caso é o conteúdo de arquivo (ADR-112): os bytes moram à parte do metadado para a listagem não os carregar,
    e por isso a tabela não tem `psicologo_id`. A primeira versão da ADR-112 concluiu que ela dispensava RLS,
    porque "nenhuma consulta chega aos bytes sem passar pelo metadado". Isso é verdade **do código** — e a razão
    de existir desta camada é justamente valer quando o código erra (`.raw()`, `cursor.execute()`, shell, uma
    view nova escrita às pressas). Duplicar a coluna do dono criaria duas fontes da verdade; perguntar ao pai,
    não. A policy custa uma busca por chave primária, que é o índice que já existe.
    """
    dono_do_pai = (f"EXISTS (SELECT 1 FROM {pai} p "
                   f"WHERE p.id = {tabela}.{coluna_ligacao} AND p.{coluna_dono} = {_DONO_DA_SESSAO})")
    return f"""
        ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS {_NOME_POLICY} ON {tabela};
        CREATE POLICY {_NOME_POLICY} ON {tabela}
            USING ({dono_do_pai})
            WITH CHECK ({dono_do_pai});
    """


def desativar_rls(tabela: str) -> str:
    """Reverso de `ativar_rls`, para a migração poder voltar atrás."""
    return f"""
        DROP POLICY IF EXISTS {_NOME_POLICY_AUTENTICACAO} ON {tabela};
        DROP POLICY IF EXISTS {_NOME_POLICY} ON {tabela};
        ALTER TABLE {tabela} NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE {tabela} DISABLE ROW LEVEL SECURITY;
    """
