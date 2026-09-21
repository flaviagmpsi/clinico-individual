"""O horário de atendimento dentro do cadastro do paciente (ADR-095).

- `VagasDaSemana` — os horários livres saem da grade declarada, menos o que já tem paciente fixo.
- `HorarioNoCadastro` — a tela mostra os livres, grava a frequência junto com o paciente, aceita "outro horário",
  recusa horário ocupado sem gravar nada, e o paciente aparece na agenda.
"""

from datetime import time, timedelta

from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from agenda.grade import vagas_da_semana
from agenda.models import HorarioDisponivel, Recorrencia
from atendimentos import servicos
from contas.models import Psicologo
from core import contexto
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente

SENHA = "senha-de-teste-123"
TERCA, QUARTA = 1, 2
SEMANAL = Recorrencia.Frequencia.SEMANAL


class Base(TransactionTestCase):
    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.horario@exemplo.com", password=SENHA, nome_completo="Ana Ribeiro", cpf="11111111111",
            telefone="31988887777", crp_regiao="04", crp_numero="818181")
        self.bruno = Psicologo.objects.create_user(
            email="bruno.horario@exemplo.com", password=SENHA, nome_completo="Bruno Carvalho", cpf="22222222222",
            telefone="31988887777", crp_regiao="04", crp_numero="828282")
        self.hoje = timezone.localdate()
        with contexto.como(self.ana.pk):
            # Terça das 14h às 17h: cabem 14h, 15h e 16h. A Maria já ocupa a das 15h.
            HorarioDisponivel.objects.create(dia_semana=TERCA, inicio=time(14), fim=time(17))
            self.caso_maria = cadastrar_paciente(Paciente(nome="Maria Fixa"))
            servicos.definir_frequencia(self.caso_maria, frequencia=SEMANAL, dia_semana=TERCA, hora=time(15))
        with contexto.como(self.bruno.pk):
            HorarioDisponivel.objects.create(dia_semana=QUARTA, inicio=time(9), fim=time(10))


class VagasDaSemana(Base):
    def test_a_grade_menos_o_que_ja_tem_paciente(self):
        with contexto.como(self.ana.pk):
            dias = vagas_da_semana(50)
        self.assertEqual([(d.nome, [v.codigo for v in d.vagas]) for d in dias],
                         [("Terça-feira", ["1-14:00", "1-16:00"])])

    def test_sessao_que_nao_cabe_no_fim_do_bloco_nao_e_oferecida(self):
        with contexto.como(self.ana.pk):
            dias = vagas_da_semana(90)  # 14h–15h30 esbarra na Maria; 16h–17h30 passa do bloco
        self.assertEqual(dias, [])

    def test_regra_encerrada_devolve_o_horario(self):
        with contexto.como(self.ana.pk):
            servicos.definir_frequencia(self.caso_maria, frequencia=servicos.AVULSO)
            dias = vagas_da_semana(50)
        self.assertEqual([v.codigo for v in dias[0].vagas], ["1-14:00", "1-15:00", "1-16:00"])

    def test_sem_grade_nao_ha_vaga(self):
        with contexto.como(self.bruno.pk):
            HorarioDisponivel.objects.all().delete()
            self.assertEqual(vagas_da_semana(50), [])


