"""A rota que o cron externo chama para disparar os lembretes (ADR-144).

Anônima e protegida por um **segredo compartilhado** (`WHATSAPP_CRON_SEGREDO`), não por login — quem chama é um
cron, não uma pessoa. `dispensa_escopo` a faz correr sob `hamilton_web`; o motor (`servicos.disparar`) faz a ponte
para o domínio, por psicólogo. Sem o segredo configurado, a rota **recusa tudo** — desligada por padrão.
"""

from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.escopo import dispensa_escopo
from lembretes import servicos


@dispensa_escopo
@csrf_exempt
@require_POST
def disparar(request):
    segredo = settings.WHATSAPP_CRON_SEGREDO
    apresentado = request.headers.get("X-Cron-Segredo", "") or request.GET.get("segredo", "")
    if not segredo or apresentado != segredo:
        return HttpResponseForbidden("segredo inválido")
    contagem = servicos.disparar()
    return JsonResponse({"ok": True, **contagem})
