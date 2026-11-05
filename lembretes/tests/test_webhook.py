"""O webhook do WhatsApp (ADR-144, RF11/RF12/RF16): verificação, assinatura HMAC e a resposta Sim/Não.

`TransactionTestCase` pelo mesmo motivo do disparo: o motor troca o papel do Postgres por psicólogo, e `SET LOCAL
ROLE` se prende à transação. O webhook é anônimo (corre sob `hamilton_web`) e desce até o tenant que reconhece o
`wamid` da mensagem respondida — se a ponte de papel/RLS estiver errada, a resposta não é tratada aqui.
"""

import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse

from contas.models import Psicologo
from core import contexto
from lembretes import meta
from lembretes.meta import Envio
from lembretes.models import LembreteEnviado
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente

SENHA = "senha-de-teste-123"
SEGREDO = "segredo-do-app"
VERIFY = "token-de-verificacao"
NUMERO = "123456789"


class MesmoNumero(SimpleTestCase):
    """O 9º dígito que vai e vem no celular brasileiro não pode separar o mesmo telefone (RF16)."""

    def test_com_e_sem_o_nono_digito_sao_o_mesmo(self):
        self.assertTrue(meta.mesmo_numero("+55 31 99999-0000", "553199990000"))  # wa_id veio sem o 9
        self.assertTrue(meta.mesmo_numero("5531999990000", "31999990000"))       # com e sem o +55

    def test_numeros_diferentes_nao_casam(self):
        self.assertFalse(meta.mesmo_numero("5531999990000", "5531988887777"))
        self.assertFalse(meta.mesmo_numero("", "5531999990000"))


@override_settings(WHATSAPP_APP_SECRET=SEGREDO, WHATSAPP_WEBHOOK_VERIFY_TOKEN=VERIFY,
                   WHATSAPP_PHONE_NUMBER_ID=NUMERO, WHATSAPP_SIMULADO=True)
class WebhookDoWhatsApp(TransactionTestCase):
    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.webhook@exemplo.com", password=SENHA, nome_completo="Ana Ribeiro", cpf="11111111111",
            telefone="31988887777", crp_regiao="04", crp_numero="313131",
            whatsapp_ligado=True, whatsapp_confirmacoes=True)
        self.rota = reverse("whatsapp_webhook")
        self.wamid = "wamid.HBgM-abc123"
        with contexto.como(self.ana.pk):
            caso = cadastrar_paciente(Paciente(nome="João Silva", telefone="31999990000"))
            self.paciente = caso.pacientes.first()
            LembreteEnviado.objects.create(
                assunto=f"sessao:{self.paciente.pk}:202611051400", wamid=self.wamid, simulado=True)

    # ── helpers ──────────────────────────────────────────────────────────────────────────────────────────────
    def _assinar(self, corpo: bytes) -> str:
        return "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()

    def _payload(self, texto="Sim", context_id=None, de="5531999990000"):
        return {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": NUMERO},
            "messages": [{"from": de, "id": "msg-entrante", "type": "button",
                          "context": {"id": context_id or self.wamid},
                          "button": {"text": texto, "payload": texto}}],
        }}]}]}

    def _postar(self, payload):
        corpo = json.dumps(payload).encode()
        return self.client.post(self.rota, data=corpo, content_type="application/json",
                                HTTP_X_HUB_SIGNATURE_256=self._assinar(corpo))

    def _respostas_registradas(self) -> int:
        with contexto.como(self.ana.pk):
            return LembreteEnviado.objects.filter(assunto__startswith="resposta:").count()

    # ── verificação (GET) ────────────────────────────────────────────────────────────────────────────────────
    def test_get_com_token_certo_devolve_o_desafio(self):
        resp = self.client.get(self.rota, {"hub.mode": "subscribe", "hub.verify_token": VERIFY,
                                            "hub.challenge": "42"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"42")

    def test_get_com_token_errado_recusa(self):
        resp = self.client.get(self.rota, {"hub.mode": "subscribe", "hub.verify_token": "errado",
                                            "hub.challenge": "42"})
        self.assertEqual(resp.status_code, 403)

    # ── assinatura (POST) ────────────────────────────────────────────────────────────────────────────────────
    def test_post_sem_assinatura_valida_recusa_e_nao_processa(self):
        corpo = json.dumps(self._payload()).encode()
        resp = self.client.post(self.rota, data=corpo, content_type="application/json",
                                HTTP_X_HUB_SIGNATURE_256="sha256=errado")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._respostas_registradas(), 0)

    # ── a resposta Sim/Não (RF11, RF12) ──────────────────────────────────────────────────────────────────────
    def test_sim_avisa_o_psicologo_e_agradece_ao_paciente_uma_vez(self):
        with patch.object(meta, "enviar_modelo", return_value=Envio(ok=True, simulado=True)) as modelo, \
             patch.object(meta, "enviar_texto", return_value=Envio(ok=True, simulado=True)) as texto:
            resp = self._postar(self._payload("Sim"))
            self.assertEqual(resp.status_code, 200)
            modelo.assert_called_once()
            self.assertEqual(modelo.call_args.args[0], self.ana.telefone)
            self.assertEqual(modelo.call_args.args[1], "paciente_confirmou")
            texto.assert_called_once()
            self.assertEqual(texto.call_args.args[0], self.paciente.telefone)
        self.assertEqual(self._respostas_registradas(), 1)

        # Idempotente: a Meta reenvia o mesmo clique e nada é mandado de novo (RF12).
        with patch.object(meta, "enviar_modelo") as modelo, patch.object(meta, "enviar_texto") as texto:
            self.assertEqual(self._postar(self._payload("Sim")).status_code, 200)
            modelo.assert_not_called()
            texto.assert_not_called()
        self.assertEqual(self._respostas_registradas(), 1)

    def test_nao_avisa_o_psicologo_que_o_paciente_nao_vem(self):
        with patch.object(meta, "enviar_modelo", return_value=Envio(ok=True, simulado=True)) as modelo, \
             patch.object(meta, "enviar_texto", return_value=Envio(ok=True, simulado=True)):
            self._postar(self._payload("Não"))
            self.assertEqual(modelo.call_args.args[1], "paciente_nao_vem")

    def test_resposta_sem_lembrete_conhecido_e_ignorada(self):
        with patch.object(meta, "enviar_modelo") as modelo, patch.object(meta, "enviar_texto") as texto:
            resp = self._postar(self._payload("Sim", context_id="wamid.desconhecido"))
            self.assertEqual(resp.status_code, 200)
            modelo.assert_not_called()
            texto.assert_not_called()
        self.assertEqual(self._respostas_registradas(), 0)
