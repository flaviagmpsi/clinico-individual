"""O financeiro por dentro: o que é devido, o que foi pago, e quando vira lembrete (ADR-062, ADR-063).

- `Mensalidade` — vence no dia fixo ou no dia útil; é cheia; não existe com o mês inteiro encerrado.
- `Lembrete` — **vencida** só a partir do vencimento (ADR-121); pago antes, nunca aparece; pagou menos, fica o resto.
- `PorSessao` — cada sessão cobrada gera a sua pendência; remarcada não; quitar uma não quita outra.
- `ValorDestaSessao` — ADR-070: a extra do mensalista e a de quem não tem valor combinado, cobradas à parte.
- `Registro` — forma obrigatória, sem data futura, referência coerente com a modalidade.
- `ConsultaComPagamento` — não é excluída nem vira falta remarcada.
- `Isolamento` — ADR-001.

Datas fixas de setembro de 2026, conferidas: 1º/09 é terça, 07/09 é feriado, e o 5º dia útil é 08/09. Consulta só
se cadastra no passado, então as datas precisam ser anteriores ao dia em que o teste roda.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from atendimentos import servicos as agenda
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto
from core.calendario import TipoDia
from financeiro import servicos
from financeiro.models import Pagamento
from pacientes.models import CondicaoCobranca, Paciente
from pacientes.servicos import cadastrar_paciente

MENSAL = CondicaoCobranca.Modalidade.MENSAL
PIX = Pagamento.Forma.PIX
REALIZADA = Consulta.Estado.REALIZADA
FALTOU = Consulta.Estado.FALTOU
REMARCADA = Consulta.Estado.REMARCADA


def setembro(dia):
    return date(2026, 9, dia)


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password="senha-de-teste-123", nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


class BaseFinanceiro(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.financeiro@exemplo.com", "11111111111", "515151")
        cls.bruno = criar_psicologo("bruno.financeiro@exemplo.com", "22222222222", "525252")
        with contexto.como(cls.ana.pk):
            cls.caso_juliana = cadastrar_paciente(
                Paciente(nome="Juliana"), valor=Decimal("700"), modalidade=MENSAL,
                tipo_vencimento=TipoDia.DIA_UTIL, dia_vencimento=5, vigente_desde=setembro(1))
            cls.caso_marcos = cadastrar_paciente(Paciente(nome="Marcos"), valor=Decimal("200"),
                                                 vigente_desde=date(2026, 1, 1))
        with contexto.como(cls.bruno.pk):
            cls.caso_carla = cadastrar_paciente(Paciente(nome="Carla"), valor=Decimal("250"),
                                                vigente_desde=date(2026, 1, 1))

    def sessao(self, caso, dia, estado=REALIZADA):
        return agenda.cadastrar_avulsa(
            caso, estado=estado, inicio=timezone.make_aware(datetime.combine(setembro(dia), time(10))))

    def pagar_setembro(self, valor, dia=2):
        return servicos.registrar_pagamento_mensalidade(
            self.caso_juliana, ano=2026, mes=9, valor=Decimal(valor), data=setembro(dia), forma=PIX)

    def vencidas(self, dia, caso):
        """ADR-121: o que passou do vencimento. Era `pagamentos_pendentes`; o nome mudou, o sentido não."""
        return servicos.pagamentos_vencidos(setembro(dia), caso=caso)


class Mensalidade(BaseFinanceiro):
    def test_vence_no_quinto_dia_util_pulando_o_feriado(self):
        with contexto.como(self.ana.pk):
            [cobranca] = servicos.cobrancas_do_mes(2026, 9, caso=self.caso_juliana)
        self.assertEqual((cobranca.tipo, cobranca.vencimento, cobranca.devido, cobranca.pago),
                         (servicos.MENSALIDADE, setembro(8), Decimal("700"), Decimal("0")))

    def test_dia_fixo_e_mensalidade_cheia_mesmo_comecando_no_meio_do_mes(self):
        with contexto.como(self.ana.pk):
            caso = cadastrar_paciente(Paciente(nome="Dia Fixo"), valor=Decimal("600"), modalidade=MENSAL,
                                      dia_vencimento=10, vigente_desde=date(2026, 8, 20))
            [cobranca] = servicos.cobrancas_do_mes(2026, 8, caso=caso)
        self.assertEqual((cobranca.vencimento, cobranca.devido), (date(2026, 8, 10), Decimal("600")))

    def test_mes_inteiro_encerrado_nao_tem_mensalidade(self):
        with contexto.como(self.ana.pk):
            caso = cadastrar_paciente(Paciente(nome="Encerrada"), valor=Decimal("600"), modalidade=MENSAL,
                                      dia_vencimento=10, vigente_desde=date(2026, 7, 1))
            agenda.registrar_desfecho(caso, tipo="DESISTENCIA", data=date(2026, 8, 15))
            self.assertEqual(len(servicos.cobrancas_do_mes(2026, 8, caso=caso)), 1)
            self.assertEqual(servicos.cobrancas_do_mes(2026, 9, caso=caso), [])

    def test_quem_paga_por_sessao_nao_tem_mensalidade(self):
        with contexto.como(self.ana.pk):
            self.assertEqual(servicos.cobrancas_do_mes(2026, 9, caso=self.caso_marcos), [])


class Lembrete(BaseFinanceiro):
    def test_so_aparece_a_partir_do_vencimento(self):
        with contexto.como(self.ana.pk):
            self.assertEqual(self.vencidas(7, self.caso_juliana), [])
            self.assertEqual(len(self.vencidas(8, self.caso_juliana)), 1)

    def test_pago_antes_do_vencimento_nunca_aparece(self):
        with contexto.como(self.ana.pk):
            self.pagar_setembro("700", dia=2)
            self.assertEqual(self.vencidas(30, self.caso_juliana), [])

    def test_pagou_menos_fica_pendente_o_resto(self):
        with contexto.como(self.ana.pk):
            self.pagar_setembro("500")
            [cobranca] = self.vencidas(30, self.caso_juliana)
        self.assertEqual(cobranca.saldo, Decimal("200"))

    def test_pagou_a_mais_e_so_mais_um_registro(self):
        with contexto.como(self.ana.pk):
            self.pagar_setembro("700")
            self.pagar_setembro("100", dia=3)
            [cobranca] = servicos.cobrancas_do_mes(2026, 9, caso=self.caso_juliana)
        self.assertEqual((cobranca.pago, cobranca.saldo, cobranca.quitada), (Decimal("800"), Decimal("0"), True))
        self.assertEqual(len(cobranca.pagamentos), 2)


class PorSessao(BaseFinanceiro):
    def test_cada_sessao_cobrada_gera_a_sua_pendencia_e_remarcada_nao(self):
        with contexto.como(self.ana.pk):
            self.sessao(self.caso_marcos, 3)
            self.sessao(self.caso_marcos, 4, FALTOU)
            self.sessao(self.caso_marcos, 5, REMARCADA)
            cobrancas = servicos.cobrancas_do_mes(2026, 9, caso=self.caso_marcos)
        self.assertEqual([(c.tipo, c.vencimento, c.devido) for c in cobrancas],
                         [(servicos.SESSAO, setembro(3), Decimal("200")), (servicos.SESSAO, setembro(4), Decimal("200"))])

    def test_pagar_uma_sessao_nao_quita_outra(self):
        with contexto.como(self.ana.pk):
            primeira = self.sessao(self.caso_marcos, 3)
            self.sessao(self.caso_marcos, 4)
            servicos.registrar_pagamento_sessao(primeira, data=setembro(3), forma=PIX)
            vencidas = self.vencidas(10, self.caso_marcos)
        self.assertEqual([c.vencimento for c in vencidas], [setembro(4)])

    def test_sem_valor_paga_o_que_falta(self):
        with contexto.como(self.ana.pk):
            consulta = self.sessao(self.caso_marcos, 3)
            servicos.registrar_pagamento_sessao(consulta, valor=Decimal("150"), data=setembro(3), forma=PIX)
            self.assertEqual(servicos.registrar_pagamento_sessao(consulta, data=setembro(4), forma=PIX).valor,
                             Decimal("50"))
            with self.assertRaises(ValidationError):
                servicos.registrar_pagamento_sessao(consulta, data=setembro(5), forma=PIX)

    def test_sessao_de_quem_paga_mensalidade_nao_gera_cobranca(self):
        with contexto.como(self.ana.pk):
            consulta = self.sessao(self.caso_juliana, 3)
            tipos = [c.tipo for c in servicos.cobrancas_do_mes(2026, 9, caso=self.caso_juliana)]
            with self.assertRaises(ValidationError):
                servicos.registrar_pagamento_sessao(consulta, data=setembro(3), forma=PIX)
        self.assertEqual(tipos, [servicos.MENSALIDADE])


class ValorDestaSessao(BaseFinanceiro):
    """ADR-070: o valor digitado na sessão manda — é o que cobra a extra e a de quem não combinou preço."""

    def test_sessao_extra_do_mensalista_cobra_a_parte(self):
        with contexto.como(self.ana.pk):
            consulta = self.sessao(self.caso_juliana, 3)
            servicos_agenda_valor = agenda.alterar_situacao(consulta, REALIZADA, valor=Decimal("150"))
            cobrancas = servicos.cobrancas_do_mes(2026, 9, caso=self.caso_juliana)
        self.assertEqual(servicos_agenda_valor.valor, Decimal("150"))
        self.assertEqual([(c.tipo, c.devido) for c in cobrancas],
                         [(servicos.SESSAO, Decimal("150")), (servicos.MENSALIDADE, Decimal("700"))])

    def test_a_extra_sem_valor_continua_dentro_da_mensalidade(self):
        with contexto.como(self.ana.pk):
            self.sessao(self.caso_juliana, 4)
            tipos = [c.tipo for c in servicos.cobrancas_do_mes(2026, 9, caso=self.caso_juliana)]
        self.assertEqual(tipos, [servicos.MENSALIDADE])

    def test_paciente_sem_valor_combinado_cobra_pelo_valor_da_sessao(self):
        with contexto.como(self.ana.pk):
            caso = cadastrar_paciente(Paciente(nome="Sem Valor"))
            consulta = agenda.cadastrar_avulsa(
                caso, estado=REALIZADA, valor=Decimal("180"),
                inicio=timezone.make_aware(datetime.combine(setembro(3), time(15))))
            [cobranca] = servicos.cobrancas_do_mes(2026, 9, caso=caso)
            pagamento = servicos.registrar_pagamento_sessao(consulta, data=setembro(3), forma=PIX)
        self.assertEqual((cobranca.devido, pagamento.valor), (Decimal("180"), Decimal("180")))

    def test_pagar_a_sessao_extra_do_mensalista(self):
        with contexto.como(self.ana.pk):
            consulta = self.sessao(self.caso_juliana, 5)
            agenda.alterar_situacao(consulta, REALIZADA, valor=Decimal("150"))
            servicos.registrar_pagamento_sessao(consulta, data=setembro(5), forma=PIX)
            vencidas = [c.tipo for c in self.vencidas(30, self.caso_juliana)]
        self.assertEqual(vencidas, [servicos.MENSALIDADE])  # a extra foi paga; a mensalidade continua

    def test_sessao_que_nao_cobra_nao_tem_valor(self):
        with contexto.como(self.ana.pk):
            consulta = agenda.cadastrar_avulsa(
                self.caso_marcos, estado=REMARCADA, valor=Decimal("200"),
                inicio=timezone.make_aware(datetime.combine(setembro(6), time(15))))
            self.assertIsNone(consulta.valor)

            cobrada = self.sessao(self.caso_marcos, 7)
            agenda.alterar_situacao(cobrada, REALIZADA, valor=Decimal("300"))
            agenda.alterar_situacao(cobrada, REMARCADA)
            cobrada.refresh_from_db()
        self.assertIsNone(cobrada.valor)


class Registro(BaseFinanceiro):
    def test_forma_de_pagamento_e_obrigatoria(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.registrar_pagamento_mensalidade(
                    self.caso_juliana, ano=2026, mes=9, valor=Decimal("700"), data=setembro(2), forma="")

    def test_data_no_futuro_e_recusada(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.registrar_pagamento_mensalidade(
                    self.caso_juliana, ano=2026, mes=9, valor=Decimal("700"),
                    data=timezone.localdate() + timedelta(days=1), forma=PIX)

    def test_mes_sem_mensalidade_e_recusado(self):
        with contexto.como(self.ana.pk):
            for caso, mes in [(self.caso_marcos, 9), (self.caso_juliana, 8)]:
                with self.subTest(caso=caso, mes=mes):
                    with self.assertRaises(ValidationError):
                        servicos.registrar_pagamento_mensalidade(
                            caso, ano=2026, mes=mes, valor=Decimal("700"), data=setembro(2), forma=PIX)

    def test_valor_zero_e_recusado(self):
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                self.pagar_setembro("0")


class ConsultaComPagamento(BaseFinanceiro):
    def test_nao_e_excluida_nem_vira_falta_remarcada(self):
        with contexto.como(self.ana.pk):
            consulta = self.sessao(self.caso_marcos, 3)
            servicos.registrar_pagamento_sessao(consulta, data=setembro(3), forma=PIX)
            with self.assertRaises(ValidationError):
                agenda.excluir_consulta(consulta)
            with self.assertRaises(ValidationError):
                agenda.alterar_situacao(consulta, REMARCADA)
            agenda.alterar_situacao(consulta, FALTOU)  # continua cobrada: permitido


class Isolamento(BaseFinanceiro):
    def test_pendencias_de_outro_psicologo_nao_aparecem(self):
        with contexto.como(self.bruno.pk):
            self.sessao(self.caso_carla, 3)
        with contexto.como(self.ana.pk):
            casos = {c.caso for c in servicos.pagamentos_vencidos(setembro(30))}
        self.assertNotIn(self.caso_carla, casos)

    def test_nao_paga_sessao_de_outro_psicologo(self):
        with contexto.como(self.bruno.pk):
            consulta_da_carla = self.sessao(self.caso_carla, 3)
        with contexto.como(self.ana.pk):
            with self.assertRaises(ValidationError):
                servicos.registrar_pagamento_sessao(consulta_da_carla, data=setembro(3), forma=PIX)