class HorarioNoCadastro(Base):
    def setUp(self):
        super().setUp()
        self.assertTrue(self.client.login(username=self.ana.email, password=SENHA))

    def cadastrar(self, nome="Paula Nova", **horario):
        dados = {"nome": nome, "uf": ""}
        dados.update({f"horario-{campo}": valor for campo, valor in horario.items()})
        return self.client.post(reverse("pacientes:novo"), dados)

    def regra_de(self, nome):
        with contexto.como(self.ana.pk):
            return Recorrencia.objects.filter(caso__pacientes__nome=nome).first()

    def test_a_tela_mostra_os_meus_horarios_livres_e_so_os_meus(self):
        resposta = self.client.get(reverse("pacientes:novo"))
        self.assertContains(resposta, "Horário de atendimento")
        self.assertContains(resposta, 'value="1-14:00"')
        self.assertContains(resposta, 'value="1-16:00"')
        self.assertNotContains(resposta, 'value="1-15:00"')  # é da Maria
        self.assertNotContains(resposta, 'value="2-09:00"')  # é do Bruno
        self.assertContains(resposta, "Outro horário")

    def test_a_edicao_do_paciente_nao_tem_o_bloco(self):
        with contexto.como(self.ana.pk):
            maria = Paciente.objects.get(nome="Maria Fixa")
        self.assertNotContains(self.client.get(reverse("pacientes:editar", args=[maria.pk])), "Horário de atendimento")

    def test_escolher_um_horario_livre_grava_a_frequencia_com_o_paciente(self):
        resposta = self.cadastrar(frequencia="SEMANAL", vaga="1-14:00")
        self.assertEqual(resposta.status_code, 302)
        regra = self.regra_de("Paula Nova")
        self.assertEqual((regra.frequencia, regra.dia_semana, regra.hora, regra.duracao, regra.inicio),
                         ("SEMANAL", TERCA, time(14), 50, self.hoje))
        # O horário deixou de ser livre, e o paciente está na agenda.
        self.assertNotContains(self.client.get(reverse("pacientes:novo")), 'value="1-14:00"')
        proxima_terca = self.hoje + timedelta(days=(TERCA - self.hoje.weekday()) % 7)
        with contexto.como(self.ana.pk):
            previstas = servicos.sessoes_previstas(proxima_terca, proxima_terca)
        self.assertIn("Paula Nova", [str(s.caso) for s in previstas])

    def test_a_regra_vale_da_primeira_sessao_quando_ela_e_futura(self):
        primeira = self.hoje + timedelta(days=20)
        self.client.post(reverse("pacientes:novo"), {
            "nome": "Paula Futura", "uf": "", "data_primeira_sessao": primeira.isoformat(),
            "horario-frequencia": "QUINZENAL", "horario-vaga": "1-16:00"})
        regra = self.regra_de("Paula Futura")
        self.assertEqual((regra.frequencia, regra.inicio), ("QUINZENAL", primeira))

    def test_outro_horario_fora_dos_livres(self):
        resposta = self.cadastrar(frequencia="SEMANAL", vaga="OUTRO", dia_semana="4", hora="08:30")
        self.assertEqual(resposta.status_code, 302)
        regra = self.regra_de("Paula Nova")
        self.assertEqual((regra.dia_semana, regra.hora), (4, time(8, 30)))

    def test_outro_horario_pede_dia_e_hora(self):
        resposta = self.cadastrar(frequencia="SEMANAL", vaga="OUTRO")
        self.assertContains(resposta, "Informe o dia da semana")
        self.assertContains(resposta, "Informe o horário")
        self.assertFalse(Paciente.objetos_todos.filter(nome="Paula Nova").exists())

    def test_frequencia_sem_horario_nao_cadastra(self):
        resposta = self.cadastrar(frequencia="SEMANAL")
        self.assertContains(resposta, "Escolha um dos seus horários livres")
        self.assertFalse(Paciente.objetos_todos.filter(nome="Paula Nova").exists())

    def test_nao_responder_o_bloco_nao_cadastra(self):
        resposta = self.cadastrar()
        self.assertContains(resposta, "Escolha a frequência")
        self.assertFalse(Paciente.objetos_todos.filter(nome="Paula Nova").exists())

    def test_sem_horario_fixo_cadastra_sem_regra(self):
        self.assertEqual(self.cadastrar(frequencia="AVULSO").status_code, 302)
        self.assertTrue(Paciente.objetos_todos.filter(nome="Paula Nova").exists())
        self.assertIsNone(self.regra_de("Paula Nova"))

    def test_horario_ocupado_e_recusado_e_nem_o_paciente_e_gravado(self):
        resposta = self.cadastrar(frequencia="SEMANAL", vaga="OUTRO", dia_semana=str(TERCA), hora="15:20")
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Horário ocupado")
        self.assertContains(resposta, "Maria Fixa")
        self.assertFalse(Paciente.objetos_todos.filter(nome="Paula Nova").exists())
        self.assertContains(resposta, 'value="Paula Nova"')  # o que foi digitado não se perde

    def test_vaga_inventada_no_post_e_recusada(self):
        resposta = self.cadastrar(frequencia="SEMANAL", vaga="1-15:00")  # a da Maria, que a tela não oferece
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(Paciente.objetos_todos.filter(nome="Paula Nova").exists())
