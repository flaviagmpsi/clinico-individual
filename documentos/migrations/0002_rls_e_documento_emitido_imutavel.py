"""Tranca o documento ao dono e torna o emitido imutável no próprio banco (ADR-076).

O mesmo desenho do prontuário (ADR-064), pela mesma razão: a cópia guardada do documento entregue é registro
documental (Res. CFP nº 01/2009, Art. 2º, VI), e prova que depende só de Python não é prova.

1. **RLS** na tabela, como em todo domínio.
2. **Gatilho** que recusa `UPDATE` em documento já emitido — vale para qualquer papel, inclusive o dono do banco,
   que ignora o RLS mas não ignora gatilho. Emitir um rascunho continua possível: a linha antiga ainda não tem
   data de emissão.

`DELETE` não entra no gatilho: a exclusão já é recusada pelo model, e o descarte de conta da ADR-038 precisa
apagar pelo papel dono.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

TABELA = "documentos_documento"

GATILHO = f"""
CREATE OR REPLACE FUNCTION documento_emitido_imutavel() RETURNS trigger AS $$
BEGIN
    IF OLD.emitido_em IS NOT NULL THEN
        RAISE EXCEPTION 'Documento emitido não pode ser alterado. Crie um novo a partir dele.';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS documento_emitido_imutavel ON {TABELA};
CREATE TRIGGER documento_emitido_imutavel
    BEFORE UPDATE ON {TABELA}
    FOR EACH ROW EXECUTE FUNCTION documento_emitido_imutavel();
"""

REMOVER_GATILHO = f"""
DROP TRIGGER IF EXISTS documento_emitido_imutavel ON {TABELA};
DROP FUNCTION IF EXISTS documento_emitido_imutavel();
"""


class Migration(migrations.Migration):
    dependencies = [("documentos", "0001_initial")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(TABELA), reverse_sql=desativar_rls(TABELA)),
        migrations.RunSQL(sql=GATILHO, reverse_sql=REMOVER_GATILHO),
    ]
