"""Tranca a ficha do prontuário ao dono e a torna imutável no próprio banco (ADR-079).

Mesmo desenho da versão confirmada (migração 0002): RLS, como em todo domínio, e um gatilho que recusa `UPDATE`.
Aqui o gatilho é incondicional — a ficha não tem rascunho, toda linha nasce definitiva. `DELETE` fica de fora
pelo mesmo motivo de lá: o model já recusa, e o descarte de conta (ADR-038) precisa apagar pelo papel dono.
"""

from django.db import migrations

from core.rls import ativar_rls, desativar_rls

FICHA = "prontuarios_fichadoprontuario"

GATILHO = f"""
CREATE OR REPLACE FUNCTION prontuario_ficha_imutavel() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'A ficha do prontuário não pode ser alterada. Grave uma nova.';
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ficha_imutavel ON {FICHA};
CREATE TRIGGER ficha_imutavel
    BEFORE UPDATE ON {FICHA}
    FOR EACH ROW EXECUTE FUNCTION prontuario_ficha_imutavel();
"""

REMOVER_GATILHO = f"""
DROP TRIGGER IF EXISTS ficha_imutavel ON {FICHA};
DROP FUNCTION IF EXISTS prontuario_ficha_imutavel();
"""


class Migration(migrations.Migration):
    dependencies = [("prontuarios", "0003_fichadoprontuario")]

    operations = [
        migrations.RunSQL(sql=ativar_rls(FICHA), reverse_sql=desativar_rls(FICHA)),
        migrations.RunSQL(sql=GATILHO, reverse_sql=REMOVER_GATILHO),
    ]
