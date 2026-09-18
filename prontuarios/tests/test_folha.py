"""O prontuário geral por dentro: as quatro partes da Res. CFP nº 001/2009 (ADR-079, ADR-080).

- `Sugestoes` — o que chega pré-preenchido é só administrativo; o que já foi salvo vence a sugestão.
- `Salvar` — só grava o que mudou; a ficha só se acrescenta; a evolução **não** se escreve por aqui.
- `Arquivo` — a folha para PDF/DOCX reúne todos os registros de sessão confirmados, e só eles.
- `ProtecaoEIsolamento` — prontuário escrito trava a exclusão do paciente; auditoria sem o texto; ADR-001.
- `FichaNoBanco` — gatilho e RLS.

As telas ficam em `documentos/tests/test_prontuario_geral.py`: o prontuário geral mora na aba Documentos.
"""

import json
from datetime import date, time

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase

from agenda.models import Recorrencia
from atendimentos import servicos as agenda
from atendimentos.models import Desfecho
from core import contexto, db
from core.models import RegistroAuditoria
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente, excluir_paciente
from prontuarios import servicos
from prontuarios.models import FichaDoProntuario, VersaoCongelada
from prontuarios.tests.test_servicos import REALIZADA, BaseProntuario, criar_psicologo, momento


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
            servicos.salvar_folha(self.marcos, demanda="Demanda escrita.", encerramento="")
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
    def test_grava_a_ficha_e_nao_toca_nos_registros_de_sessao(self):
        with contexto.como(self.ana.pk):
            self.assertTrue(servicos.salvar_folha(self.marcos, demanda="Demanda.", encerramento=""))
            self.assertEqual(servicos.ficha_de(self.marcos).demanda, "Demanda.")
            self.assertTrue(servicos.registro_de(self.sessao_marcos, self.marcos).pendente)

    def test_salvar_sem_mudar_nao_grava_nada(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_folha(self.marcos, demanda="Demanda.", encerramento="")
            self.assertFalse(servicos.salvar_folha(self.marcos, demanda=" Demanda. ", encerramento=""))
            self.assertEqual(FichaDoProntuario.objects.count(), 1)

    def test_folha_em_branco_nao_vira_ficha(self):
        with contexto.como(self.ana.pk):
            self.assertFalse(servicos.salvar_folha(self.marcos, demanda="  ", encerramento=""))
            self.assertFalse(FichaDoProntuario.objects.exists())

    def test_editar_guarda_a_redacao_anterior(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_folha(self.marcos, demanda="Primeira.", encerramento="")
            servicos.salvar_folha(self.marcos, demanda="Segunda.", encerramento="Alta em comum acordo.")
            self.assertEqual([f.demanda for f in FichaDoProntuario.objects.all()], ["Segunda.", "Primeira."])
            self.assertEqual(servicos.ficha_de(self.marcos).encerramento, "Alta em comum acordo.")

    def test_ficha_nao_se_altera_nem_se_apaga(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_folha(self.marcos, demanda="Demanda.", encerramento="")
            ficha = servicos.ficha_de(self.marcos)
            ficha.demanda = "Adulterada."
            with self.assertRaises(VersaoCongelada):
                ficha.save()
            with self.assertRaises(VersaoCongelada):
                ficha.delete()


class Arquivo(BaseProntuario):
    def test_reune_todos_os_registros_confirmados_em_ordem_e_so_eles(self):
        with contexto.como(self.ana.pk):
            caso = self.marcos.participacoes.get().caso
            segunda = agenda.cadastrar_avulsa(caso, estado=REALIZADA, inicio=momento(8))
            terceira = agenda.cadastrar_avulsa(caso, estado=REALIZADA, inicio=momento(15))
            servicos.salvar_folha(self.marcos, demanda="Demanda escrita.", encerramento="")
            servicos.confirmar(segunda, self.marcos, texto="Segunda sessão.")
            servicos.confirmar(self.sessao_marcos, self.marcos, texto="Primeira sessão.")
            servicos.salvar_rascunho(terceira, self.marcos, texto="Só rascunho.")
            folha = servicos.folha_para_arquivo(self.marcos, self.ana, hoje=date(2026, 9, 18))
        blocos = dict(folha["blocos"])
        self.assertEqual(list(blocos), ["Identificação", "Avaliação da demanda e objetivos do trabalho",
                                        "Evolução do trabalho e procedimentos adotados",
                                        "Encaminhamento ou encerramento"])
        self.assertIn("Nome completo: Marcos", blocos["Identificação"])
        self.assertIn("CRP 04/616161", blocos["Identificação"])
        self.assertEqual(blocos["Avaliação da demanda e objetivos do trabalho"], "Demanda escrita.")
        self.assertEqual(blocos["Evolução do trabalho e procedimentos adotados"],
                         "03/09/2026, 10:00 — Primeira sessão.\n\n08/09/2026, 10:00 — Segunda sessão.")
        self.assertNotIn("Só rascunho.", json.dumps(folha, ensure_ascii=False))
        self.assertEqual(blocos["Encaminhamento ou encerramento"], "Sem registro até esta data.")
        self.assertIn("18 de setembro de 2026", folha["local_e_data"])

    def test_registro_editado_entra_com_a_redacao_que_vale(self):
        with contexto.como(self.ana.pk):
            servicos.confirmar(self.sessao_marcos, self.marcos, texto="Redação antiga.")
            servicos.confirmar(self.sessao_marcos, self.marcos, texto="Redação nova.")
            evolucao = dict(servicos.folha_para_arquivo(self.marcos, self.ana)["blocos"])[
                "Evolução do trabalho e procedimentos adotados"]
        self.assertIn("Redação nova.", evolucao)
        self.assertNotIn("Redação antiga.", evolucao)

    def test_participante_de_casal_leva_so_o_proprio_registro(self):
        with contexto.como(self.ana.pk):
            servicos.confirmar(self.sessao_casal, self.maria, texto="Registro da Maria.")
            servicos.confirmar(self.sessao_casal, self.joao, texto="Registro do João.")
            texto = json.dumps(servicos.folha_para_arquivo(self.maria, self.ana), ensure_ascii=False)
        self.assertIn("Registro da Maria.", texto)
        self.assertNotIn("Registro do João.", texto)

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
            servicos.salvar_folha(novo, demanda="Entrevista inicial.", encerramento="")
            with self.assertRaises(ValidationError):
                excluir_paciente(novo)

    def test_auditoria_registra_sem_guardar_o_texto(self):
        with contexto.como(self.ana.pk):
            servicos.salvar_folha(self.marcos, demanda="Conteúdo sigiloso da demanda.", encerramento="")
        registros = RegistroAuditoria.objetos_todos.filter(titular="pacientes.paciente", titular_id=self.marcos.pk,
                                                           alvo="prontuarios.fichadoprontuario")
        self.assertTrue(registros.exists())
        self.assertNotIn("sigiloso", json.dumps([r.campos for r in registros]))

    def test_nao_ve_nem_escreve_a_ficha_de_outro_psicologo(self):
        with contexto.como(self.bruno.pk):
            servicos.salvar_folha(self.carla, demanda="Da Carla.", encerramento="")
        with contexto.como(self.ana.pk):
            self.assertIsNone(servicos.ficha_de(self.carla))
            with self.assertRaises(ValidationError):
                servicos.salvar_folha(self.carla, demanda="Intrusão.", encerramento="")


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
                servicos.salvar_folha(paciente, demanda="Demanda original.", encerramento="")

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
