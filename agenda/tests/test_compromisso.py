"""Compromisso fora da clínica (ADR-122): ocupa a agenda e não encosta em nada clínico.

Decisão do usuário: *"é puramente visual pra minha agenda ficar mais fiel à quantidade de coisas que eu faço no
meu trabalho"* — supervisão, paciente de ONG, aula, reunião.

O par que prova a feature está em `NaoContaminaOClinico`: um teste que só verificasse que o compromisso aparece
passaria mesmo se ele estivesse gerando cobrança e prontuário por baixo, que é justamente o que ele não pode fazer.

Datas fixas e conferidas: **14/09/2026 é segunda-feira**, 15/09 é terça e 17/09 é quinta.
"""

from datetime import date, time, timedelta

from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from agenda import compromissos
from agenda.models import Compromisso, HorarioDisponivel
from agenda.grade import mapa_da_semana, vagas_da_semana
from atendimentos import servicos as agenda
from contas.models import Psicologo
from core import contexto

SENHA = "senha-de-teste-123"
TERCA, QUINTA = 1, 3
SEGUNDA_14 = date(2026, 9, 14)


def compromisso(frequencia="SEMANAL", dia=TERCA, inicio=SEGUNDA_14, fim=None):
    return Compromisso(titulo="Supervisão do Arthur", frequencia=frequencia, dia_semana=dia,
                       hora=time(10), duracao=90, inicio=inicio, fim=fim)


class Datas(SimpleTestCase):
    """A conta de quando ele acontece — sem banco, porque é aritmética de calendário."""

    def test_semanal_toda_semana(self):
        self.assertEqual(compromisso().ocorrencias(SEGUNDA_14, date(2026, 10, 6)),
                         [date(2026, 9, 15), date(2026, 9, 22), date(2026, 9, 29), date(2026, 10, 6)])

    def test_quinzenal_pula_uma(self):
        self.assertEqual(compromisso("QUINZENAL").ocorrencias(SEGUNDA_14, date(2026, 10, 6)),
                         [date(2026, 9, 15), date(2026, 9, 29)])

    def test_unico_acontece_uma_vez_e_ignora_o_dia_da_semana(self):
        unico = Compromisso(titulo="Reunião", frequencia="UNICO", dia_semana=None, hora=time(15),
                            duracao=60, inicio=date(2026, 9, 17))
        self.assertEqual(unico.ocorrencias(SEGUNDA_14, date(2026, 12, 31)), [date(2026, 9, 17)])
        self.assertEqual(unico.ocorrencias(date(2026, 9, 18), date(2026, 12, 31)), [])

    def test_depois_do_fim_nao_acontece(self):
        """O fim é exclusivo, como na recorrência: no dia em que termina, já não vale."""
        ate_o_fim_do_mes = compromisso(fim=date(2026, 9, 29))
        self.assertEqual(ate_o_fim_do_mes.ocorrencias(SEGUNDA_14, date(2026, 10, 6)),
                         [date(2026, 9, 15), date(2026, 9, 22)])


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = Psicologo.objects.create_user(email="ana.comp@exemplo.com", password=SENHA,
                                                nome_completo="Ana", crp_regiao="04", crp_numero="717272")
        cls.hoje = timezone.localdate()
        with contexto.como(cls.ana.pk):
            # Terça das 9h às 13h: cabem 9h, 10h, 11h e 12h para sessões de 50 minutos.
            HorarioDisponivel.objects.create(dia_semana=TERCA, inicio=time(9), fim=time(13))
            cls.supervisao = Compromisso.objects.create(
                titulo="Supervisão do Arthur", frequencia="SEMANAL", dia_semana=TERCA,
                hora=time(10), duracao=90, inicio=cls.hoje)


