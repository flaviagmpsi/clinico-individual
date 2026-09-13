"""A agenda por dentro: previsão, troca de frequência, colisão, registro e pendência.

Cada classe guarda uma ADR:

- `Previsao` — ADR-022 e 053: semanal e quinzenal geram a janela; avulso não gera nada.
- `TrocaDeFrequencia` — ADR-022: "esta e as próximas"; remarcadas e passado ficam.
- `Colisao` — ADR-024, inclusive contra sessões que a regra **ainda não gerou**.
- `Registro` — ADR-023 e 025: comparecimento e cobrança independentes, falta segue o perfil.
- `Pendencia` — ADR-052: o sistema nunca registra sozinho.
- `Isolamento` — ADR-001: a agenda de um psicólogo não bloqueia nem enxerga a de outro.
- `ExclusaoDePaciente` — ADR-048: agendada sai junto; atendimento registrado impede.

As datas partem de "hoje" porque a janela de previsão parte de hoje; `proxima_terca` garante que a série
começa no futuro, seja qual for o dia em que o teste roda.
"""

from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from agenda.models import Recorrencia
from atendimentos import servicos
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente, criar_caso_coletivo, excluir_paciente

SEMANAL = Recorrencia.Frequencia.SEMANAL
QUINZENAL = Recorrencia.Frequencia.QUINZENAL
TERCA = Recorrencia.DiaSemana.TERCA
QUARTA = Recorrencia.DiaSemana.QUARTA


def momento(dia, hora, minuto=0):
    return timezone.make_aware(datetime.combine(dia, time(hora, minuto)))


def proxima(dia_semana):
    amanha = timezone.localdate() + timedelta(days=1)
    return amanha + timedelta(days=(dia_semana - amanha.weekday()) % 7)


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password="senha-de-teste-123", nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


