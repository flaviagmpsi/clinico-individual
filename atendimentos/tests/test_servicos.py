"""A agenda por dentro: previsão calculada, cadastro, pendência, frequência e colisão (ADR-060).

Cada classe guarda uma parte da decisão:

- `Previsao` — a frequência prevê sem gravar nada; o que foi cadastrado sai da previsão.
- `Cadastro` — só o que já aconteceu; a sessão é presumida confirmada até o psicólogo dizer outra coisa.
- `SituacoesECobranca` — as cinco situações da ADR-065: quais cobram, qual aceita escolha, quais ocupam o horário.
- `ModalidadeDaSessao` — o padrão vem do paciente e a sessão pode sair dele.
- `Remarcacao` — ADR-068: a remarcada diz para quando; a sessão nova espera cadastro e não reserva horário.
- `Pendencia` — sessão prevista que passou sem cadastro é pendente, e o sistema não cadastra sozinho (ADR-052).
- `TrocaDeFrequencia` — "desta data em diante"; o que foi cadastrado fica (ADR-022).
- `Colisao` — consultas que ocupam o horário e regras de frequência não se sobrepõem (ADR-024).
- `Isolamento` — ADR-001.
- `ExclusaoDePaciente` — ADR-048: sessão remarcada sai junto; atendimento registrado impede.

Sessões futuras partem de `proxima(...)`, sempre depois de hoje. Sessões **passadas** precisam de uma frequência
que começou no passado, e o serviço recusa isso — o passado não é reescrito. Por isso `frequencia_desde` grava a
regra direto, como uma frequência cadastrada semanas atrás, com a última sessão ontem.
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
REALIZADA = Consulta.Estado.REALIZADA
FALTOU = Consulta.Estado.FALTOU
REMARCADA = Consulta.Estado.REMARCADA
CANCELADA_CLIENTE = Consulta.Estado.CANCELADA_CLIENTE
CANCELADA_PROFISSIONAL = Consulta.Estado.CANCELADA_PROFISSIONAL
PRESENCIAL = Paciente.Modalidade.PRESENCIAL
ONLINE = Paciente.Modalidade.ONLINE


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
        self.ontem = self.hoje - timedelta(days=1)

    def semanal_da_maria(self, hora=14, frequencia=SEMANAL, inicio=None):
        return servicos.definir_frequencia(
            self.caso_maria, frequencia=frequencia, dia_semana=TERCA, hora=time(hora), a_partir_de=inicio or self.terca)

    def frequencia_desde(self, caso, semanas=3, hora=9):
        """Semanal que começou `semanas` atrás, com sessões em ontem - 14, ontem - 7 e ontem."""
        return Recorrencia.objects.create(
            caso=caso, frequencia=SEMANAL, dia_semana=self.ontem.weekday(), hora=time(hora), duracao=50,
            inicio=self.hoje - timedelta(weeks=semanas))

    def avulsa(self, caso, dias=1, hora=10, minuto=0, estado=REALIZADA):
        return servicos.cadastrar_avulsa(
            caso, estado=estado, inicio=momento(self.hoje - timedelta(days=dias), hora, minuto))


class Previsao(BaseAgenda):
    def test_frequencia_preve_sem_gravar_consulta(self):
        with contexto.como(self.ana.pk):
            self.semanal_da_maria()
            previstas = servicos.sessoes_previstas(self.terca, self.terca + timedelta(weeks=3), caso=self.caso_maria)
            self.assertFalse(Consulta.objects.exists())
        self.assertEqual([s.data for s in previstas], [self.terca + timedelta(weeks=n) for n in range(4)])
        self.assertTrue(all(s.duracao == 50 and s.inicio == momento(s.data, 14) for s in previstas))

    def test_quinzenal_e_semana_sim_semana_nao(self):
        with contexto.como(self.ana.pk):
            self.semanal_da_maria(frequencia=QUINZENAL)
            previstas = servicos.sessoes_previstas(self.terca, self.terca + timedelta(weeks=4), caso=self.caso_maria)
        self.assertEqual([s.data for s in previstas],
                         [self.terca, self.terca + timedelta(days=14), self.terca + timedelta(days=28)])

    def test_avulso_nao_preve_nada(self):
        with contexto.como(self.ana.pk):
            self.assertIsNone(servicos.definir_frequencia(self.caso_maria, frequencia=servicos.AVULSO))
            self.assertEqual(
                servicos.sessoes_previstas(self.hoje, self.hoje + timedelta(weeks=8), caso=self.caso_maria), [])

    def test_sessao_cadastrada_sai_da_previsao(self):
        with contexto.como(self.ana.pk):
            regra = self.frequencia_desde(self.caso_maria)
            servicos.cadastrar_prevista(regra, self.ontem, estado=REALIZADA)
            datas = [s.data for s in servicos.sessoes_previstas(regra.inicio, self.hoje, caso=self.caso_maria)]
        self.assertNotIn(self.ontem, datas)
        self.assertEqual(len(datas), 2)


class Cadastro(BaseAgenda):
    def test_realizada_e_cobrada_e_fica_ligada_a_frequencia(self):
        with contexto.como(self.ana.pk):
            regra = self.frequencia_desde(self.caso_joao)
            consulta = servicos.cadastrar_prevista(regra, self.ontem, estado=REALIZADA)
        self.assertTrue(consulta.cobrada)
        self.assertFalse(consulta.avulsa)
        self.assertEqual(consulta.inicio, momento(self.ontem, 9))

    def test_falta_sem_aviso_cobra_e_remarcada_nao(self):
        with contexto.como(self.ana.pk):
            self.assertTrue(self.avulsa(self.caso_joao, dias=2, estado=FALTOU).cobrada)
            self.assertFalse(self.avulsa(self.caso_joao, dias=3, estado=REMARCADA).cobrada)

    def test_avulsa_usa_a_duracao_do_perfil(self):
        with contexto.como(self.ana.pk):
            consulta = self.avulsa(self.caso_joao)
        self.assertTrue(consulta.avulsa)
        self.assertEqual(consulta.duracao, 50)

    def test_so_se_cadastra_o_que_ja_aconteceu(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.cadastrar_avulsa(self.caso_joao, estado=REALIZADA, inicio=momento(self.terca, 10))
            regra = self.semanal_da_maria()
            with self.assertRaises(ValidationError):
                servicos.cadastrar_prevista(regra, self.terca, estado=FALTOU)
            self.assertFalse(Consulta.objects.exists())

    def test_data_que_nao_e_da_frequencia_e_recusada(self):
        with contexto.como(self.ana.pk):
            regra = self.frequencia_desde(self.caso_joao)
            with self.assertRaises(ValidationError):
                servicos.cadastrar_prevista(regra, self.hoje - timedelta(days=2), estado=REALIZADA)

    def test_a_mesma_sessao_nao_e_cadastrada_duas_vezes(self):
        with contexto.como(self.ana.pk):
            regra = self.frequencia_desde(self.caso_joao)
            servicos.cadastrar_prevista(regra, self.ontem, estado=REALIZADA)
            with self.assertRaises(ValidationError):
                servicos.cadastrar_prevista(regra, self.ontem, estado=FALTOU)

    def test_situacao_fora_das_cinco_e_recusada(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.cadastrar_avulsa(self.caso_joao, estado="AGENDADA", inicio=momento(self.ontem, 10))

    def test_corrigir_a_situacao(self):
        with contexto.como(self.ana.pk):
            consulta = self.avulsa(self.caso_joao)
            servicos.alterar_situacao(consulta, REMARCADA)
            consulta.refresh_from_db()
        self.assertEqual(consulta.estado, REMARCADA)
        self.assertFalse(consulta.cobrada)

    def test_excluir_o_cadastro_devolve_a_pendencia(self):
        with contexto.como(self.ana.pk):
            regra = self.frequencia_desde(self.caso_joao)
            servicos.excluir_consulta(servicos.cadastrar_prevista(regra, self.ontem, estado=REALIZADA))
            self.assertIn(self.ontem, [s.data for s in servicos.sessoes_pendentes(caso=self.caso_joao)])


class SituacoesECobranca(BaseAgenda):
    """ADR-065: a sessão é presumida confirmada; o psicólogo só mexe quando algo aconteceu."""

    COBRA = {REALIZADA: True, FALTOU: True, CANCELADA_CLIENTE: True,
             CANCELADA_PROFISSIONAL: False, REMARCADA: False}

    def test_cada_situacao_ja_diz_se_cobra(self):
        with contexto.como(self.ana.pk):
            for dia, (estado, cobra) in enumerate(self.COBRA.items(), start=1):
                with self.subTest(estado=estado):
                    self.assertEqual(self.avulsa(self.caso_joao, dias=dia, estado=estado).cobrada, cobra)

    def test_so_o_cancelamento_do_cliente_aceita_escolha(self):
        """Cortesia é decisão do psicólogo; nas outras situações a cobrança não se negocia."""
        with contexto.como(self.ana.pk):
            cortesia = servicos.cadastrar_avulsa(
                self.caso_joao, estado=CANCELADA_CLIENTE, cobrada=False, inicio=momento(self.ontem, 8))
            realizada = servicos.cadastrar_avulsa(
                self.caso_joao, estado=REALIZADA, cobrada=False, inicio=momento(self.ontem, 9))
        self.assertFalse(cortesia.cobrada)
        self.assertTrue(realizada.cobrada)

    def test_cancelamento_nao_ocupa_o_horario(self):
        """Ninguém esteve na sala: o horário continua livre para quem entrou no lugar."""
        with contexto.como(self.ana.pk):
            self.avulsa(self.caso_maria, hora=10, estado=CANCELADA_CLIENTE)
            self.avulsa(self.caso_joao, hora=10, minuto=30, estado=CANCELADA_PROFISSIONAL)
            consulta = self.avulsa(self.caso_maria, hora=10, minuto=15)
        self.assertTrue(consulta.ocupa_horario)

    def test_corrigir_a_situacao_refaz_a_cobranca(self):
        with contexto.como(self.ana.pk):
            consulta = self.avulsa(self.caso_joao, estado=REMARCADA)
            servicos.alterar_situacao(consulta, CANCELADA_CLIENTE, cobrada=False)
            self.assertFalse(consulta.cobrada)
            servicos.alterar_situacao(consulta, FALTOU)
            consulta.refresh_from_db()
        self.assertTrue(consulta.cobrada)


class ModalidadeDaSessao(BaseAgenda):
    def test_a_sessao_nasce_com_a_modalidade_do_paciente(self):
        with contexto.como(self.ana.pk):
            self.assertEqual(self.avulsa(self.caso_joao).modalidade, PRESENCIAL)
            self.maria.modalidade = ONLINE
            self.maria.save()
            regra = self.frequencia_desde(self.caso_maria)
            prevista = servicos.cadastrar_prevista(regra, self.ontem, estado=REALIZADA)
            [futura] = servicos.sessoes_previstas(self.hoje, self.hoje + timedelta(days=6), caso=self.caso_maria)
        self.assertEqual(prevista.modalidade, ONLINE)
        self.assertEqual(futura.modalidade, ONLINE)

    def test_uma_sessao_pode_sair_do_padrao(self):
        with contexto.como(self.ana.pk):
            consulta = servicos.cadastrar_avulsa(
                self.caso_joao, estado=REALIZADA, modalidade=ONLINE, inicio=momento(self.ontem, 8))
            self.assertEqual(consulta.modalidade, ONLINE)
            servicos.alterar_situacao(consulta, REALIZADA, modalidade=PRESENCIAL)
            consulta.refresh_from_db()
            padrao_do_paciente = Paciente.objects.get(pk=self.joao.pk).modalidade
        self.assertEqual(consulta.modalidade, PRESENCIAL)
        self.assertEqual(padrao_do_paciente, PRESENCIAL)  # a sessão não reescreve o padrão


class Remarcacao(BaseAgenda):
    """ADR-068: a sessão remarcada diz para quando foi, e a data nova entra na agenda esperando cadastro."""

    def remarcar(self, caso, *, dias=1, para_daqui=2, hora=10):
        return servicos.cadastrar_avulsa(
            caso, estado=REMARCADA, inicio=momento(self.hoje - timedelta(days=dias), hora),
            remarcada_para=momento(self.hoje + timedelta(days=para_daqui), hora))

    def test_a_data_nova_fica_esperando_cadastro(self):
        with contexto.como(self.ana.pk):
            consulta = self.remarcar(self.caso_joao)
            [esperada] = servicos.sessoes_remarcadas(self.hoje, self.hoje + timedelta(days=7))
        self.assertEqual(consulta.remarcada_para, esperada.inicio)
        self.assertEqual((esperada.caso, esperada.origem), (self.caso_joao, consulta))
        self.assertFalse(esperada.pendente())  # ainda não chegou

    def test_a_sessao_nova_nao_e_gravada_junto(self):
        """ADR-060 continua valendo: consulta só existe depois de acontecer."""
        with contexto.como(self.ana.pk):
            self.remarcar(self.caso_joao)
            self.assertEqual(Consulta.objects.count(), 1)

    def test_cadastrar_a_sessao_nova_tira_da_espera(self):
        with contexto.como(self.ana.pk):
            consulta = self.remarcar(self.caso_joao, para_daqui=0, hora=8)
            servicos.cadastrar_avulsa(self.caso_joao, estado=REALIZADA, inicio=consulta.remarcada_para,
                                      agora=consulta.remarcada_para)
            self.assertEqual(servicos.sessoes_remarcadas(self.hoje, self.hoje + timedelta(days=7)), [])

    def test_so_a_remarcada_tem_data_nova(self):
        with contexto.como(self.ana.pk):
            consulta = servicos.cadastrar_avulsa(
                self.caso_joao, estado=REALIZADA, inicio=momento(self.ontem, 8),
                remarcada_para=momento(self.hoje + timedelta(days=1), 8))
            self.assertIsNone(consulta.remarcada_para)

    def test_corrigir_a_situacao_apaga_a_data_nova(self):
        with contexto.como(self.ana.pk):
            consulta = self.remarcar(self.caso_joao)
            servicos.alterar_situacao(consulta, FALTOU)
            consulta.refresh_from_db()
        self.assertIsNone(consulta.remarcada_para)

    def test_a_espera_nao_reserva_o_horario(self):
        """Previsão não é registro (ADR-024): o horário só é ocupado quando a sessão for cadastrada."""
        with contexto.como(self.ana.pk):
            remarcada = self.remarcar(self.caso_joao, para_daqui=0, hora=8)
            outra = servicos.cadastrar_avulsa(self.caso_maria, estado=REALIZADA,
                                              inicio=remarcada.remarcada_para, agora=remarcada.remarcada_para)
        self.assertTrue(outra.ocupa_horario)

    def test_a_remarcada_que_ja_passou_entra_na_pendencia(self):
        with contexto.como(self.ana.pk):
            consulta = servicos.cadastrar_avulsa(
                self.caso_joao, estado=REMARCADA, inicio=momento(self.hoje - timedelta(days=5), 8),
                remarcada_para=momento(self.ontem, 8))
            pendentes = servicos.sessoes_pendentes(caso=self.caso_joao)
        self.assertIn(consulta.pk, [getattr(s, "origem", None) and s.origem.pk for s in pendentes])


class Pendencia(BaseAgenda):
    def test_sessao_prevista_que_passou_e_pendente_e_nada_e_cadastrado(self):
        with contexto.como(self.ana.pk):
            self.frequencia_desde(self.caso_joao)
            pendentes = servicos.sessoes_pendentes(caso=self.caso_joao)
            self.assertFalse(Consulta.objects.exists())
        self.assertEqual([s.data for s in pendentes],
                         [self.ontem - timedelta(days=14), self.ontem - timedelta(days=7), self.ontem])

    def test_sessao_futura_nao_e_pendente(self):
        with contexto.como(self.ana.pk):
            self.semanal_da_maria()
            self.assertEqual(servicos.sessoes_pendentes(caso=self.caso_maria), [])


class TrocaDeFrequencia(BaseAgenda):
    def test_vale_desta_data_em_diante(self):
        virada = self.terca + timedelta(days=14)
        with contexto.como(self.ana.pk):
            antiga = self.semanal_da_maria()
            nova = servicos.definir_frequencia(
                self.caso_maria, frequencia=QUINZENAL, dia_semana=TERCA, hora=time(16), a_partir_de=virada)
            antiga.refresh_from_db()
            previstas = servicos.sessoes_previstas(self.terca, virada + timedelta(days=14), caso=self.caso_maria)
        self.assertEqual(antiga.fim, virada)
        self.assertEqual(
            [(s.regra.pk, s.data) for s in previstas],
            [(antiga.pk, self.terca), (antiga.pk, self.terca + timedelta(days=7)),
             (nova.pk, virada), (nova.pk, virada + timedelta(days=14))])

    def test_o_passado_nao_e_reescrito(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.definir_frequencia(
                    self.caso_maria, frequencia=SEMANAL, dia_semana=TERCA, hora=time(14),
                    a_partir_de=self.hoje - timedelta(days=1))

    def test_corrigir_no_mesmo_dia_apaga_a_frequencia_que_nunca_valeu(self):
        with contexto.como(self.ana.pk):
            self.semanal_da_maria()
            self.semanal_da_maria(hora=15)
            self.assertEqual(Recorrencia.objects.filter(caso=self.caso_maria).count(), 1)
            self.assertEqual(self.caso_maria.regra_aberta().hora, time(15))

    def test_o_que_foi_cadastrado_fica_quando_a_frequencia_muda(self):
        with contexto.como(self.ana.pk):
            regra = self.frequencia_desde(self.caso_maria)
            consulta = servicos.cadastrar_prevista(regra, self.ontem - timedelta(days=14), estado=REALIZADA)
            servicos.definir_frequencia(self.caso_maria, frequencia=servicos.AVULSO)
            regra.refresh_from_db()
            self.assertEqual(regra.fim, self.hoje)
            self.assertTrue(Consulta.objects.filter(pk=consulta.pk).exists())
            self.assertEqual(len(servicos.sessoes_pendentes(caso=self.caso_maria)), 2)


class Colisao(BaseAgenda):
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

    def test_duas_consultas_no_mesmo_horario_sao_recusadas(self):
        with contexto.como(self.ana.pk):
            self.avulsa(self.caso_maria, hora=10)
            with self.assertRaises(ValidationError):
                self.avulsa(self.caso_joao, hora=10, minuto=30)

    def test_falta_remarcada_nao_ocupa_o_horario(self):
        with contexto.como(self.ana.pk):
            self.avulsa(self.caso_maria, hora=10, estado=REMARCADA)
            self.avulsa(self.caso_joao, hora=10)

    def test_sessao_prevista_nao_bloqueia_cadastro(self):
        """Previsão não é registro: se o João foi atendido no horário da Maria, a sessão dela não aconteceu ali."""
        with contexto.como(self.ana.pk):
            self.frequencia_desde(self.caso_maria, hora=9)
            self.avulsa(self.caso_joao, hora=9)

    def test_casal_e_uma_consulta_so(self):
        """ADR-026: dois participantes, uma sessão — não colide consigo mesma."""
        with contexto.como(self.ana.pk):
            casal = criar_caso_coletivo([self.maria, self.joao], descricao="Maria e João")
            self.avulsa(casal, hora=18)
            self.assertEqual(Consulta.objects.filter(caso=casal).count(), 1)


class Isolamento(BaseAgenda):
    def test_nao_cadastra_consulta_no_caso_de_outro_psicologo(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                self.avulsa(self.caso_carla)

    def test_a_frequencia_de_outro_psicologo_nao_bloqueia_nem_aparece(self):
        with contexto.como(self.bruno.pk):
            servicos.definir_frequencia(
                self.caso_carla, frequencia=SEMANAL, dia_semana=TERCA, hora=time(14), a_partir_de=self.terca)
        with contexto.como(self.ana.pk):
            self.semanal_da_maria()
            casos = {s.caso for s in servicos.sessoes_previstas(self.terca, self.terca)}
        self.assertEqual(casos, {self.caso_maria})


class ExclusaoDePaciente(BaseAgenda):
    def test_frequencia_e_falta_remarcada_saem_junto(self):
        with contexto.como(self.ana.pk):
            regra = self.frequencia_desde(self.caso_maria)
            servicos.cadastrar_prevista(regra, self.ontem, estado=REMARCADA)
            excluir_paciente(self.maria)
            self.assertFalse(Paciente.objects.filter(pk=self.maria.pk).exists())
        self.assertFalse(Consulta.objetos_todos.filter(caso_id=self.caso_maria.pk).exists())

    def test_atendimento_registrado_impede_a_exclusao(self):
        with contexto.como(self.ana.pk):
            self.avulsa(self.caso_joao, dias=3)
            with self.assertRaises(ValidationError):
                excluir_paciente(self.joao)
            self.assertTrue(Paciente.objects.filter(pk=self.joao.pk).exists())