class OcupaOHorario(Base):
    def test_some_das_vagas_oferecidas_no_cadastro_de_paciente(self):
        """A decisão do usuário: o sistema não pode propor marcar alguém por cima da supervisão."""
        with contexto.como(self.ana.pk):
            codigos = [v.codigo for d in vagas_da_semana(50) for v in d.vagas]
        self.assertEqual(codigos, ["1-09:00", "1-12:00"])  # 10h e 11h ficaram sob a supervisão

    def test_entra_na_ocupacao_da_semana(self):
        with contexto.como(self.ana.pk):
            mapa = mapa_da_semana()
        self.assertEqual(mapa.minutos_ocupados, 90)
        self.assertEqual(mapa.horas_ocupadas, "1h30")

    def test_o_de_uma_vez_so_nao_toma_a_semana_inteira(self):
        """Uma reunião num dia não pode bloquear aquele horário para sempre."""
        with contexto.como(self.ana.pk):
            Compromisso.objects.create(titulo="Reunião", frequencia="UNICO", dia_semana=None,
                                       hora=time(9), duracao=50, inicio=self.hoje)
            self.assertEqual([c.titulo for c in compromissos.que_ocupam_a_grade()], ["Supervisão do Arthur"])
            self.assertIn("1-09:00", [v.codigo for d in vagas_da_semana(50) for v in d.vagas])


class ApareceNaAgenda(Base):
    def proxima_terca(self):
        return self.hoje + timedelta(days=(TERCA - self.hoje.weekday()) % 7)

    def test_vira_cartao_no_calendario(self):
        with contexto.como(self.ana.pk):
            dias = agenda.calendario(self.hoje, self.hoje + timedelta(days=13), duracao=50)
        tipos = [tipo for dia in dias for tipo, _, _ in dia.cartoes]
        self.assertIn("compromisso", tipos)
        titulos = {item.titulo for dia in dias for item in dia.compromissos}
        self.assertEqual(titulos, {"Supervisão do Arthur"})

    def test_o_filtro_de_situacao_nao_o_devolve(self):
        """Ele não tem situação: procurar faltas e receber supervisão seria ruído."""
        with contexto.como(self.ana.pk):
            dias = agenda.calendario(self.hoje, self.hoje + timedelta(days=13),
                                     situacao="REALIZADA", duracao=50)
        self.assertEqual([item for dia in dias for item in dia.compromissos], [])


class NaoContaminaOClinico(Base):
    """A outra metade da prova: ele aparece **e** não mexe em nada do que é atendimento."""

    def test_nao_conta_como_sessao(self):
        with contexto.como(self.ana.pk):
            dias = agenda.calendario(self.hoje, self.hoje + timedelta(days=13), duracao=50)
        self.assertEqual([item for dia in dias for item in dia.sessoes], [])

    def test_nao_gera_cobranca(self):
        from financeiro import servicos as financeiro
        with contexto.como(self.ana.pk):
            self.assertEqual(financeiro.cobrancas_em_aberto(self.hoje), [])

    def test_nao_gera_prontuario_nem_sessao_a_cadastrar(self):
        from prontuarios import servicos as prontuarios
        with contexto.como(self.ana.pk):
            self.assertEqual(prontuarios.registros(somente_pendentes=True), [])
            self.assertEqual(agenda.sessoes_previstas(self.hoje, self.hoje + timedelta(days=30)), [])


class ContaNasHoras(Base):
    def test_entra_nas_horas_de_trabalho_separado_do_que_e_sessao(self):
        from indicadores import estatisticas
        from indicadores.periodo import Periodo
        with contexto.como(self.ana.pk):
            retrato = estatisticas.retrato_da_agenda(Periodo(self.hoje.year, self.hoje.month))
        self.assertEqual(retrato.minutos_de_sessao, 0)
        self.assertTrue(retrato.minutos_fora_da_clinica >= 90)
        self.assertTrue(retrato.tem_trabalho_fora)
        self.assertEqual(retrato.minutos_trabalhados, retrato.minutos_fora_da_clinica)


