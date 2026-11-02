"""Adaptador da WhatsApp Cloud API (Meta) — o único lugar do sistema que fala WhatsApp (ADR-144, WHATSAPP.md).

O resto do Polaris chama **intenções** (ex.: "lembrar compromisso", "avisar agenda do dia"); ninguém aqui conhece
paciente, sessão nem cobrança — é o mesmo papel que `prontuarios/ia.py` tem com a OpenAI.

Duas garantias que não se negociam:
- **Modo simulado é o padrão** (`settings.WHATSAPP_SIMULADO`): sem `WHATSAPP_ATIVO=True` e credenciais, **não toca a
  rede** — registra o que enviaria e segue. É assim no desenvolvimento e no ar enquanto a conta Meta não tiver cartão
  (sem ele, modelo fora da janela de 24h é recusado — erro 131042).
- **Erro da Meta nunca sobe como exceção** para a tela ou para o job: toda falha vira um `Envio(ok=False)`, com `requests`
  trocado por `urllib` da biblioteca padrão (uma dependência a menos) e **timeout** sempre.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger("lembretes.whatsapp")

_TIMEOUT = 10  # segundos; a Meta responde rápido, e um envio preso não pode segurar o job de lembretes.


@dataclass
class Envio:
    """O resultado de uma tentativa de envio, para registrar e decidir sem levantar exceção."""

    ok: bool
    simulado: bool
    id_mensagem: str = ""
    erro: str = ""


def normalizar_numero(telefone: str) -> str:
    """Só os dígitos, com `+55` e DDD, como a Meta exige no destino. Vazio quando não há número.

    O 9º dígito do celular fica como veio no cadastro; a normalização do **webhook** é que precisa lidar com o
    `wa_id` que às vezes volta sem o 9 (WHATSAPP.md). Aqui, no envio, mandamos o que está cadastrado.
    """
    digitos = re.sub(r"\D", "", telefone or "")
    if not digitos:
        return ""
    if not digitos.startswith("55"):
        digitos = "55" + digitos
    return "+" + digitos


def enviar_modelo(telefone: str, modelo: str, variaveis: list) -> Envio:
    """Envia um modelo aprovado (`pt_BR`), preenchendo `{{1}}, {{2}}...` com `variaveis`, **na ordem**.

    Modelo é o que vale fora da janela de 24h — todo lembrete que o sistema dispara por conta própria. Botões de
    resposta (Sim/Não), quando o modelo os tem, são definidos no próprio modelo na Meta; aqui não mudam o corpo.
    """
    destino = normalizar_numero(telefone)
    if not destino:
        return Envio(ok=False, simulado=settings.WHATSAPP_SIMULADO, erro="sem número de WhatsApp")

    if settings.WHATSAPP_SIMULADO:
        logger.info("WhatsApp SIMULADO: enviaria o modelo %r para %s com %r", modelo, destino, list(variaveis))
        return Envio(ok=True, simulado=True, id_mensagem="simulado")

    corpo = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "template",
        "template": {
            "name": modelo,
            "language": {"code": "pt_BR"},
            "components": [{"type": "body",
                            "parameters": [{"type": "text", "text": str(v)} for v in variaveis]}],
        },
    }
    return _postar(corpo, modelo, destino)


def _postar(corpo: dict, modelo: str, destino: str) -> Envio:
    url = (f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}"
           f"/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages")
    requisicao = urllib.request.Request(
        url, data=json.dumps(corpo).encode(), method="POST",
        headers={"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(requisicao, timeout=_TIMEOUT) as resposta:
            dados = json.loads(resposta.read().decode())
        id_mensagem = (dados.get("messages") or [{}])[0].get("id", "")
        return Envio(ok=True, simulado=False, id_mensagem=id_mensagem)
    except urllib.error.HTTPError as erro:
        detalhe = _detalhe_do_erro(erro)
        logger.warning("WhatsApp: a Meta recusou o modelo %r para %s (%s)", modelo, destino, detalhe)
        return Envio(ok=False, simulado=False, erro=detalhe)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as erro:
        logger.warning("WhatsApp: falha ao enviar o modelo %r para %s (%s)", modelo, destino, erro)
        return Envio(ok=False, simulado=False, erro=str(erro))


def _detalhe_do_erro(erro: urllib.error.HTTPError) -> str:
    """O código e a mensagem da Meta (ex.: "131042: ...") — para registrar e diagnosticar (ver WHATSAPP.md)."""
    try:
        corpo = json.loads(erro.read().decode())
        meta = corpo.get("error", {})
        return f"{meta.get('code', erro.code)}: {meta.get('message', erro.reason)}"
    except Exception:
        return f"{erro.code}: {erro.reason}"
