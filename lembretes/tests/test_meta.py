"""O adaptador da Meta (ADR-144). Nenhum teste toca a rede — `urlopen` é sempre simulado.

Prova os dois lados que importam: em modo simulado **não** chama a Meta; em modo ativo monta o payload exato e
devolve o id; e erro da Meta **não sobe** — vira `Envio(ok=False)`.
"""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from lembretes import meta


class Normalizacao(SimpleTestCase):
    def test_poe_55_com_ddd_e_so_digitos(self):
        self.assertEqual(meta.normalizar_numero("(31) 98888-7777"), "+5531988887777")
        self.assertEqual(meta.normalizar_numero("+55 31 98888-7777"), "+5531988887777")

    def test_sem_numero_e_vazio(self):
        self.assertEqual(meta.normalizar_numero(""), "")
        self.assertEqual(meta.normalizar_numero(None), "")


@override_settings(WHATSAPP_SIMULADO=True)
class ModoSimulado(SimpleTestCase):
    def test_nao_chama_a_rede(self):
        with patch("lembretes.meta.urllib.request.urlopen") as urlopen:
            envio = meta.enviar_modelo("31988887777", "agenda_do_dia", ["Ana", "5", "08:00"])
        self.assertTrue(envio.ok)
        self.assertTrue(envio.simulado)
        urlopen.assert_not_called()

    def test_sem_numero_falha_sem_enviar(self):
        envio = meta.enviar_modelo("", "agenda_do_dia", ["Ana"])
        self.assertFalse(envio.ok)
        self.assertIn("número", envio.erro)


def _resposta_fake(payload: dict) -> MagicMock:
    resposta = MagicMock()
    resposta.read.return_value = json.dumps(payload).encode()
    contexto = MagicMock()
    contexto.__enter__.return_value = resposta
    return contexto


@override_settings(WHATSAPP_SIMULADO=False, WHATSAPP_ATIVO=True, WHATSAPP_TOKEN="EAA_teste",
                   WHATSAPP_PHONE_NUMBER_ID="1413166918549157", WHATSAPP_API_VERSION="v26.0")
class ModoAtivo(SimpleTestCase):
    def test_monta_o_payload_certo_e_devolve_o_id(self):
        capturado = {}

        def fake_urlopen(requisicao, timeout=None):
            capturado["url"] = requisicao.full_url
            capturado["auth"] = requisicao.get_header("Authorization")
            capturado["corpo"] = json.loads(requisicao.data.decode())
            return _resposta_fake({"messages": [{"id": "wamid.ABC"}]})

        with patch("lembretes.meta.urllib.request.urlopen", side_effect=fake_urlopen):
            envio = meta.enviar_modelo("(31) 98888-7777", "agenda_do_dia", ["Ana", 5, "08:00"])

        self.assertTrue(envio.ok)
        self.assertFalse(envio.simulado)
        self.assertEqual(envio.id_mensagem, "wamid.ABC")
        self.assertIn("1413166918549157/messages", capturado["url"])
        self.assertEqual(capturado["auth"], "Bearer EAA_teste")
        corpo = capturado["corpo"]
        self.assertEqual(corpo["to"], "+5531988887777")
        self.assertEqual(corpo["template"]["name"], "agenda_do_dia")
        self.assertEqual(corpo["template"]["language"]["code"], "pt_BR")
        parametros = corpo["template"]["components"][0]["parameters"]
        self.assertEqual([p["text"] for p in parametros], ["Ana", "5", "08:00"])

    def test_erro_da_meta_nao_sobe_e_vira_envio_falho(self):
        erro = urllib.error.HTTPError(
            url="x", code=400, msg="Bad Request", hdrs=None,
            fp=io.BytesIO(json.dumps({"error": {"code": 131042, "message": "falta cartão"}}).encode()))
        with patch("lembretes.meta.urllib.request.urlopen", side_effect=erro):
            envio = meta.enviar_modelo("31988887777", "agenda_do_dia", ["Ana"])
        self.assertFalse(envio.ok)
        self.assertFalse(envio.simulado)
        self.assertIn("131042", envio.erro)
