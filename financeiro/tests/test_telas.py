"""As telas do financeiro, vistas por dois psicólogos ao mesmo tempo.

`test_servicos.py` prova as regras; aqui se prova que as telas não atravessam a fronteira entre psicólogos e que
o registro pela tela funciona. `TransactionTestCase` pelo motivo de sempre: o middleware usa `SET LOCAL ROLE`.
"""

from datetime import date, datetime, time
from decimal import Decimal

from django.db import connection, transaction
from django.db.utils import ProgrammingError
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from atendimentos import servicos as agenda
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto, db
from core.calendario import TipoDia
from financeiro import servicos
from financeiro.models import Pagamento
from pacientes.models import CondicaoCobranca, Paciente
from pacientes.servicos import cadastrar_paciente

SENHA = "senha-de-teste-123"
MENSAL = CondicaoCobranca.Modalidade.MENSAL
REALIZADA = Consulta.Estado.REALIZADA


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


def dia_3_de_setembro():
    return timezone.make_aware(datetime.combine(date(2026, 9, 3), time(10)))


class BaseTelasFinanceiro(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.telafin@exemplo.com", "11111111111", "535353")
        self.bruno = criar_psicologo("bruno.telafin@exemplo.com", "22222222222", "545454")
        with contexto.como(self.ana.pk):
            self.caso_juliana = cadastrar_paciente(
                Paciente(nome="Juliana Tela"), valor=Decimal("700"), modalidade=MENSAL,
                tipo_vencimento=TipoDia.DIA_UTIL, dia_vencimento=5, vigente_desde=date(2026, 9, 1))
            self.caso_marcos = cadastrar_paciente(Paciente(nome="Marcos Tela"), valor=Decimal("200"),
                                                  vigente_desde=date(2026, 1, 1))
            self.consulta_marcos = agenda.cadastrar_avulsa(self.caso_marcos, estado=REALIZADA,
                                                           inicio=dia_3_de_setembro())
        with contexto.como(self.bruno.pk):
            self.caso_carla = cadastrar_paciente(Paciente(nome="Carla Tela"), valor=Decimal("250"),
                                                 vigente_desde=date(2026, 1, 1))
            self.consulta_carla = agenda.cadastrar_avulsa(self.caso_carla, estado=REALIZADA,
                                                          inicio=dia_3_de_setembro())
            self.pagamento_do_bruno = servicos.registrar_pagamento_sessao(
                self.consulta_carla, data=date(2026, 9, 3), forma=Pagamento.Forma.PIX)

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))


class ExigeLoginENaoAtravessa(BaseTelasFinanceiro):
    def test_nenhuma_tela_abre_sem_login(self):
        for nome, args in [
            ("financeiro:mes", []),
            ("financeiro:pagar_mensalidade", [self.caso_juliana.pk, 2026, 9]),
            ("financeiro:pagar_sessao", [self.consulta_marcos.pk]),
            ("financeiro:excluir", [self.pagamento_do_bruno.pk]),
        ]:
            with self.subTest(tela=nome):
                resposta = self.client.get(reverse(nome, args=args))
                self.assertEqual(resposta.status_code, 302)
                self.assertIn(reverse("contas:entrar"), resposta["Location"])

    def test_nada_do_outro_psicologo_e_alcancavel(self):
        self.entrar(self.ana)
        self.assertEqual(self.client.get(reverse("financeiro:pagar_sessao", args=[self.consulta_carla.pk])).status_code, 404)
        self.assertEqual(self.client.get(
            reverse("financeiro:pagar_mensalidade", args=[self.caso_carla.pk, 2026, 9])).status_code, 404)
        self.assertEqual(self.client.post(
            reverse("financeiro:excluir", args=[self.pagamento_do_bruno.pk])).status_code, 404)
        self.assertTrue(Pagamento.objetos_todos.filter(pk=self.pagamento_do_bruno.pk).exists())

    def test_o_mes_mostra_so_os_proprios_pacientes(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("financeiro:mes"), {"mes": "2026-09"})
        self.assertContains(resposta, "Juliana Tela")
        self.assertContains(resposta, "Marcos Tela")
        self.assertNotContains(resposta, "Carla Tela")


