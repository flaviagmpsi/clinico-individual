"""A escrita assistida do registro de sessão (ADR-111).

O que estes testes protegem, em ordem de gravidade: que **nenhum nome conhecido sai da máquina**, que a IA não
recebe dado de identificação, e que o recurso só aparece com as duas chaves — a do servidor e a da psicóloga.

Nada aqui chama a OpenAI. A anonimização e a montagem do contexto são funções puras justamente para poderem ser
testadas sem rede; as views são testadas com a chamada trocada por uma que não sai da máquina.
"""

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from prontuarios import ia


class Anonimizacao(SimpleTestCase):
    def test_tira_o_nome_inteiro_e_cada_parte_dele(self):
        texto = "Maria Clara Souza chegou atrasada; Maria falou da mãe, e Souza é o sobrenome do pai."
        limpo = ia.anonimizar(texto, nomes=["Maria Clara Souza"])
        for pedaco in ("Maria", "Clara", "Souza"):
            self.assertNotIn(pedaco, limpo)
        self.assertIn("chegou atrasada", limpo)

    def test_o_nome_inteiro_vira_um_substituto_so(self):
        """Trocar parte por parte deixaria três marcas emendadas onde havia um nome."""
        limpo = ia.anonimizar("Falei com Ana Ribeiro ontem.", nomes=["Ana Ribeiro"])
        self.assertEqual(limpo.count("[nome omitido]"), 1)
        self.assertEqual(limpo, "Falei com [nome omitido] ontem.")

    def test_ignora_acento_porque_a_transcricao_erra_acento_o_tempo_todo(self):
        for escrito in ("Antônio", "ANTONIO", "Antonio"):
            with self.subTest(escrito=escrito):
                limpo = ia.anonimizar(f"o paciente {escrito} disse", nomes=["Antônio"])
                self.assertEqual(limpo, "o paciente [nome omitido] disse")

    def test_nome_que_tambem_e_palavra_comum_so_sai_com_inicial_maiuscula(self):
        """Achado real: uma paciente chamada Vitória tinha o relato corrompido.

        "contou uma vitória no trabalho" virava "contou uma [nome omitido] no trabalho", e o relato chegava
        assim ao modelo — em silêncio, porque ninguém compara o antes com o depois. Exigir inicial maiúscula
        separa o nome próprio do substantivo, que é como a escrita já os separa.
        """
        casos = [
            ("Vitória Campos", "A Vitória contou uma vitória e falou dos campos do avô.",
             "A [nome omitido] contou uma vitória e falou dos campos do avô."),
            ("Rosa Leão", "A Rosa ganhou uma rosa e tem coração de leão.",
             "A [nome omitido] ganhou uma rosa e tem coração de leão."),
            ("Rafael Pinto", "O Rafael desenhou um pinto.",
             "O [nome omitido] desenhou um pinto."),
        ]
        for nome, antes, esperado in casos:
            with self.subTest(nome=nome):
                self.assertEqual(ia.anonimizar(antes, nomes=[nome]), esperado)

    def test_o_nome_composto_sai_mesmo_em_minuscula(self):
        """"vitória campos" em sequência não é frase de ninguém — aí a caixa pode ser ignorada com segurança."""
        self.assertEqual(ia.anonimizar("falei com vitória campos ontem", nomes=["Vitória Campos"]),
                         "falei com [nome omitido] ontem")

    def test_dobrar_acento_nao_muda_o_tamanho_do_texto(self):
        """A busca é no texto sem acento e o recorte no original: um caractere a mais desalinharia tudo.

        Há caracteres que se decompõem em vários — a ligadura "ﬁ" vira "fi" —, e a versão ingênua da função
        cortava a frase no lugar errado dali em diante.
        """
        for texto in ("ação", "ﬁcou", "coração ﬁel", "Ana ﬁcou à toa"):
            with self.subTest(texto=texto):
                self.assertEqual(len(ia._sem_acento(texto)), len(texto))

    def test_o_texto_em_volta_do_nome_fica_intato_mesmo_com_ligadura(self):
        self.assertEqual(ia.anonimizar("Ana ﬁcou à toa hoje", nomes=["Ana"]),
                         "[nome omitido] ﬁcou à toa hoje")

    def test_nao_come_pedaco_de_palavra_maior(self):
        """"Ana" dentro de "ananás" não é a paciente — `\\b` existe para isso."""
        limpo = ia.anonimizar("Ana trouxe ananás e falou de bananas.", nomes=["Ana"])
        self.assertIn("ananás", limpo)
        self.assertIn("bananas", limpo)
        self.assertNotIn("Ana ", limpo)

    def test_conectivo_e_pedaco_curto_ficam_de_fora(self):
        """Trocar "de" e "da" destruiria o texto e não esconderia ninguém."""
        limpo = ia.anonimizar("A paciente falou da escola e de casa.", nomes=["Ana de Souza da Silva"])
        self.assertIn("da escola", limpo)
        self.assertIn("de casa", limpo)

    def test_esconde_varios_nomes_de_uma_vez(self):
        limpo = ia.anonimizar("Bruno contou que Helena ligou.", nomes=["Bruno Carvalho", "Helena Castro"])
        self.assertNotIn("Bruno", limpo)
        self.assertNotIn("Helena", limpo)

    def test_texto_vazio_e_nome_vazio_nao_quebram(self):
        self.assertEqual(ia.anonimizar("", nomes=["Ana"]), "")
        self.assertEqual(ia.anonimizar("nada a esconder", nomes=["", "  ", None]), "nada a esconder")


