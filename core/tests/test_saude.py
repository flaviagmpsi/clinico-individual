"""A rota de saúde não pode manter o Neon acordado (ADR-145).

O Neon só suspende o compute depois de 5 minutos sem **nenhum** statement. O Render consulta `/saude/` de poucos em
poucos segundos, o dia inteiro: se essa consulta emitir qualquer coisa — um `SET LOCAL ROLE`, um savepoint, a leitura
da sessão —, o banco nunca dorme e o projeto paga compute 24 h por dia.

`CaptureQueriesContext` vê tudo o que passa por um cursor do Django, inclusive o `SET LOCAL ROLE` do middleware de
escopo e o `SAVEPOINT` do `transaction.atomic()` (aqui aninhado na transação do `TestCase`). Zero é zero.

A outra metade é a fronteira: a exceção vale só para o caminho exato. Qualquer outra rota anônima continua descendo
para `hamilton_web` (ADR-046).
"""

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext


class SaudeSemBanco(TestCase):
    def test_saude_responde_ok_sem_nenhum_statement(self):
        with CaptureQueriesContext(connection) as consultas:
            resposta = self.client.get("/saude/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.content, b"ok")
        self.assertEqual([c["sql"] for c in consultas.captured_queries], [])

    def test_cookie_de_sessao_nao_faz_a_saude_ler_a_sessao(self):
        # Um cookie qualquer (de um navegador, ou forjado) não pode puxar `django_session` para a checagem.
        self.client.cookies["sessionid"] = "uma-sessao-qualquer"
        with CaptureQueriesContext(connection) as consultas:
            resposta = self.client.get("/saude/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual([c["sql"] for c in consultas.captured_queries], [])

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[r"^saude/$"])
    def test_saude_continua_fora_do_redirecionamento_para_https(self):
        # A checagem do Render chega em HTTP pela rede interna; um 301 seria lido como serviço caído.
        resposta = self.client.get("/saude/")
        self.assertEqual(resposta.status_code, 200)

    def test_a_excecao_vale_so_para_o_caminho_exato(self):
        # Vizinhas de `/saude/` seguem o caminho normal: transação e papel da web, como toda rota anônima.
        if connection.vendor != "postgresql":
            self.skipTest("Papel de banco só existe no PostgreSQL.")
        for caminho in ("/saude", "/saude/x/", "/saudex/"):
            with self.subTest(caminho=caminho), CaptureQueriesContext(connection) as consultas:
                self.client.get(caminho)
                sql = " ".join(c["sql"] for c in consultas.captured_queries)
                self.assertIn("SET LOCAL ROLE", sql)
