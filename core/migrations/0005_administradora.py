"""A administradora da plataforma enxerga e altera tudo (ADR-115).

**O que muda, dito sem rodeio:** até aqui, nem superusuária via o dado de outro psicólogo. Agora a conta marcada
como `is_superuser` atravessa o isolamento em **todas** as tabelas, inclusive prontuário e documento. É a
operadora da plataforma, e foi decisão do usuário depois de o custo ser apresentado duas vezes.

**O custo, para ficar escrito:** essa conta passa a ser a chave do sistema inteiro. Comprometida, ela abre o
prontuário de todos os pacientes de todos os testadores. Antes, nem o roubo de uma sessão autenticada chegava lá.

**Como funciona:** uma segunda variável de sessão, `hamilton.administradora`, posta pelo middleware junto com o
dono, na mesma transação e com o mesmo `is_local` — morre com ela e não vaza pelo pool (I-01). Quem decide é o
Django; o banco só obedece ao que a transação declarou. Sem a variável, `current_setting(..., true)` devolve
NULL, a comparação falha, e o comportamento é o de antes — inclusive para as migrações antigas, que continuam
produzindo SQL válido.

Esta migração só **reescreve as policies** com a cláusula nova. As tabelas e os papéis já existem.
"""

from django.db import migrations

from core.rls import ativar_rls, ativar_rls_no_tenant_raiz, ativar_rls_por_tabela_pai

# A lista é escrita à mão, e não descoberta no catálogo: migração que varre o banco faz coisas diferentes em
# bancos diferentes — e esta decide quem lê prontuário.
COM_COLUNA_DE_DONO = (
    "agenda_horariodisponivel", "agenda_recorrencia", "assinaturas_assinatura",
    "atendimentos_consulta", "atendimentos_desfecho", "contas_mudancaderegime",
    "core_registroauditoria", "documentos_arquivoguardado", "documentos_documento",
    "financeiro_baixadedespesa", "financeiro_despesa", "financeiro_pagamento",
    "pacientes_caso", "pacientes_condicaocobranca", "pacientes_contatodeemergencia",
    "pacientes_convitedecadastro", "pacientes_paciente", "pacientes_participacao",
    "pacientes_responsavellegal", "prontuarios_anamnese", "prontuarios_fichadoprontuario",
    "prontuarios_prontuario", "prontuarios_respostadeanamnese", "prontuarios_temadeanamnese",
    "prontuarios_versaoprontuario",
)


def _sql() -> str:
    partes = [ativar_rls(tabela) for tabela in COM_COLUNA_DE_DONO]
    partes.append(ativar_rls_no_tenant_raiz("contas_psicologo"))
    partes.append(ativar_rls_por_tabela_pai("documentos_conteudodearquivo",
                                            pai="documentos_arquivoguardado", coluna_ligacao="arquivo_id"))
    return "\n".join(partes)


class Migration(migrations.Migration):
    # Depende da última migração de cada app: as policies são reescritas sobre as tabelas deles.
    dependencies = [
        ("core", "0004_rls_auditoria"),
        ("contas", "0013_ia_no_registro_de_sessao"),
        ("pacientes", "0013_endereco_fora_do_brasil"),
        ("agenda", "0004_rls_horario"),
        ("atendimentos", "0008_valor_da_sessao"),
        ("financeiro", "0005_categoria_do_carne_leao"),
        ("prontuarios", "0009_ia_no_registro_de_sessao"),
        ("documentos", "0005_rls_conteudo_de_arquivo"),
        ("assinaturas", "0002_rls"),
    ]

    operations = [
        # Sem reverso: a forma antiga de cada policy está no histórico do app que a criou.
        migrations.RunSQL(sql=_sql(), reverse_sql=migrations.RunSQL.noop),
    ]
