"""A folha do prontuário: as quatro partes da Res. CFP nº 001/2009 numa página só (ADR-079).

- `Sugestoes` — o que chega pré-preenchido é só administrativo; o que já foi salvo vence a sugestão.
- `Salvar` — só grava o que mudou; ficha só se acrescenta; evolução vira versão confirmada da sessão.
- `Arquivo` — a folha para PDF/DOCX leva só o que está confirmado.
- `ProtecaoEIsolamento` — prontuário escrito trava a exclusão do paciente; auditoria sem o texto; ADR-001.
- `FichaNoBanco` — gatilho e RLS.
- `TelaDaFolha` — a página, o salvar, o download e a trilha de exportação.
"""

import json
from datetime import date, time

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase
from django.urls import reverse

from agenda.models import Recorrencia
from atendimentos import servicos as agenda
from atendimentos.models import Desfecho
from core import contexto, db
from core.models import RegistroAuditoria
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente, excluir_paciente
from prontuarios import servicos
from prontuarios.models import FichaDoProntuario, VersaoCongelada, VersaoProntuario
from prontuarios.tests.test_servicos import REALIZADA, BaseProntuario, criar_psicologo, momento
from prontuarios.tests.test_telas import BaseTelasProntuario


class Sugestoes(BaseProntuario):
    def test_demanda_comeca_so_com_o_que_e_administrativo(self):
        with contexto.como(self.ana.pk):
            folha = servicos.folha_do_prontuario(self.marcos)
        self.assertTrue(folha.demanda_sugerida)
        self.assertIn("modalidade presencial", folha.demanda)
        self.assertIn("sem frequência fixa", folha.demanda)
        self.assertIn("iniciado em 3 de setembro de 2026", folha.demanda)  # a primeira sessão realizada
        self.assertIsNone(folha.ficha)

    def test_frequencia_cadastrada_entra_na_sugestao(self):
        with contexto.como(self.ana.pk):
            caso = self.marcos.participacoes.get().caso
            Recorrencia.objects.create(caso=caso, frequencia=Recorrencia.Frequencia.SEMANAL, dia_semana=1,
                                       hora=time(14), duracao=50, inicio=date(2026, 9, 1))
            texto = servicos.sugestao_de_demanda(self.marcos)
        self.assertIn("frequência semanal", texto)
        self.assertIn("14:00", texto)
        self.assertIn("sessões de 50 minutos", texto)

    def test_encerramento_so_e_sugerido_quando_ha_desfecho(self):
        with contexto.como(self.ana.pk):
            self.assertEqual(servicos.sugestao_de_encerramento(self.marcos), "")
            caso = self.marcos.participacoes.get().caso
            agenda.registrar_desfecho(caso, tipo=Desfecho.Tipo.ALTA, iniciativa=Desfecho.Iniciativa.PSICOLOGO,
                                      motivo="Objetivos alcançados.", data=date(2026, 9, 10))
            texto = servicos.sugestao_de_encerramento(self.marcos)
        self.assertIn("10 de setembro de 2026", texto)
        self.assertIn("alta", texto)
        self.assertIn("Objetivos alcançados.", texto)

    def test_o_que_foi_salvo_vence_a_sugestao(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_folha(self.marcos, demanda="Demanda escrita.", encerramento="", evolucoes={})
            folha = servicos.folha_do_prontuario(self.marcos)
        self.assertEqual(folha.demanda, "Demanda escrita.")
        self.assertFalse(folha.demanda_sugerida)

    def test_evolucao_vem_em_ordem_cronologica_e_so_de_sessao_realizada(self):
        with contexto.como(self.ana.pk):
            caso = self.marcos.participacoes.get().caso
            depois = agenda.cadastrar_avulsa(caso, estado=REALIZADA, inicio=momento(8))
            folha = servicos.folha_do_prontuario(self.marcos)
        self.assertEqual([r.consulta.pk for r in folha.evolucao], [self.sessao_marcos.pk, depois.pk])
        self.assertEqual(folha.sem_registro, 2)


class Salvar(BaseProntuario):
    def test_grava_ficha_e_confirma_a_evolucao(self):
        with contexto.como(self.ana.pk):
            mudancas = servicos.salvar_folha(self.marcos, demanda="Demanda.", encerramento="",
                                             evolucoes={self.sessao_marcos.pk: "Sessão de acolhimento."})
            registro = servicos.registro_de(self.sessao_marcos, self.marcos)
        self.assertEqual(mudancas, 2)
        self.assertEqual(registro.situacao, "confirmado")
        self.assertEqual(registro.vigente.texto, "Sessão de acolhimento.")

    def test_salvar_sem_mudar_nao_grava_nada(self):
        with contexto.como(self.ana.pk):
            dados = {"demanda": "Demanda.", "encerramento": "", "evolucoes": {self.sessao_marcos.pk: "Registro."}}
            servicos.salvar_folha(self.marcos, **dados)
            self.assertEqual(servicos.salvar_folha(self.marcos, **dados), 0)
            self.assertEqual(FichaDoProntuario.objects.count(), 1)
            self.assertEqual(VersaoProntuario.objects.count(), 1)

    def test_editar_guarda_a_redacao_anterior(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_folha(self.marcos, demanda="Primeira.", encerramento="",
                                  evolucoes={self.sessao_marcos.pk: "Texto um."})
            servicos.salvar_folha(self.marcos, demanda="Segunda.", encerramento="Alta em comum acordo.",
                                  evolucoes={self.sessao_marcos.pk: "Texto dois."})
            self.assertEqual([f.demanda for f in FichaDoProntuario.objects.all()], ["Segunda.", "Primeira."])
            self.assertEqual(servicos.ficha_de(self.marcos).encerramento, "Alta em comum acordo.")
            registro = servicos.registro_de(self.sessao_marcos, self.marcos)
        self.assertEqual([v.texto for v in registro.confirmadas], ["Texto um.", "Texto dois."])

    def test_texto_apagado_nao_apaga_registro_e_sessao_alheia_e_ignorada(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_folha(self.marcos, demanda="", encerramento="",
                                  evolucoes={self.sessao_marcos.pk: "Registro."})
            mudancas = servicos.salvar_folha(self.marcos, demanda="", encerramento="", evolucoes={
                self.sessao_marcos.pk: "  ", self.sessao_casal.pk: "Não é dele.", self.falta_marcos.pk: "Falta."})
            self.assertEqual(mudancas, 0)
            self.assertEqual(servicos.registro_de(self.sessao_marcos, self.marcos).vigente.texto, "Registro.")
            self.assertEqual(VersaoProntuario.objects.count(), 1)
            self.assertFalse(FichaDoProntuario.objects.exists())  # folha em branco não vira ficha

    def test_rascunho_da_tela_da_sessao_e_confirmado_pela_folha(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_rascunho(self.sessao_marcos, self.marcos, texto="Em rascunho.")
            servicos.salvar_folha(self.marcos, demanda="", encerramento="",
                                  evolucoes={self.sessao_marcos.pk: "Em rascunho."})
            self.assertEqual(servicos.registro_de(self.sessao_marcos, self.marcos).situacao, "confirmado")

    def test_ficha_nao_se_altera_nem_se_apaga(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_folha(self.marcos, demanda="Demanda.", encerramento="", evolucoes={})
            ficha = servicos.ficha_de(self.marcos)
            ficha.demanda = "Adulterada."
            with self.assertRaises(VersaoCongelada):
                ficha.save()
            with self.assertRaises(VersaoCongelada):
                ficha.delete()

    def test_participante_de_casal_tem_a_propria_folha(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_folha(self.maria, demanda="", encerramento="",
                                  evolucoes={self.sessao_casal.pk: "Registro da Maria."})
            self.assertEqual(servicos.registro_de(self.sessao_casal, self.maria).vigente.texto, "Registro da Maria.")
            self.assertTrue(servicos.registro_de(self.sessao_casal, self.joao).pendente)


class Arquivo(BaseProntuario):
    def test_leva_as_quatro_partes_e_so_o_que_esta_confirmado(self):
        with contexto.como(self.ana.pk):
            caso = self.marcos.participacoes.get().caso
            outra = agenda.cadastrar_avulsa(caso, estado=REALIZADA, inicio=momento(8))
            servicos.salvar_folha(self.marcos, demanda="Demanda escrita.", encerramento="",
                                  evolucoes={self.sessao_marcos.pk: "Sessão confirmada."})
            servicos.salvar_rascunho(outra, self.marcos, texto="Só rascunho.")
            folha = servicos.folha_para_arquivo(self.marcos, self.ana, hoje=date(2026, 9, 18))
        blocos = dict(folha["blocos"])
        self.assertEqual(list(blocos), ["Identificação", "Avaliação da demanda e objetivos do trabalho",
                                        "Evolução do trabalho e procedimentos adotados",
                                        "Encaminhamento ou encerramento"])
        self.assertIn("Nome completo: Marcos", blocos["Identificação"])
        self.assertIn("CRP 04/616161", blocos["Identificação"])
        self.assertEqual(blocos["Avaliação da demanda e objetivos do trabalho"], "Demanda escrita.")
        self.assertIn("03/09/2026, 10:00 — Sessão confirmada.", blocos["Evolução do trabalho e procedimentos adotados"])
        self.assertNotIn("Só rascunho.", json.dumps(folha, ensure_ascii=False))
        self.assertEqual(blocos["Encaminhamento ou encerramento"], "Sem registro até esta data.")
        self.assertIn("18 de setembro de 2026", folha["local_e_data"])

    def test_sugestao_nao_salva_nao_vai_para_o_arquivo(self):
        with contexto.como(self.ana.pk):
            folha = servicos.folha_para_arquivo(self.marcos, self.ana)
        self.assertEqual(dict(folha["blocos"])["Avaliação da demanda e objetivos do trabalho"],
                         "Sem registro até esta data.")


class ProtecaoEIsolamento(BaseProntuario):
    def test_paciente_com_prontuario_escrito_nao_e_apagado(self):
        with contexto.como(self.ana.pk):
            novo = Paciente(nome="Cadastro Recente")
            cadastrar_paciente(novo)
            servicos.salvar_folha(novo, demanda="Entrevista inicial.", encerramento="", evolucoes={})
            with self.assertRaises(ValidationError):
                excluir_paciente(novo)

    def test_auditoria_registra_sem_guardar_o_texto(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_folha(self.marcos, demanda="Conteúdo sigiloso da demanda.", encerramento="", evolucoes={})
        registros = RegistroAuditoria.objetos_todos.filter(titular="pacientes.paciente", titular_id=self.marcos.pk,
                                                           alvo="prontuarios.fichadoprontuario")
        self.assertTrue(registros.exists())
        self.assertNotIn("sigiloso", json.dumps([r.campos for r in registros]))

    def test_nao_ve_nem_escreve_a_ficha_de_outro_psicologo(self):
        with contexto.como(self.bruno.pk):
            servicos.salvar_folha(self.carla, demanda="Da Carla.", encerramento="", evolucoes={})
        with contexto.como(self.ana.pk):
            self.assertIsNone(servicos.ficha_de(self.carla))
            with self.assertRaises(ValidationError):
                servicos.salvar_folha(self.carla, demanda="Intrusão.", encerramento="", evolucoes={})


class FichaNoBanco(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Gatilho e RLS exigem PostgreSQL.")
        self.ana = criar_psicologo("ana.fichabanco@exemplo.com", "33333333333", "676767")
        self.bruno = criar_psicologo("bruno.fichabanco@exemplo.com", "44444444444", "686868")
        for psicologo, nome in [(self.ana, "Da Ana"), (self.bruno, "Do Bruno")]:
            with contexto.como(psicologo.pk):
                paciente = Paciente(nome=nome)
                cadastrar_paciente(paciente)
                servicos.salvar_folha(paciente, demanda="Demanda original.", encerramento="", evolucoes={})

    def test_gatilho_recusa_alterar_a_ficha_ate_para_o_dono_do_banco(self):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE prontuarios_fichadoprontuario SET demanda = 'adulterada'")
        self.assertFalse(FichaDoProntuario.objetos_todos.filter(demanda="adulterada").exists())

    def test_sql_cru_so_devolve_o_proprio_dono(self):
        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.ana.pk)
            with connection.cursor() as cursor:
                cursor.execute("SELECT DISTINCT psicologo_id FROM prontuarios_fichadoprontuario")
                donos = {linha[0] for linha in cursor.fetchall()}
        self.assertEqual(donos, {self.ana.pk})


class TelaDaFolha(BaseTelasProntuario):
    def folha(self, paciente=None):
        return reverse("prontuarios:paciente", args=[(paciente or self.marcos).pk])

    def baixar(self, formato="pdf", paciente=None):
        return reverse("prontuarios:baixar", args=[(paciente or self.marcos).pk, formato])

    def test_nao_abre_sem_login_nem_a_de_outro_psicologo(self):
        for rota in [self.folha(), self.baixar(), reverse("prontuarios:abrir")]:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 302)
        self.entrar(self.ana)
        for rota in [self.folha(self.carla), self.baixar("pdf", self.carla),
                     reverse("prontuarios:abrir") + f"?paciente={self.carla.pk}"]:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 404)

    def test_a_folha_traz_orientacao_identificacao_sugestao_e_uma_entrada_por_sessao(self):
        self.entrar(self.ana)
        resposta = self.client.get(self.folha())
        self.assertContains(resposta, "PRONTUÁRIO PSICOLÓGICO")
        self.assertContains(resposta, "Quatro partes, e nenhuma é opcional")
        self.assertContains(resposta, "Res. CFP nº 001/2009")
        self.assertContains(resposta, "Marcos Tela")
        self.assertContains(resposta, "sem frequência fixa")  # a sugestão administrativa
        self.assertContains(resposta, f'name="evolucao_{self.sessao.pk}"')
        self.assertNotContains(resposta, f'name="evolucao_{self.falta.pk}"')  # falta não tem evolução

    def test_abrir_a_folha_entra_na_trilha(self):
        self.entrar(self.ana)
        self.client.get(self.folha())
        self.assertTrue(RegistroAuditoria.objetos_todos.filter(
            acao="VER", titular="pacientes.paciente", titular_id=self.marcos.pk).exists())

    def test_salvar_pela_folha(self):
        self.entrar(self.ana)
        resposta = self.client.post(self.folha(), {
            "acao": "salvar", "demanda": "Demanda pela tela.", "encerramento": "",
            f"evolucao_{self.sessao.pk}": "Evolução pela tela."}, follow=True)
        self.assertContains(resposta, "Prontuário salvo.")
        self.assertContains(resposta, "Demanda pela tela.")
        with contexto.como(self.ana.pk):
            self.assertEqual(servicos.ficha_de(self.marcos).demanda, "Demanda pela tela.")
            self.assertEqual(servicos.registro_de(self.sessao, self.marcos).vigente.texto, "Evolução pela tela.")

    def test_salvar_e_baixar_leva_ao_arquivo(self):
        self.entrar(self.ana)
        resposta = self.client.post(self.folha(), {"acao": "docx", "demanda": "Demanda.", "encerramento": ""})
        self.assertRedirects(resposta, self.baixar("docx"), fetch_redirect_response=False)

    def test_baixar_em_pdf_e_docx_registra_a_exportacao(self):
        self.entrar(self.ana)
        pdf = self.client.get(self.baixar("pdf"))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertIn('filename="prontuario-marcos-tela.pdf"', pdf["Content-Disposition"])
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        docx = self.client.get(self.baixar("docx"))
        self.assertIn("wordprocessingml", docx["Content-Type"])
        self.assertTrue(docx.content.startswith(b"PK"))
        self.assertEqual(RegistroAuditoria.objetos_todos.filter(
            acao="EXPORTAR", titular="pacientes.paciente", titular_id=self.marcos.pk).count(), 2)

    def test_formato_desconhecido_da_404(self):
        self.entrar(self.ana)
        self.assertEqual(self.client.get(self.baixar("exe")).status_code, 404)

    def test_a_aba_oferece_a_folha_por_paciente(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("prontuarios:lista"))
        self.assertContains(resposta, "Prontuário por paciente")
        self.assertContains(resposta, "Marcos Tela")
        self.assertNotContains(resposta, "Carla Tela")
        resposta = self.client.get(reverse("prontuarios:abrir"), {"paciente": self.marcos.pk})
        self.assertRedirects(resposta, self.folha(), fetch_redirect_response=False)
