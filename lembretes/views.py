"""As rotas anônimas do WhatsApp (ADR-144): o cron que dispara os lembretes e o webhook que recebe o Sim/Não.

Ambas correm sob `hamilton_web` (`dispensa_escopo`), não por login — quem chama é um cron ou a Meta, não uma
pessoa. O motor (`servicos`) faz a ponte para o domínio, por psicólogo. Cada uma tem sua prova de que o chamador é
quem diz ser: o cron, um **segredo compartilhado**; o webhook, a **assinatura HMAC** da Meta. Sem isso configurado,
a rota recusa — desligada por padrão.
"""

import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.escopo import dispensa_escopo
from lembretes import servicos

logger = logging.getLogger("lembretes")


@dispensa_escopo
@csrf_exempt
@require_POST
def disparar(request):
    # `.strip()` nos dois lados: uma variável de ambiente colada no painel do Render costuma vir com um espaço ou
    # uma quebra de linha invisível no fim, e sem isso o cron leva 403 com o segredo "certo". Comparação em tempo
    # constante por ser um segredo compartilhado.
    segredo = (settings.WHATSAPP_CRON_SEGREDO or "").strip()
    apresentado = (request.headers.get("X-Cron-Segredo", "") or request.GET.get("segredo", "")).strip()
    if not segredo or not hmac.compare_digest(apresentado, segredo):
        return HttpResponseForbidden("segredo inválido")
    # O cron não pode cair num 500 mudo: um erro aqui some no log do Django (sem config, `django.request` não vai
    # ao console em produção). Registramos o traceback com um marcador buscável e devolvemos a classe+mensagem no
    # corpo, para diagnosticar sem depender de caçar log.
    try:
        contagem = servicos.disparar()
    except Exception as erro:  # noqa: BLE001 — a borda do cron é o lugar certo de não deixar nada vazar como 500 mudo
        logger.exception("LEMBRETES_CRON_FALHOU")
        return JsonResponse({"ok": False, "erro": f"{type(erro).__name__}: {erro}"}, status=500)
    return JsonResponse({"ok": True, **contagem})


@dispensa_escopo
@csrf_exempt
def webhook(request):
    """O webhook da Meta (RF16): GET verifica a inscrição; POST traz o Sim/Não do paciente.

    Responde **200 rápido** a todo POST com assinatura válida — a Meta reenvia o que não receber 200, e o motor é
    idempotente, então um reenvio não duplica resposta. Assinatura inválida é recusada (nunca processa).
    """
    if request.method == "GET":
        return _verificar(request)
    if not _assinatura_valida(request):
        return HttpResponseForbidden("assinatura inválida")
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponse("ok")  # corpo ilegível não é motivo para a Meta ficar reenviando
    servicos.processar_webhook(payload)
    return HttpResponse("ok")


def _verificar(request):
    """A verificação única da Meta ao cadastrar o webhook: devolve o `hub.challenge` se o token bater."""
    esperado = settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN
    if (request.GET.get("hub.mode") == "subscribe" and esperado
            and request.GET.get("hub.verify_token") == esperado):
        return HttpResponse(request.GET.get("hub.challenge", ""))
    return HttpResponseForbidden("verificação falhou")


def _assinatura_valida(request) -> bool:
    """Confere o `X-Hub-Signature-256`: HMAC-SHA256 do corpo cru com o segredo do app (RF16).

    Sem o segredo configurado, não há como validar — e então nada é aceito. É o que mantém o webhook fechado por
    padrão: só processa o que a Meta assinou.
    """
    segredo = settings.WHATSAPP_APP_SECRET
    assinatura = request.headers.get("X-Hub-Signature-256", "")
    if not segredo or not assinatura.startswith("sha256="):
        return False
    esperada = "sha256=" + hmac.new(segredo.encode(), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, assinatura)
