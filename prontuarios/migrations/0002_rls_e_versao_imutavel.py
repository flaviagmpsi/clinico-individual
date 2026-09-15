"""Tranca o prontuário ao dono e torna a versão confirmada imutável no próprio banco (ADR-064).

Duas coisas:

1. **RLS** nas duas tabelas, como em todo domínio: o prontuário é o dado mais sensível do produto.
2. **Gatilho** que recusa `UPDATE` em versão já confirmada. O model já recusa, mas prova que depende só de Python
   não é prova: um `UPDATE` cru — de uma view escrita às pressas, de uma injeção, de uma migração mal pensada —
   passaria por cima. O gatilho vale para qualquer papel, inclusive o dono do banco, que ignora o RLS mas não
   ignora gatilho. Confirmar um rascunho continua possível: a linha antiga ainda não tem data de confirmação.

`DELETE` não entra no gatilho: a exclusão já é protegida pelo model e pelo `PROTECT`, e o descarte de conta da
ADR-038 precisa apagar pelo papel dono.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

PRONTUARIO = "prontuarios_prontuario"
VERSAO = "prontuarios_versaoprontuario"

GATILHO = f"""
CREATE OR REPLACE FUNCTION prontuario_versao_confirmada_imutavel() RETURNS trigger AS $$
BEGIN
    IF OLD.confirmada_em IS NOT NULL THEN
        RAISE EXCEPTION 'Versão confirmada de prontuário não pode ser alterada. Crie uma nova versão.';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS versao_confirmada_imutavel ON {VERSAO};
CREATE TRIGGER versao_confirmada_imutavel
    BEFORE UPDATE ON {VERSAO}
    FOR EACH ROW EXECUTE FUNCTION prontuario_versao_confirmada_imutavel();
"""

REMOVER_GATILHO = f"""
DROP TRIGGER IF EXISTS versao_confirmada_imutavel ON {VERSAO};
DROP FUNCTION IF EXISTS prontuario_versao_confirmada_imutavel();
"""


class Migration(migrations.Migration):
    dependencies = [("prontuarios", "0001_initial")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(PRONTUARIO), reverse_sql=desativar_rls(PRONTUARIO)),
        migrations.RunSQL(sql=ativar_rls(VERSAO), reverse_sql=desativar_rls(VERSAO)),
        migrations.RunSQL(sql=GATILHO, reverse_sql=REMOVER_GATILHO),
    ]