class RegistroPelaTela(BaseTelasFinanceiro):
    def test_registrar_pagamento_de_sessao(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("financeiro:pagar_sessao", args=[self.consulta_marcos.pk]), {
            "valor": "200", "data": "2026-09-03", "forma": "PIX", "observacao": ""})
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(Pagamento.objetos_todos.filter(consulta=self.consulta_marcos).exists())

    def test_sem_forma_de_pagamento_volta_explicando(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("financeiro:pagar_sessao", args=[self.consulta_marcos.pk]), {
            "valor": "200", "data": "2026-09-03"})
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(Pagamento.objetos_todos.filter(consulta=self.consulta_marcos).exists())

    def test_registrar_mensalidade_e_excluir(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("financeiro:pagar_mensalidade", args=[self.caso_juliana.pk, 2026, 9]), {
            "valor": "700", "data": "2026-09-05", "forma": "TRANSFERENCIA", "observacao": "Adiantado."})
        self.assertEqual(resposta.status_code, 302)
        pagamento = Pagamento.objetos_todos.get(caso=self.caso_juliana)
        self.assertEqual(pagamento.mes_referencia, date(2026, 9, 1))
        self.assertEqual(self.client.post(reverse("financeiro:excluir", args=[pagamento.pk])).status_code, 302)
        self.assertFalse(Pagamento.objetos_todos.filter(pk=pagamento.pk).exists())

    def test_mes_sem_mensalidade_da_404(self):
        self.entrar(self.ana)
        rota = reverse("financeiro:pagar_mensalidade", args=[self.caso_juliana.pk, 2026, 8])
        self.assertEqual(self.client.get(rota).status_code, 404)

    def test_painel_lembra_pagamento_pendente(self):
        self.entrar(self.ana)
        # ADR-117: o bloco agora se chama "2 pagamentos vencidos", e o que ainda tem prazo fica em "a receber".
        # Aqui tudo já venceu, então o que o painel mostra é o alerta.
        painel = self.client.get(reverse("painel"))
        self.assertContains(painel, "vencido")
        self.assertContains(painel, "bi-exclamation-triangle-fill")


class RLSNoFinanceiro(TransactionTestCase):
    TABELA = "financeiro_pagamento"

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("RLS exige PostgreSQL.")
        self.ana = criar_psicologo("ana.rlsfin@exemplo.com", "33333333333", "555555")
        self.bruno = criar_psicologo("bruno.rlsfin@exemplo.com", "44444444444", "565656")
        for psicologo, nome in [(self.ana, "Da Ana"), (self.bruno, "Do Bruno")]:
            with contexto.como(psicologo.pk):
                caso = cadastrar_paciente(Paciente(nome=nome), valor=Decimal("200"), vigente_desde=date(2026, 1, 1))
                consulta = agenda.cadastrar_avulsa(caso, estado=REALIZADA, inicio=dia_3_de_setembro())
                servicos.registrar_pagamento_sessao(consulta, data=date(2026, 9, 3), forma=Pagamento.Forma.PIX)

    def test_sql_cru_so_devolve_o_proprio_dono(self):
        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.ana.pk)
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT DISTINCT psicologo_id FROM {self.TABELA}")
                donos = {linha[0] for linha in cursor.fetchall()}
        self.assertEqual(donos, {self.ana.pk})

    def test_papel_anonimo_nao_le_pagamentos(self):
        with self.assertRaises(ProgrammingError):
            with transaction.atomic():
                db.assumir_papel_da_web()
                with connection.cursor() as cursor:
                    cursor.execute(f"SELECT 1 FROM {self.TABELA}")