class ContextoDaIA(SimpleTestCase):
    def test_o_contexto_nao_carrega_nada_que_identifique_alguem(self):
        """Se um dia alguém acrescentar um campo com nome aqui, este teste cai."""
        campos = set(ia.Contexto.__dataclass_fields__)
        self.assertEqual(campos, {"abordagem", "modalidade", "frequencia", "numero_da_sessao"})

    def test_o_texto_do_contexto_omite_o_que_esta_vazio(self):
        self.assertEqual(ia.Contexto().como_texto(), "")
        texto = ia.Contexto(abordagem="Gestalt-terapia", numero_da_sessao=3).como_texto()
        self.assertIn("Gestalt-terapia", texto)
        self.assertIn("3ª sessão", texto)
        self.assertNotIn("Modalidade", texto)


class PromptDoSistema(SimpleTestCase):
    def test_proibe_identificacao_e_hipotese(self):
        """As duas regras que, se sumirem do prompt, produzem documento errado sem ninguém perceber."""
        prompt = ia.PROMPT_DO_SISTEMA
        for proibido in ("NÃO escreva bloco de identificação", "CPF", "CRP",
                         "hipóteses diagnósticas não compartilhadas", "transcrição literal"):
            self.assertIn(proibido, prompt)

    def test_sao_quatro_pontos(self):
        """O quinto do original virou instrução do que não dizer; se voltar a cinco, é engano (ADR-111)."""
        self.assertEqual(len(ia.PONTOS), 4)

    def test_proibe_inventar_e_da_a_frase_exata_para_o_que_falta(self):
        """Num teste real, o modelo completou um tópico que o relato não mencionava. A frase exata resolveu.

        Sem ela, o modelo escrevia o que seria "clinicamente coerente" — invenção num documento que é meio de
        prova. Se esta instrução sair do prompt, o comportamento volta e ninguém percebe até ser tarde.
        """
        prompt = ia.PROMPT_DO_SISTEMA
        self.assertIn("NÃO invente NADA", prompt)
        self.assertIn("Sem registro sobre este ponto nesta sessão.", prompt)
        self.assertIn("ausência de menção não é negação", prompt)

    def test_proibe_atribuir_tecnica_a_escola_teorica(self):
        """Outro achado real: o modelo escreveu "psicoeducação de acordo com os princípios da Gestalt-terapia".

        Psicoeducação é TCC. Ele pegou a abordagem passada como contexto e a grudou em técnicas que não são
        dela — uma falsidade clínica num documento que a psicóloga assina.
        """
        self.assertIn("NÃO\n  afirme que uma técnica", ia.PROMPT_DO_SISTEMA)
        self.assertIn("não atribua técnicas a ela",
                      ia.Contexto(abordagem="Gestalt-terapia").como_texto())


class SemChave(SimpleTestCase):
    @override_settings(OPENAI_API_KEY="")
    def test_sem_chave_o_recurso_se_declara_indisponivel(self):
        self.assertFalse(ia.disponivel())
        with self.assertRaises(ia.IAIndisponivel):
            ia.sintetizar("qualquer relato")

    @override_settings(OPENAI_API_KEY="sk-de-mentira")
    def test_com_chave_mas_sem_relato_tambem_recusa(self):
        self.assertTrue(ia.disponivel())
        with self.assertRaises(ia.IAIndisponivel):
            ia.sintetizar("   ")

    def test_o_recado_de_erro_e_em_portugues_e_diz_o_que_fazer(self):
        self.assertIn("sem crédito", ia._recado(Exception("Error code: 429 - insufficient_quota")))
        self.assertIn("recusada", ia._recado(Exception("invalid_api_key")))
        self.assertIn("à mão", ia._recado(Exception("qualquer outra coisa")))
