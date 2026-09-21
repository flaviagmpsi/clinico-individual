"""As telas dos documentos psicológicos, vistas por dois psicólogos ao mesmo tempo (ADR-076).

`TransactionTestCase` pelo motivo de sempre nas telas: o middleware troca o papel do banco com `SET LOCAL ROLE`.
"""

from datetime import date

from django.test import TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo
from core import contexto
from core.models import RegistroAuditoria
from documentos import modelos, servicos
from documentos.models import Documento
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente

SENHA = "senha-de-teste-123"

DECLARACAO = {
    "finalidade": "comprovação junto à Escola Municipal Crescer e Aprender", "atendido": "Marcos Tela",
    "cpf": "", "informacao": "compareceu a atendimento psicológico em 30 de maio de 2025, das 16h às 17h.",
    "local": "Belo Horizonte", "data": "2025-05-31", "psicologo_nome": "Ana Tela", "psicologo_crp": "CRP 04/757575",
}


def criar_psicologo(email, nome, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=nome, cpf=cpf, telefone="31988887777",
        crp_regiao="04", crp_numero=crp, cidade="Belo Horizonte", nome_clinica="Consultório da Ana")


class BaseTelasDocumentos(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.teladoc@exemplo.com", "Ana Tela", "11111111111", "757575")
        self.bruno = criar_psicologo("bruno.teladoc@exemplo.com", "Bruno Tela", "22222222222", "767676")
        with contexto.como(self.ana.pk):
            self.marcos = Paciente(nome="Marcos Tela", cpf="52998224725", data_nascimento=date(1988, 4, 12))
            cadastrar_paciente(self.marcos)
        with contexto.como(self.bruno.pk):
            self.carla = Paciente(nome="Carla Tela")
            cadastrar_paciente(self.carla)
            self.do_bruno = servicos.salvar_rascunho("declaracao", {"atendido": "Carla Tela"}, paciente=self.carla)

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def modelo(self, codigo="declaracao"):
        return reverse("documentos:modelo", args=[codigo])


class ExigeLoginENaoAtravessa(BaseTelasDocumentos):
    def test_nenhuma_tela_abre_sem_login(self):
        for rota in [reverse("documentos:aba"), self.modelo(), reverse("documentos:editar", args=[self.do_bruno.pk]),
                     reverse("documentos:imprimir", args=[self.do_bruno.pk])]:
            with self.subTest(rota=rota):
                resposta = self.client.get(rota)
                self.assertEqual(resposta.status_code, 302)
                self.assertIn(reverse("contas:entrar"), resposta["Location"])

    def test_documento_e_paciente_alheios_dao_404(self):
        self.entrar(self.ana)
        for rota in [reverse("documentos:editar", args=[self.do_bruno.pk]),
                     reverse("documentos:imprimir", args=[self.do_bruno.pk]),
                     f"{self.modelo()}?paciente={self.carla.pk}"]:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 404)
        for nome in ["documentos:excluir", "documentos:duplicar"]:
            self.assertEqual(self.client.post(reverse(nome, args=[self.do_bruno.pk])).status_code, 404)
        self.assertEqual(self.client.post(self.modelo(), {**DECLARACAO, "paciente": self.carla.pk}).status_code, 404)
        self.assertEqual(Documento.objetos_todos.count(), 1)

    def test_a_aba_lista_so_os_proprios_documentos(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_rascunho("declaracao", {"atendido": "Marcos Tela"}, paciente=self.marcos)
        self.entrar(self.ana)
        resposta = self.client.get(reverse("documentos:aba"))
        self.assertContains(resposta, "Marcos Tela")
        self.assertNotContains(resposta, "Carla Tela")


class SubAbasDosModelos(BaseTelasDocumentos):
    def test_cada_modelo_abre_com_a_orientacao_e_os_campos_em_branco(self):
        self.entrar(self.ana)
        for modelo in modelos.CATALOGO:
            with self.subTest(modelo=modelo.codigo):
                resposta = self.client.get(self.modelo(modelo.codigo))
                self.assertContains(resposta, "Como o CFP espera este documento")
                self.assertContains(resposta, "Antes de emitir")
                self.assertContains(resposta, modelo.orientacoes[0].titulo)
                self.assertContains(resposta, modelo.campos[0].rotulo)

    def test_preenche_se_dentro_da_folha_do_documento(self):
        """ADR-077: a tela já é o documento — título, texto e assinatura —, com os campos no lugar onde caem."""
        self.entrar(self.ana)
        corpo = self.client.get(self.modelo()).content.decode()
        folha = corpo[corpo.index('<div class="folha">'):]
        self.assertIn("<h1>DECLARAÇÃO</h1>", folha)
        self.assertIn("Consultório da Ana", folha)  # o timbre
        # O texto do documento envolve os campos: "Declara-se, para fins de [finalidade], que [nome]…".
        ordem = [folha.index("Declara-se, para fins de"), folha.index('name="finalidade"'), folha.index(", que "),
                 folha.index('name="atendido"'), folha.index('name="informacao"'), folha.index('name="local"'),
                 folha.index('name="psicologo_nome"')]
        self.assertEqual(ordem, sorted(ordem))

    def test_cada_campo_da_folha_leva_a_explicacao_do_que_se_espera_nele(self):
        self.entrar(self.ana)
        for modelo in modelos.CATALOGO:
            corpo = self.client.get(self.modelo(modelo.codigo)).content.decode()
            with self.subTest(modelo=modelo.codigo):
                self.assertEqual(corpo.count("data-ajuda="), len(modelo.campos))
                for campo in modelo.campos:
                    self.assertIn(f'name="{campo.nome}"', corpo)

    def test_documento_em_itens_traz_os_titulos_da_resolucao_na_folha(self):
        self.entrar(self.ana)
        corpo = self.client.get(self.modelo("laudo")).content.decode()
        titulos = ["Identificação", "Descrição da demanda", "Procedimento", "Análise", "Conclusão", "Referências"]
        posicoes = [corpo.index(f"<h2>{titulo}</h2>") for titulo in titulos]
        self.assertEqual(posicoes, sorted(posicoes))

    def test_a_declaracao_avisa_que_nao_pode_conter_sintoma(self):
        self.entrar(self.ana)
        self.assertContains(self.client.get(self.modelo()), "vedado registrar sintomas")

    def test_em_branco_vem_so_a_assinatura_e_com_paciente_a_identificacao(self):
        self.entrar(self.ana)
        em_branco = self.client.get(self.modelo()).content.decode()
        self.assertIn('value="Ana Tela"', em_branco)
        self.assertIn('value="CRP 04/757575"', em_branco)
        self.assertNotIn('value="Marcos Tela"', em_branco)

        com_paciente = self.client.get(f"{self.modelo()}?paciente={self.marcos.pk}").content.decode()
        self.assertIn('value="Marcos Tela"', com_paciente)
        self.assertIn('value="529.982.247-25"', com_paciente)

    def test_modelo_inexistente_da_404(self):
        self.entrar(self.ana)
        self.assertEqual(self.client.get(self.modelo("receita-medica")).status_code, 404)


class ArquivoDoPaciente(BaseTelasDocumentos):
    """ADR-096: na ficha do paciente, a aba Documentos é o arquivo dele — o que foi produzido sobre ele vem primeiro."""

    def setUp(self):
        super().setUp()
        with contexto.como(self.ana.pk):
            self.lucia = Paciente(nome="Lúcia Outra")
            cadastrar_paciente(self.lucia)
            servicos.salvar_rascunho("relatorio", {"atendido": "Lúcia Outra"}, paciente=self.lucia)
        self.entrar(self.ana)
        self.do_marcos = reverse("documentos:aba") + f"?paciente={self.marcos.pk}"

    def test_o_relatorio_produzido_pela_tela_fica_guardado_no_perfil_do_paciente(self):
        self.client.post(self.modelo("relatorio"), {"atendido": "Marcos Tela", "paciente": self.marcos.pk,
                                                    "finalidade": "apresentação ao psiquiatra", "acao": "rascunho"})
        corpo = self.client.get(self.do_marcos).content.decode()
        self.assertIn("Documentos de Marcos Tela", corpo)
        self.assertIn("Relatório psicológico", corpo[:corpo.index("Produzir um documento sobre")])
        self.assertIn("1 guardado", corpo)
        # Só os dele — o da Lúcia não aparece aqui, e aparece na aba geral.
        self.assertNotIn("Lúcia Outra", corpo)
        self.assertContains(self.client.get(reverse("documentos:aba")), "Lúcia Outra")

    def test_os_guardados_vem_antes_dos_modelos_e_a_ficha_leva_ate_eles(self):
        corpo = self.client.get(self.do_marcos).content.decode()
        self.assertLess(corpo.index("Documentos de Marcos Tela"), corpo.index("Produzir um documento sobre"))
        self.assertLess(corpo.index('<ul class="nav nav-tabs">'), corpo.index("Documentos de Marcos Tela"))
        self.assertIn("Nenhum documento produzido sobre Marcos Tela ainda", corpo)
        self.assertContains(self.client.get(reverse("pacientes:detalhe", args=[self.marcos.pk])), self.do_marcos)

    def test_documento_emitido_volta_para_o_arquivo_do_paciente(self):
        self.client.post(self.modelo(), {**DECLARACAO, "paciente": self.marcos.pk, "acao": "emitir"})
        documento = Documento.objetos_todos.get(paciente=self.marcos)
        self.assertContains(self.client.get(reverse("documentos:imprimir", args=[documento.pk])), self.do_marcos)
        corpo = self.client.get(self.do_marcos).content.decode()
        self.assertIn("emitido", corpo[:corpo.index("Produzir um documento sobre")])


class EscritaPelaTela(BaseTelasDocumentos):
    def test_salvar_rascunho_continuar_e_emitir(self):
        self.entrar(self.ana)
        resposta = self.client.post(self.modelo(), {"atendido": "Marcos Tela", "paciente": self.marcos.pk,
                                                    "acao": "rascunho"})
        documento = Documento.objetos_todos.get(paciente=self.marcos)
        self.assertRedirects(resposta, reverse("documentos:editar", args=[documento.pk]),
                             fetch_redirect_response=False)
        self.assertTrue(documento.rascunho)

        resposta = self.client.post(reverse("documentos:editar", args=[documento.pk]),
                                    {**DECLARACAO, "paciente": self.marcos.pk, "acao": "emitir"})
        self.assertRedirects(resposta, reverse("documentos:imprimir", args=[documento.pk]),
                             fetch_redirect_response=False)
        documento.refresh_from_db()
        self.assertFalse(documento.rascunho)

    def test_emitir_incompleto_explica_guarda_o_rascunho_e_nao_o_duplica(self):
        """A recusa leva à tela do rascunho salvo: insistir de lá regrava o mesmo, em vez de criar outro."""
        self.entrar(self.ana)
        resposta = self.client.post(self.modelo(), {"atendido": "Marcos Tela", "acao": "emitir"}, follow=True)
        documento = Documento.objetos_todos.get(dados__atendido="Marcos Tela")
        self.assertEqual(resposta.redirect_chain[-1][0], reverse("documentos:editar", args=[documento.pk]))
        self.assertContains(resposta, "Para emitir, preencha")
        self.assertContains(resposta, "O rascunho ficou salvo")

        self.client.post(reverse("documentos:editar", args=[documento.pk]), {"atendido": "Marcos Tela", "acao": "emitir"})
        self.assertEqual(Documento.objetos_todos.filter(dados__atendido="Marcos Tela").count(), 1)
        self.assertTrue(Documento.objetos_todos.get(pk=documento.pk).rascunho)

    def test_a_folha_impressa_traz_o_documento_composto(self):
        with contexto.como(self.ana.pk):
            documento = servicos.emitir(servicos.salvar_rascunho("declaracao", DECLARACAO, paciente=self.marcos))
        self.entrar(self.ana)
        resposta = self.client.get(reverse("documentos:imprimir", args=[documento.pk]))
        for texto in ["DECLARAÇÃO", "Declara-se, para fins de comprovação junto à Escola",
                      "Belo Horizonte, 31 de maio de 2025", "CRP 04/757575", "Consultório da Ana"]:
            with self.subTest(texto=texto):
                self.assertContains(resposta, texto)
        self.assertNotContains(resposta, "RASCUNHO")
        self.assertTrue(RegistroAuditoria.objetos_todos.filter(
            acao=RegistroAuditoria.Acao.VER, alvo="documentos.documento", titular_id=self.marcos.pk).exists())

    def test_emitido_nao_se_edita_pela_tela_mas_se_copia(self):
        with contexto.como(self.ana.pk):
            documento = servicos.emitir(servicos.salvar_rascunho("declaracao", DECLARACAO, paciente=self.marcos))
        self.entrar(self.ana)
        editar = reverse("documentos:editar", args=[documento.pk])
        imprimir = reverse("documentos:imprimir", args=[documento.pk])
        self.assertRedirects(self.client.get(editar), imprimir, fetch_redirect_response=False)
        self.assertRedirects(self.client.post(editar, {**DECLARACAO, "atendido": "Adulterado", "acao": "rascunho"}),
                             imprimir, fetch_redirect_response=False)
        documento.refresh_from_db()
        self.assertEqual(documento.dados["atendido"], "Marcos Tela")

        self.client.post(reverse("documentos:duplicar", args=[documento.pk]))
        self.assertEqual(Documento.objetos_todos.filter(paciente=self.marcos, emitido_em__isnull=True).count(), 1)

    def test_rascunho_se_exclui_e_a_barra_lateral_leva_a_aba(self):
        with contexto.como(self.ana.pk):
            documento = servicos.salvar_rascunho("declaracao", {"atendido": "Marcos Tela"})
        self.entrar(self.ana)
        self.assertContains(self.client.get(reverse("painel")), reverse("documentos:aba"))
        self.assertEqual(self.client.post(reverse("documentos:excluir", args=[documento.pk])).status_code, 302)
        self.assertFalse(Documento.objetos_todos.filter(pk=documento.pk).exists())


class SalvarEmArquivo(BaseTelasDocumentos):
    """PDF e DOCX (ADR-078): mesma composição da folha; exportar entra na trilha; rascunho sai marcado."""

    def baixar(self, documento, formato="pdf"):
        return reverse("documentos:baixar", args=[documento.pk, formato])

    def test_emitido_baixa_em_pdf_e_docx_e_registra_a_exportacao(self):
        with contexto.como(self.ana.pk):
            documento = servicos.emitir(servicos.salvar_rascunho("declaracao", DECLARACAO, paciente=self.marcos))
        self.entrar(self.ana)
        pdf = self.client.get(self.baixar(documento))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertIn('filename="declaracao-marcos-tela.pdf"', pdf["Content-Disposition"])
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        docx = self.client.get(self.baixar(documento, "docx"))
        self.assertIn("wordprocessingml", docx["Content-Type"])
        self.assertTrue(docx.content.startswith(b"PK"))
        self.assertEqual(RegistroAuditoria.objetos_todos.filter(
            acao="EXPORTAR", alvo="documentos.documento", alvo_id=documento.pk).count(), 2)

    def test_rascunho_baixa_com_nome_de_rascunho(self):
        with contexto.como(self.ana.pk):
            documento = servicos.salvar_rascunho("declaracao", {"atendido": "Marcos Tela"}, paciente=self.marcos)
        self.entrar(self.ana)
        resposta = self.client.get(self.baixar(documento))
        self.assertIn('filename="rascunho-declaracao-marcos-tela.pdf"', resposta["Content-Disposition"])

    def test_formato_desconhecido_e_documento_alheio_dao_404(self):
        with contexto.como(self.ana.pk):
            documento = servicos.salvar_rascunho("declaracao", {"atendido": "Marcos Tela"})
        self.entrar(self.ana)
        self.assertEqual(self.client.get(self.baixar(documento, "exe")).status_code, 404)
        self.assertEqual(self.client.get(self.baixar(self.do_bruno)).status_code, 404)

    def test_sem_login_nao_baixa(self):
        self.assertEqual(self.client.get(self.baixar(self.do_bruno)).status_code, 302)

    def test_salvar_e_baixar_grava_o_que_esta_na_folha_antes_de_gerar_o_arquivo(self):
        with contexto.como(self.ana.pk):
            documento = servicos.salvar_rascunho("declaracao", {"atendido": "Marcos Tela"}, paciente=self.marcos)
        self.entrar(self.ana)
        resposta = self.client.post(reverse("documentos:editar", args=[documento.pk]),
                                    {**DECLARACAO, "paciente": self.marcos.pk, "acao": "docx"})
        self.assertRedirects(resposta, self.baixar(documento, "docx"), fetch_redirect_response=False)
        documento.refresh_from_db()
        self.assertEqual(documento.dados["finalidade"], DECLARACAO["finalidade"])
        self.assertTrue(documento.rascunho)
