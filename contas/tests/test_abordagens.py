"""O catálogo fechado e a conversão do que já estava escrito à mão (ADR-107).

O que estes testes protegem é a promessa da migração 0012: **ninguém perde o que escreveu**. O que o catálogo
reconhece vira código; o que não reconhece vira OUTRA com o texto preservado.
"""

import importlib

from django.test import SimpleTestCase

from contas import abordagens

# O nome do módulo começa com número, então não dá para importar com `from ... import`.
_MIGRACAO = importlib.import_module("contas.migrations.0012_abordagens_de_lista_fechada")


class CatalogoTest(SimpleTestCase):
    def test_nenhum_codigo_repetido_e_outra_e_o_ultimo(self):
        for catalogo in (abordagens.ABORDAGENS, abordagens.AREAS):
            codigos = [c for c, _ in catalogo]
            self.assertEqual(len(codigos), len(set(codigos)))
            self.assertEqual(codigos[-1], abordagens.OUTRA)

    def test_avaliacao_neuropsicologica_e_area_e_nao_abordagem(self):
        """Nas duas listas, a mesma pessoa contaria duas vezes e nenhum dos números fecharia."""
        self.assertIn("AVALIACAO_NEUROPSICOLOGICA", abordagens.ROTULO_DA_AREA)
        self.assertNotIn("AVALIACAO_NEUROPSICOLOGICA", abordagens.ROTULO_DA_ABORDAGEM)

    def test_reconhece_o_proprio_rotulo_independente_de_acento_e_caixa(self):
        for escrito in ("Psicanálise", "psicanalise", "  PSICANÁLISE  ", "Psicanalise"):
            self.assertEqual(abordagens.codigo_da_abordagem(escrito), "PSICANALISE", escrito)

    def test_reconhece_os_rotulos_da_lista_fechada_antiga(self):
        """A ADR-071 tinha outra grafia, e a migração 0009 gravou aqueles rótulos como texto."""
        antigos = {
            "Terapia cognitivo-comportamental": "TCC",
            "Psicologia analítica (junguiana)": "PSICOLOGIA_ANALITICA",
            "Abordagem centrada na pessoa / humanista": "CENTRADA_NA_PESSOA",
            "Fenomenológico-existencial": "FENOMENOLOGIA_EXISTENCIAL",
            "Análise do comportamento": "ANALISE_DO_COMPORTAMENTO",
            "Sistêmica / familiar": "SISTEMICA",
            "Gestalt-terapia": "GESTALT",
            "Psicodrama": "PSICODRAMA",
        }
        for escrito, codigo in antigos.items():
            self.assertEqual(abordagens.codigo_da_abordagem(escrito), codigo, escrito)

    def test_o_que_nao_esta_no_catalogo_nao_e_adivinhado(self):
        for escrito in ("Esquizoanálise", "EMDR", "", "   "):
            self.assertIsNone(abordagens.codigo_da_abordagem(escrito), escrito)

    def test_descrever_usa_a_ordem_do_catalogo_e_poe_o_escrito_no_fim(self):
        texto = abordagens.descrever(["TERAPIA_DO_ESQUEMA", abordagens.OUTRA, "GESTALT"],
                                     abordagens.ROTULO_DA_ABORDAGEM, "Esquizoanálise")
        self.assertEqual(texto, "Gestalt-terapia, Terapia do esquema, Esquizoanálise")

    def test_descrever_ignora_o_escrito_se_outra_nao_estiver_marcada(self):
        texto = abordagens.descrever(["GESTALT"], abordagens.ROTULO_DA_ABORDAGEM, "Esquizoanálise")
        self.assertEqual(texto, "Gestalt-terapia")


class ConversaoTest(SimpleTestCase):
    """A função que a migração 0012 usa. Testada direto, sem banco: é aritmética de texto."""

    converter = staticmethod(_MIGRACAO._converter)

    def test_o_que_o_catalogo_conhece_vira_codigo_sem_repetir(self):
        codigos, escrito = self.converter(["Psicanálise", "psicanalise", "Gestalt-terapia"],
                                          abordagens.codigo_da_abordagem)
        self.assertEqual(codigos, ["PSICANALISE", "GESTALT"])
        self.assertEqual(escrito, "")

    def test_o_que_o_catalogo_nao_conhece_vira_outra_com_o_texto_preservado(self):
        codigos, escrito = self.converter(["Psicanálise", "Esquizoanálise"], abordagens.codigo_da_abordagem)
        self.assertEqual(codigos, ["PSICANALISE", abordagens.OUTRA])
        self.assertEqual(escrito, "Esquizoanálise")

    def test_varias_desconhecidas_cabem_juntas_no_mesmo_campo(self):
        codigos, escrito = self.converter(["Esquizoanálise", "EMDR"], abordagens.codigo_da_abordagem)
        self.assertEqual(codigos, [abordagens.OUTRA])
        self.assertEqual(escrito, "Esquizoanálise, EMDR")

    def test_quem_nao_tinha_nada_continua_sem_nada(self):
        self.assertEqual(self.converter([], abordagens.codigo_da_abordagem), ([], ""))
        self.assertEqual(self.converter(None, abordagens.codigo_da_abordagem), ([], ""))

    def test_o_texto_de_outra_cabe_na_coluna(self):
        """A coluna tem 120 letras; um histórico longo não pode derrubar a migração."""
        codigos, escrito = self.converter([f"Abordagem inventada {n}" for n in range(20)],
                                          abordagens.codigo_da_abordagem)
        self.assertEqual(codigos, [abordagens.OUTRA])
        self.assertLessEqual(len(escrito), 120)