class Isolamento(Base):
    """ADR-001: o compromisso diz quando o psicólogo trabalha e com quem. Não sai do dono."""

    def test_o_de_outro_psicologo_nao_aparece_na_consulta(self):
        bruno = Psicologo.objects.create_user(email="bruno.comp@exemplo.com", password=SENHA,
                                              nome_completo="Bruno", crp_regiao="04", crp_numero="727373")
        with contexto.como(bruno.pk):
            Compromisso.objects.create(titulo="Alheio", frequencia="SEMANAL", dia_semana=QUINTA,
                                       hora=time(8), duracao=50, inicio=self.hoje)
        with contexto.como(self.ana.pk):
            self.assertNotIn("Alheio", [c.titulo for c in Compromisso.objects.all()])


class Telas(TransactionTestCase):
    """As telas de editar e excluir.

    `TransactionTestCase` e não `TestCase`: o login grava sessão, e o `SET LOCAL ROLE` do middleware vaza dentro
    da transação única do `TestCase` — o banco responde "permission denied for table django_session". Armadilha
    conhecida deste projeto, e o motivo de todo teste de tela aqui herdar desta classe.
    """

    def setUp(self):
        self.ana = Psicologo.objects.create_user(email="ana.telacomp@exemplo.com", password=SENHA,
                                                 nome_completo="Ana", crp_regiao="04", crp_numero="737474")
        self.bruno = Psicologo.objects.create_user(email="bruno.telacomp@exemplo.com", password=SENHA,
                                                   nome_completo="Bruno", crp_regiao="04", crp_numero="747575")
        self.hoje = timezone.localdate()
        with contexto.como(self.ana.pk):
            self.meu = Compromisso.objects.create(titulo="Supervisão", frequencia="SEMANAL", dia_semana=TERCA,
                                                  hora=time(10), duracao=90, inicio=self.hoje)
        with contexto.como(self.bruno.pk):
            self.alheio = Compromisso.objects.create(titulo="Alheio", frequencia="SEMANAL", dia_semana=QUINTA,
                                                     hora=time(8), duracao=50, inicio=self.hoje)
        self.assertTrue(self.client.login(username=self.ana.email, password=SENHA))

    def test_editar_muda_e_nao_duplica(self):
        resposta = self.client.post(reverse("agenda:compromisso_editar", args=[self.meu.pk]), {
            "titulo": "Supervisão nova", "frequencia": "QUINZENAL", "dia_semana": str(QUINTA),
            "inicio": self.hoje.strftime("%Y-%m-%d"), "hora": "14:00", "duracao": "60", "fim": ""})
        self.assertEqual(resposta.status_code, 302)
        with contexto.como(self.ana.pk):
            self.meu.refresh_from_db()
            self.assertEqual((self.meu.titulo, self.meu.dia_semana, self.meu.duracao),
                             ("Supervisão nova", QUINTA, 60))
            self.assertEqual(Compromisso.objects.count(), 1)

    def test_o_de_outro_psicologo_nao_se_edita_nem_se_exclui(self):
        self.assertEqual(
            self.client.get(reverse("agenda:compromisso_editar", args=[self.alheio.pk])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("agenda:compromisso_excluir", args=[self.alheio.pk])).status_code, 404)
        with contexto.como(self.bruno.pk):
            self.assertTrue(Compromisso.objects.filter(pk=self.alheio.pk).exists())

    def test_repetido_sem_dia_da_semana_e_recusado(self):
        """Sem isto o compromisso ficaria invisível para sempre, sem erro em lugar nenhum."""
        resposta = self.client.post(reverse("agenda:compromisso_novo"), {
            "titulo": "Sem dia", "frequencia": "SEMANAL", "dia_semana": "",
            "inicio": self.hoje.strftime("%Y-%m-%d"), "hora": "10:00", "duracao": "50", "fim": ""})
        self.assertContains(resposta, "Diga em que dia da semana ele acontece.")
        with contexto.como(self.ana.pk):
            self.assertFalse(Compromisso.objects.filter(titulo="Sem dia").exists())
