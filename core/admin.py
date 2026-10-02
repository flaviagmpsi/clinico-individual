"""Registra no `/admin/` os models que não têm classe própria (ADR-115).

Vive em `core/admin.py` porque o Django carrega o `admin.py` de cada app sozinho, **depois** de todos os models
estarem prontos — que é exatamente a hora certa para varrer e registrar o resto. Fazer isso no `ready()` do
`AppConfig` pegaria o registro pela metade.
"""

from core.admin_completo import registrar_o_resto

registrar_o_resto()
