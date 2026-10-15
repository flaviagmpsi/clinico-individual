"""Senha forte no cadastro (ADR-130): maiúscula, minúscula, número e símbolo.

Sem banco — é validação pura. Testa o validador direto e a mensagem, que lista o que **falta**.
"""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from contas.validacao_de_senha import SenhaForteValidator

v = SenhaForteValidator()


class SenhaForte(SimpleTestCase):
    def test_senha_completa_passa(self):
        v.validate("Flavia@2026")  # não levanta

    def test_sem_maiuscula_e_recusada(self):
        with self.assertRaises(ValidationError) as c:
            v.validate("flavia@2026")
        self.assertIn("maiúscula", c.exception.messages[0])

    def test_sem_minuscula_e_recusada(self):
        with self.assertRaises(ValidationError) as c:
            v.validate("FLAVIA@2026")
        self.assertIn("minúscula", c.exception.messages[0])

    def test_sem_numero_e_recusada(self):
        with self.assertRaises(ValidationError) as c:
            v.validate("Flavia@teste")
        self.assertIn("número", c.exception.messages[0])

    def test_sem_simbolo_e_recusada(self):
        with self.assertRaises(ValidationError) as c:
            v.validate("Flavia2026")
        self.assertIn("símbolo", c.exception.messages[0])

    def test_a_mensagem_lista_tudo_que_falta(self):
        with self.assertRaises(ValidationError) as c:
            v.validate("abcdefgh")  # falta maiúscula, número e símbolo
        msg = c.exception.messages[0]
        self.assertIn("maiúscula", msg)
        self.assertIn("número", msg)
        self.assertIn("símbolo", msg)


class NoCadastroDeVerdade(SimpleTestCase):
    def test_o_validador_esta_na_lista_do_django(self):
        from django.conf import settings
        nomes = [v["NAME"] for v in settings.AUTH_PASSWORD_VALIDATORS]
        self.assertIn("contas.validacao_de_senha.SenhaForteValidator", nomes)

    def test_validate_password_do_django_aplica_a_regra(self):
        from django.contrib.auth.password_validation import validate_password
        with self.assertRaises(ValidationError):
            validate_password("Flavia2026")  # sem símbolo
        validate_password("Flavia@2026")     # completa, não levanta
