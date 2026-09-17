"""Máscara é da tela; o banco guarda número puro (`core.formularios`).

- `Limpeza` — CPF, telefone, CEP e valor chegam formatados e são validados já sem a máscara.
- `NaoAtrapalha` — quem digita sem máscara continua passando, e campo ausente não vira string vazia.

Sem banco: são formulários simples, e o que se prova aqui é a etapa anterior à validação.
"""

from decimal import Decimal

from django import forms
from django.test import SimpleTestCase

from core.formularios import LimpaMascara, apenas_digitos, decimal_brasileiro
from pacientes.forms import CondicaoCobrancaForm


class FormularioDeTeste(LimpaMascara, forms.Form):
    CAMPOS_NUMERICOS = ("cpf", "telefone", "cep")
    CAMPOS_DECIMAIS = ("valor",)

    cpf = forms.CharField(max_length=11)
    telefone = forms.CharField(max_length=11, required=False)
    cep = forms.CharField(max_length=8, required=False)
    valor = forms.DecimalField(max_digits=10, decimal_places=2, required=False)


class Limpeza(SimpleTestCase):
    def test_o_que_a_tela_formata_chega_ao_model_como_numero(self):
        formulario = FormularioDeTeste(data={"cpf": "529.982.247-25", "telefone": "(31) 98888-7777",
                                             "cep": "30140-071", "valor": "1.200,50"})
        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertEqual(
            (formulario.cleaned_data["cpf"], formulario.cleaned_data["telefone"],
             formulario.cleaned_data["cep"], formulario.cleaned_data["valor"]),
            ("52998224725", "31988887777", "30140071", Decimal("1200.50")))

    def test_a_mascara_nao_estoura_o_tamanho_do_campo(self):
        """O `max_length=11` do CPF roda antes de qualquer `clean_`: a limpeza precisa vir antes dele."""
        self.assertTrue(FormularioDeTeste(data={"cpf": "529.982.247-25"}).is_valid())

    def test_valor_da_cobranca_com_virgula(self):
        formulario = CondicaoCobrancaForm(data={"valor": "1.200,00", "modalidade": "POR_SESSAO"})
        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertEqual(formulario.cleaned_data["valor"], Decimal("1200.00"))


class NaoAtrapalha(SimpleTestCase):
    def test_quem_digita_so_numeros_continua_valendo(self):
        formulario = FormularioDeTeste(data={"cpf": "52998224725", "valor": "1200.50"})
        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertEqual(formulario.cleaned_data["valor"], Decimal("1200.50"))

    def test_campo_que_nao_veio_no_post_nao_e_inventado(self):
        formulario = FormularioDeTeste(data={"cpf": "52998224725"})
        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertNotIn("telefone", formulario.data)

    def test_formulario_sem_dados_nao_tenta_limpar_nada(self):
        self.assertFalse(FormularioDeTeste().is_bound)

    def test_as_funcoes_soltas(self):
        self.assertEqual(apenas_digitos("(31) 9 8888-7777"), "31988887777")
        self.assertEqual(apenas_digitos(""), "")
        self.assertEqual(decimal_brasileiro("1.200,50"), "1200.50")
        self.assertEqual(decimal_brasileiro("1200.50"), "1200.50")
        self.assertEqual(decimal_brasileiro(""), "")