class BaseAgenda(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.agenda@exemplo.com", "11111111111", "919191")
        cls.bruno = criar_psicologo("bruno.agenda@exemplo.com", "22222222222", "929292")
        with contexto.como(cls.ana.pk):
            cls.maria = Paciente(nome="Maria")
            cls.caso_maria = cadastrar_paciente(cls.maria)
            cls.joao = Paciente(nome="João")
            cls.caso_joao = cadastrar_paciente(cls.joao)
        with contexto.como(cls.bruno.pk):
            cls.carla = Paciente(nome="Carla")
            cls.caso_carla = cadastrar_paciente(cls.carla)

    def setUp(self):
        self.terca = proxima(TERCA)
        self.hoje = timezone.localdate()

    def semanal_da_maria(self, hora=14, frequencia=SEMANAL, inicio=None):
        return servicos.definir_frequencia(
            self.caso_maria, frequencia=frequencia, dia_semana=TERCA, hora=time(hora), a_partir_de=inicio or self.terca)


class Previsao(BaseAgenda):
    def test_semanal_preve_toda_a_janela_com_a_duracao_do_perfil(self):
        with contexto.como(self.ana.pk):
            regra = self.semanal_da_maria()
            esperadas = regra.ocorrencias(self.terca, self.hoje + timedelta(weeks=servicos.JANELA_SEMANAS))
            consultas = Consulta.objects.filter(recorrencia=regra)
            self.assertEqual(sorted(c.data_prevista for c in consultas), esperadas)
            self.assertTrue(all(c.estado == Consulta.Estado.AGENDADA and c.duracao == 50 for c in consultas))

    def test_quinzenal_e_semana_sim_semana_nao(self):
        with contexto.como(self.ana.pk):
            regra = self.semanal_da_maria(frequencia=QUINZENAL)
            datas = sorted(Consulta.objects.filter(recorrencia=regra).values_list("data_prevista", flat=True))
        self.assertTrue(all((b - a).days == 14 for a, b in zip(datas, datas[1:])))

    def test_avulso_nao_preve_nada(self):
        with contexto.como(self.ana.pk):
            self.assertIsNone(servicos.definir_frequencia(self.caso_maria, frequencia=servicos.AVULSO))
            self.assertFalse(Consulta.objects.filter(caso=self.caso_maria).exists())

    def test_gerar_de_novo_nao_duplica(self):
        with contexto.como(self.ana.pk):
            self.semanal_da_maria()
            antes = Consulta.objects.count()
            servicos.gerar_consultas()
            self.assertEqual(Consulta.objects.count(), antes)


class TrocaDeFrequencia(BaseAgenda):
    def test_vale_para_esta_e_as_proximas_e_preserva_a_remarcada(self):
        virada = self.terca + timedelta(days=14)
        with contexto.como(self.ana.pk):
            antiga = self.semanal_da_maria()
            terceira = Consulta.objects.get(recorrencia=antiga, data_prevista=virada)
            servicos.remarcar(terceira, inicio=momento(virada + timedelta(days=1), 14))

            nova = servicos.definir_frequencia(
                self.caso_maria, frequencia=QUINZENAL, dia_semana=TERCA, hora=time(16), a_partir_de=virada)

            antiga.refresh_from_db()
            self.assertEqual(antiga.fim, virada)
            self.assertEqual(
                sorted(Consulta.objects.filter(recorrencia=antiga).values_list("data_prevista", flat=True)),
                [self.terca, self.terca + timedelta(days=7), virada])
            self.assertTrue(Consulta.objects.get(pk=terceira.pk).remarcada)
            self.assertTrue(Consulta.objects.filter(recorrencia=nova, inicio=momento(virada, 16)).exists())

    def test_o_passado_nao_e_reescrito(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.definir_frequencia(
                    self.caso_maria, frequencia=SEMANAL, dia_semana=TERCA, hora=time(14),
                    a_partir_de=self.hoje - timedelta(days=1))

    def test_virar_avulso_tira_as_sessoes_futuras(self):
        with contexto.como(self.ana.pk):
            self.semanal_da_maria()
            servicos.definir_frequencia(self.caso_maria, frequencia=servicos.AVULSO)
            self.assertFalse(Consulta.objects.filter(caso=self.caso_maria, estado=Consulta.Estado.AGENDADA).exists())
            self.assertIsNone(self.caso_maria.regra_aberta())

    def test_remarcada_nao_e_gerada_de_novo(self):
        with contexto.como(self.ana.pk):
            regra = self.semanal_da_maria()
            primeira = Consulta.objects.get(recorrencia=regra, data_prevista=self.terca)
            servicos.remarcar(primeira, inicio=momento(self.terca + timedelta(days=1), 9))
            antes = Consulta.objects.count()
            servicos.gerar_consultas()
            self.assertEqual(Consulta.objects.count(), antes)


class Colisao(BaseAgenda):
    def test_avulsa_em_cima_de_sessao_gerada_e_recusada(self):
        with contexto.como(self.ana.pk):
            self.semanal_da_maria()
            with self.assertRaises(ValidationError):
                servicos.marcar_avulsa(self.caso_joao, inicio=momento(self.terca, 14, 30))

    def test_avulsa_em_cima_de_sessao_ainda_nao_gerada_tambem_e_recusada(self):
        """Fora da janela de 8 semanas a sessão não existe como consulta — e mesmo assim ocupa o horário."""
        longe = self.terca + timedelta(weeks=20)
        with contexto.como(self.ana.pk):
            self.semanal_da_maria()
            self.assertFalse(Consulta.objects.filter(data_prevista=longe).exists())
            with self.assertRaises(ValidationError):
                servicos.marcar_avulsa(self.caso_joao, inicio=momento(longe, 14))

    def test_regra_que_bate_em_outra_regra_e_recusada_sem_gravar_nada(self):
        with contexto.como(self.ana.pk):
            self.semanal_da_maria()
            with self.assertRaises(ValidationError):
                servicos.definir_frequencia(
                    self.caso_joao, frequencia=SEMANAL, dia_semana=TERCA, hora=time(14, 30), a_partir_de=self.terca)
            self.assertFalse(Recorrencia.objects.filter(caso=self.caso_joao).exists())

    def test_quinzenais_alternadas_no_mesmo_horario_nao_colidem(self):
        with contexto.como(self.ana.pk):
            self.semanal_da_maria(frequencia=QUINZENAL)
            servicos.definir_frequencia(
                self.caso_joao, frequencia=QUINZENAL, dia_semana=TERCA, hora=time(14),
                a_partir_de=self.terca + timedelta(days=7))
            self.assertTrue(Recorrencia.objects.filter(caso=self.caso_joao).exists())

    def test_consulta_cancelada_libera_o_horario(self):
        with contexto.como(self.ana.pk):
            consulta = servicos.marcar_avulsa(self.caso_maria, inicio=momento(self.terca, 10))
            servicos.registrar(consulta, Consulta.Estado.CANCELADA)
            servicos.marcar_avulsa(self.caso_joao, inicio=momento(self.terca, 10))

    def test_casal_e_uma_consulta_so(self):
        """ADR-026: dois participantes, uma sessão — não colide consigo mesma."""
        with contexto.como(self.ana.pk):
            casal = criar_caso_coletivo([self.maria, self.joao], descricao="Maria e João")
            servicos.marcar_avulsa(casal, inicio=momento(self.terca, 18))
            self.assertEqual(Consulta.objects.filter(caso=casal).count(), 1)


class Registro(BaseAgenda):
    def passada(self, caso=None):
        return servicos.marcar_avulsa(caso or self.caso_joao, inicio=momento(self.hoje - timedelta(days=3), 9))

    def test_realizada_entra_na_cobranca(self):
        with contexto.como(self.ana.pk):
            consulta = servicos.registrar(self.passada(), Consulta.Estado.REALIZADA)
        self.assertTrue(consulta.contabilizada)
        self.assertIsNotNone(consulta.registrada_em)

    def test_falta_segue_o_perfil(self):
        with contexto.como(self.ana.pk):
            self.assertTrue(servicos.registrar(self.passada(), Consulta.Estado.FALTA).contabilizada)
            self.ana.cobra_falta = False
            self.ana.save()
            outra = servicos.marcar_avulsa(self.caso_maria, inicio=momento(self.hoje - timedelta(days=2), 9))
            self.assertFalse(servicos.registrar(outra, Consulta.Estado.FALTA).contabilizada)

    def test_cobranca_se_ajusta_caso_a_caso(self):
        """Sessão de cortesia: realizada, e não entra na cobrança (ADR-023)."""
        with contexto.como(self.ana.pk):
            consulta = servicos.registrar(self.passada(), Consulta.Estado.REALIZADA, contabilizada=False)
        self.assertEqual(consulta.estado, Consulta.Estado.REALIZADA)
        self.assertFalse(consulta.contabilizada)

    def test_consulta_futura_nao_e_registrada_como_realizada(self):
        with contexto.como(self.ana.pk):
            futura = servicos.marcar_avulsa(self.caso_joao, inicio=momento(self.terca, 9))
            with self.assertRaises(ValidationError):
                servicos.registrar(futura, Consulta.Estado.REALIZADA)
            servicos.registrar(futura, Consulta.Estado.CANCELADA)


class Pendencia(BaseAgenda):
    def test_consulta_passada_sem_registro_e_pendencia_e_nao_muda_sozinha(self):
        with contexto.como(self.ana.pk):
            consulta = servicos.marcar_avulsa(self.caso_joao, inicio=momento(self.hoje - timedelta(days=1), 9))
            servicos.gerar_consultas()
            self.assertIn(consulta, list(servicos.consultas_sem_registro()))
            consulta.refresh_from_db()
            self.assertEqual(consulta.estado, Consulta.Estado.AGENDADA)


class Isolamento(BaseAgenda):
    def test_nao_marca_consulta_no_caso_de_outro_psicologo(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.marcar_avulsa(self.caso_carla, inicio=momento(self.terca, 11))

    def test_a_agenda_de_outro_psicologo_nao_bloqueia_o_mesmo_horario(self):
        with contexto.como(self.bruno.pk):
            servicos.definir_frequencia(
                self.caso_carla, frequencia=SEMANAL, dia_semana=TERCA, hora=time(14), a_partir_de=self.terca)
        with contexto.como(self.ana.pk):
            self.semanal_da_maria()
            self.assertFalse(Consulta.objects.filter(caso=self.caso_carla).exists())


class ExclusaoDePaciente(BaseAgenda):
    def test_consultas_so_agendadas_saem_junto(self):
        with contexto.como(self.ana.pk):
            self.semanal_da_maria()
            excluir_paciente(self.maria)
            self.assertFalse(Paciente.objects.filter(pk=self.maria.pk).exists())
        self.assertFalse(Consulta.objetos_todos.filter(caso_id=self.caso_maria.pk).exists())

    def test_atendimento_registrado_impede_a_exclusao(self):
        with contexto.como(self.ana.pk):
            consulta = servicos.marcar_avulsa(self.caso_joao, inicio=momento(self.hoje - timedelta(days=3), 9))
            servicos.registrar(consulta, Consulta.Estado.REALIZADA)
            with self.assertRaises(ValidationError):
                excluir_paciente(self.joao)
            self.assertTrue(Paciente.objects.filter(pk=self.joao.pk).exists())
