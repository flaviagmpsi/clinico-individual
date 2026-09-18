"""Documentos psicológicos por dentro (ADR-076): catálogo, sugestões, rascunho, emissão e as travas.

- `Catalogo` — as cinco modalidades da Res. 06/2019 e os três termos de apoio; o que a norma exige de cada uma.
- `Sugestoes` — o sistema propõe só identificação e assinatura; nada clínico chega ao documento.
- `CicloDeVida` — rascunho aceita campo em branco; emitir exige os obrigatórios e congela; copiar reabre.
- `Composicao` — dos campos ao texto impresso: texto corrido, itens, traços do atestado, data por extenso.
- `Gabarito` — ADR-077: todo campo tem lugar no texto; a folha de preencher e a impressa saem do mesmo gabarito.
- `Protecao` — paciente com documento emitido não é excluído; auditoria sem o conteúdo.
- `Isolamento` — ADR-001.
- `NoBanco` — o gatilho recusa alterar documento emitido, até para o dono do banco; RLS na tabela.
"""

import json
from datetime import date

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.db.utils import ProgrammingError
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from contas.models import Psicologo
from core import contexto, db
from core.models import RegistroAuditoria
from documentos import modelos, servicos
from documentos.models import Documento, DocumentoEmitido
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente, excluir_paciente

DECLARACAO_COMPLETA = {
    "finalidade": "apresentação à empresa Indústria de Alimentos S.A.", "atendido": "Marcos Vieira",
    "cpf": "529.982.247-25", "informacao": "compareceu a atendimento psicológico em 30 de maio de 2025, das 16h às 17h.",
    "local": "Belo Horizonte", "data": "2025-05-31", "psicologo_nome": "Ana Ribeiro", "psicologo_crp": "CRP 04/717171",
}


def criar_psicologo(email, cpf, crp, **extra):
    return Psicologo.objects.create_user(
        email=email, password="senha-de-teste-123", nome_completo="Ana Ribeiro", cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp, **extra)


class Catalogo(SimpleTestCase):
    def test_as_cinco_modalidades_e_os_tres_termos(self):
        self.assertEqual([m.codigo for m in modelos.CATALOGO if m.grupo == "documento"],
                         ["declaracao", "atestado", "relatorio", "laudo", "parecer"])
        self.assertEqual(len([m for m in modelos.CATALOGO if m.grupo == "apoio"]), 3)

    def test_todo_campo_explica_o_que_se_espera_dele(self):
        for modelo in modelos.CATALOGO:
            for campo in modelo.campos:
                with self.subTest(modelo=modelo.codigo, campo=campo.nome):
                    self.assertGreater(len(campo.ajuda), 15)
            self.assertTrue(modelo.orientacoes and modelo.prerequisito and modelo.norma)

    def test_a_estrutura_de_cada_modalidade_e_a_da_resolucao(self):
        """Res. 06/2019: relatório tem cinco itens; laudo, seis, com referências; parecer não tem procedimento."""
        titulos = {m.codigo: [s.titulo for s in m.secoes if s.titulo != "Encerramento"] for m in modelos.CATALOGO}
        self.assertEqual(titulos["relatorio"],
                         ["Identificação", "Descrição da demanda", "Procedimento", "Análise", "Conclusão"])
        self.assertEqual(titulos["laudo"], titulos["relatorio"] + ["Referências"])
        self.assertEqual(titulos["parecer"],
                         ["Identificação", "Descrição da demanda", "Análise", "Conclusão", "Referências"])

    def test_validade_so_em_atestado_relatorio_e_laudo(self):
        """Art. 17: o prazo de validade do conteúdo se aplica a esses três, e a nenhum outro."""
        com_validade = {m.codigo for m in modelos.CATALOGO if any(c.nome == "validade" for c in m.campos)}
        self.assertEqual(com_validade, {"atestado", "relatorio", "laudo"})

    def test_parecer_pede_titulacao_e_referencias(self):
        obrigatorios = {campo.nome for campo in modelos.PARECER.obrigatorios}
        self.assertTrue({"titulacao", "referencias"} <= obrigatorios)

    def test_nenhuma_sugestao_vem_de_dado_clinico(self):
        """ADR-034: a origem de um campo é identificação do paciente, o perfil ou a data de hoje — e só."""
        for modelo in modelos.CATALOGO:
            for campo in modelo.campos:
                if campo.origem:
                    with self.subTest(modelo=modelo.codigo, campo=campo.nome):
                        self.assertRegex(campo.origem, r"^(hoje|psicologo\.\w+|paciente\.(nome|cpf|data_nascimento|identificacao))$")


class BaseDocumentos(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.documentos@exemplo.com", "11111111111", "717171", cidade="Belo Horizonte")
        cls.bruno = criar_psicologo("bruno.documentos@exemplo.com", "22222222222", "727272")
        with contexto.como(cls.ana.pk):
            cls.marcos = Paciente(nome="Marcos Vieira", cpf="52998224725", data_nascimento=date(1988, 4, 12))
            cadastrar_paciente(cls.marcos)
        with contexto.como(cls.bruno.pk):
            cls.carla = Paciente(nome="Carla")
            cadastrar_paciente(cls.carla)


class Sugestoes(BaseDocumentos):
    def test_em_branco_so_vem_a_assinatura_e_a_data(self):
        sugerido = servicos.sugestoes(modelos.DECLARACAO, self.ana, hoje=date(2026, 9, 18))
        self.assertEqual(sugerido, {"local": "Belo Horizonte", "data": "2026-09-18",
                                    "psicologo_nome": "Ana Ribeiro", "psicologo_crp": "CRP 04/717171"})

    def test_escolher_o_paciente_traz_so_a_identificacao(self):
        sugerido = servicos.sugestoes(modelos.DECLARACAO, self.ana, self.marcos)
        self.assertEqual((sugerido["atendido"], sugerido["cpf"]), ("Marcos Vieira", "529.982.247-25"))
        self.assertNotIn("informacao", sugerido)   # o que se declara é sempre de quem assina
        self.assertNotIn("finalidade", sugerido)

    def test_relatorio_nao_recebe_nada_clinico(self):
        sugerido = servicos.sugestoes(modelos.RELATORIO, self.ana, self.marcos)
        for campo in ["demanda", "procedimento", "analise", "conclusao", "validade"]:
            self.assertNotIn(campo, sugerido)
        self.assertIn("12/04/1988", sugerido["outras_informacoes"])


class CicloDeVida(BaseDocumentos):
    def test_rascunho_aceita_pela_metade_e_se_regrava(self):
        with contexto.como(self.ana.pk):
            documento = servicos.salvar_rascunho("declaracao", {"atendido": "  Marcos  ", "cpf": ""},
                                                 paciente=self.marcos)
            servicos.salvar_rascunho("declaracao", {"atendido": "Marcos Vieira"}, paciente=self.marcos,
                                     documento=documento)
            self.assertEqual(Documento.objects.count(), 1)
        self.assertEqual((documento.dados, documento.rascunho), ({"atendido": "Marcos Vieira"}, True))

    def test_emitir_exige_os_campos_obrigatorios_e_diz_quais(self):
        with contexto.como(self.ana.pk):
            documento = servicos.salvar_rascunho("declaracao", {"atendido": "Marcos Vieira"})
            with self.assertRaises(ValidationError) as erro:
                servicos.emitir(documento)
        self.assertIn("Finalidade", erro.exception.messages[0])
        self.assertIn("O que se declara", erro.exception.messages[0])

    def test_emitido_nao_se_altera_nem_se_apaga(self):
        with contexto.como(self.ana.pk):
            documento = servicos.emitir(servicos.salvar_rascunho("declaracao", DECLARACAO_COMPLETA,
                                                                 paciente=self.marcos))
            with self.assertRaises(ValidationError):
                servicos.emitir(documento)
            with self.assertRaises(DocumentoEmitido):
                servicos.salvar_rascunho("declaracao", {"atendido": "Outro"}, documento=documento)
            with self.assertRaises(ValidationError):
                servicos.excluir_rascunho(documento)
            with self.assertRaises(DocumentoEmitido):
                documento.delete()

    def test_copiar_abre_rascunho_novo_e_o_original_fica(self):
        with contexto.como(self.ana.pk):
            original = servicos.emitir(servicos.salvar_rascunho("declaracao", DECLARACAO_COMPLETA,
                                                                paciente=self.marcos))
            copia = servicos.duplicar(original, hoje=date(2026, 9, 18))
        self.assertTrue(copia.rascunho)
        self.assertNotEqual(copia.pk, original.pk)
        self.assertEqual((copia.dados["informacao"], copia.dados["data"], copia.paciente),
                         (DECLARACAO_COMPLETA["informacao"], "2026-09-18", self.marcos))

    def test_modelo_desconhecido_e_campo_estranho_sao_recusados(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.salvar_rascunho("receita-medica", {})
            with self.assertRaises(ValidationError):
                Documento(modelo="declaracao", dados={"sintomas": "não é campo da declaração"}).save()


class Composicao(SimpleTestCase):
    def test_declaracao_em_texto_corrido_com_data_por_extenso(self):
        folha = modelos.compor(modelos.DECLARACAO, DECLARACAO_COMPLETA)
        [(titulo, texto)] = folha["blocos"]
        self.assertEqual(titulo, "")
        self.assertTrue(texto.startswith("Declara-se, para fins de apresentação à empresa"))
        self.assertIn("Marcos Vieira, CPF 529.982.247-25, compareceu", texto)
        self.assertEqual((folha["titulo"], folha["local_e_data"]), ("DECLARAÇÃO", "Belo Horizonte, 31 de maio de 2025"))

    def test_atestado_fecha_o_espaco_com_tracos(self):
        self.assertTrue(modelos.compor(modelos.ATESTADO, {})["tracos"])
        self.assertFalse(modelos.compor(modelos.DECLARACAO, {})["tracos"])

    def test_laudo_sai_em_itens_na_ordem_da_resolucao(self):
        dados = {"atendido": "Marcos", "solicitante": "o próprio", "finalidade": "orientação", "autor": "Ana",
                 "demanda": "D", "procedimento": "P", "analise": "A", "conclusao": "C", "validade": "V",
                 "referencias": "R"}
        folha = modelos.compor(modelos.LAUDO, dados)
        self.assertEqual([titulo for titulo, _ in folha["blocos"]],
                         ["Identificação", "Descrição da demanda", "Procedimento", "Análise", "Conclusão", "Referências"])
        self.assertEqual(dict(folha["blocos"])["Conclusão"], "C\n\nV")   # a validade fecha a conclusão (Art. 17)

    def test_termo_de_entrega_pede_a_assinatura_de_quem_recebe(self):
        self.assertTrue(modelos.compor(modelos.TERMO_DE_ENTREGA, {})["segunda_assinatura"])
        self.assertFalse(modelos.compor(modelos.RELATORIO, {})["segunda_assinatura"])


class Gabarito(SimpleTestCase):
    """ADR-077: preenche-se dentro do documento, e o que se preenche é o que se imprime."""

    FECHO = {"local", "data", "psicologo_nome", "psicologo_crp"}

    def corridos(self):
        return [modelo for modelo in modelos.CATALOGO if not modelo.itemizado]

    def test_todo_campo_tem_lugar_no_texto_e_nenhum_lugar_fica_sem_campo(self):
        for modelo in self.corridos():
            with self.subTest(modelo=modelo.codigo):
                campos = {campo.nome for campo in modelo.campos}
                lugares = {valor for tipo, valor in modelos.segmentos(modelo.gabarito) if tipo == "campo"}
                self.assertEqual(lugares, campos - self.FECHO)

    def test_a_folha_de_preencher_mostra_o_trecho_opcional_e_a_impressa_so_se_preenchido(self):
        pedacos = modelos.segmentos(modelos.DECLARACAO.gabarito)
        self.assertIn(("campo", "cpf"), pedacos)
        self.assertIn(("texto", ", CPF "), pedacos)

        sem_cpf = dict(DECLARACAO_COMPLETA, cpf="")
        self.assertNotIn("CPF", modelos.compor(modelos.DECLARACAO, sem_cpf)["blocos"][0][1])
        self.assertIn(", CPF 529.982.247-25,", modelos.compor(modelos.DECLARACAO, DECLARACAO_COMPLETA)["blocos"][0][1])

    def test_a_idade_no_atestado_entra_como_aposto_ou_nao_entra(self):
        dados = {"finalidade": "comprovação junto ao trabalho", "solicitante": "a própria pessoa atendida",
                 "atendido": "Maria Rosa", "condicoes": "encontra-se em acompanhamento.", "validade": "Válido por 30 dias."}
        self.assertIn("que Maria Rosa encontra-se", modelos.compor(modelos.ATESTADO, dados)["blocos"][0][1])
        self.assertIn("que Maria Rosa, 35 anos, encontra-se",
                      modelos.compor(modelos.ATESTADO, {**dados, "idade": "35 anos"})["blocos"][0][1])

    def test_data_dentro_do_texto_sai_por_extenso(self):
        dados = {"responsavel": "Luciana", "responsavel_nascimento": "1985-03-09", "atendido": "Rafael",
                 "atendido_nascimento": "2019-06-08"}
        texto = modelos.compor(modelos.AUTORIZACAO_MENOR, dados)["blocos"][0][1]
        self.assertIn("data de nascimento 9 de março de 1985", texto)
        self.assertIn("data de nascimento 8 de junho de 2019", texto)


class Protecao(BaseDocumentos):
    def test_paciente_com_documento_emitido_nao_e_excluido_e_rascunho_sai_junto(self):
        with contexto.como(self.ana.pk):
            outro = Paciente(nome="Só Rascunho")
            cadastrar_paciente(outro)
            servicos.salvar_rascunho("declaracao", {"atendido": "Só Rascunho"}, paciente=outro)
            excluir_paciente(outro)
            self.assertFalse(Documento.objects.filter(dados__atendido="Só Rascunho").exists())

            servicos.emitir(servicos.salvar_rascunho("declaracao", DECLARACAO_COMPLETA, paciente=self.marcos))
            with self.assertRaises(ValidationError):
                excluir_paciente(self.marcos)

    def test_auditoria_registra_sem_guardar_o_conteudo(self):
        with contexto.como(self.ana.pk):
            servicos.emitir(servicos.salvar_rascunho("declaracao", DECLARACAO_COMPLETA, paciente=self.marcos))
        registros = RegistroAuditoria.objetos_todos.filter(titular="pacientes.paciente", titular_id=self.marcos.pk,
                                                           alvo="documentos.documento")
        self.assertEqual([r.acao for r in registros.order_by("pk")],
                         [RegistroAuditoria.Acao.CRIAR, RegistroAuditoria.Acao.ALTERAR])
        self.assertNotIn("Indústria", json.dumps([r.campos for r in registros], ensure_ascii=False))


class Isolamento(BaseDocumentos):
    def test_nao_ve_documento_nem_usa_paciente_de_outro_psicologo(self):
        with contexto.como(self.bruno.pk):
            servicos.salvar_rascunho("declaracao", {"atendido": "Carla"}, paciente=self.carla)
        with contexto.como(self.ana.pk):
            self.assertFalse(servicos.documentos().exists())
            with self.assertRaises(ValidationError):
                servicos.salvar_rascunho("declaracao", {"atendido": "Carla"}, paciente=self.carla)


class NoBanco(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Gatilho e RLS exigem PostgreSQL.")
        self.ana = criar_psicologo("ana.docbanco@exemplo.com", "33333333333", "737373")
        self.bruno = criar_psicologo("bruno.docbanco@exemplo.com", "44444444444", "747474")
        for psicologo in [self.ana, self.bruno]:
            with contexto.como(psicologo.pk):
                servicos.emitir(servicos.salvar_rascunho("declaracao", DECLARACAO_COMPLETA))

    def test_gatilho_recusa_alterar_documento_emitido_ate_para_o_dono_do_banco(self):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE documentos_documento SET dados = '{}'::jsonb")
        self.assertFalse(Documento.objetos_todos.filter(dados={}).exists())

    def test_sql_cru_so_devolve_o_proprio_dono(self):
        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.ana.pk)
            with connection.cursor() as cursor:
                cursor.execute("SELECT DISTINCT psicologo_id FROM documentos_documento")
                donos = {linha[0] for linha in cursor.fetchall()}
        self.assertEqual(donos, {self.ana.pk})

    def test_papel_anonimo_nao_le_documento(self):
        with self.assertRaises(ProgrammingError):
            with transaction.atomic():
                db.assumir_papel_da_web()
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM documentos_documento")
