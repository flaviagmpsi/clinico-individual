"""A rota do cron e o motor (ADR-144), em modo simulado.

`TransactionTestCase` porque o motor troca o papel do Postgres com `SET LOCAL ROLE`, que se prende à transação —
o mesmo motivo dos testes de tela. Aqui isso é essencial: a rota é anônima (corre sob `hamilton_web`) e o motor
desce para `hamilton_app` por psicólogo. Se a ponte de papel/RLS estiver errada, o disparo falha aqui.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from atendimentos.servicos import cadastrar_avulsa
from contas.models import Psicologo
from core import contexto
from lembretes.models import LembreteEnviado
from pacientes.models import CondicaoCobranca, Paciente
from pacientes.servicos import cadastrar_paciente

SENHA = "senha-de-teste-123"


@override_settings(WHATSAPP_CRON_SEGREDO="segredo-do-cron", WHATSAPP_SIMULADO=True)
class RotaDoCron(TransactionTestCase):
    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.cron@exemplo.com", password=SENHA, nome_completo="Ana Ribeiro", cpf="11111111111",
            telefone="31988887777", crp_regiao="04", crp_numero="313131",
            whatsapp_ligado=True, whatsapp_agenda_manha=True, whatsapp_agenda_manha_hora=time(0, 0))
        self.rota = reverse("lembretes_disparar")

    def test_sem_segredo_ou_com_segredo_errado_recusa(self):
        self.assertEqual(self.client.post(self.rota).status_code, 403)
        self.assertEqual(self.client.post(self.rota, HTTP_X_CRON_SEGREDO="errado").status_code, 403)

    def test_erro_no_motor_vira_500_com_mensagem(self):
        # O cron nunca deve devolver um 500 mudo: o erro é registrado com marcador e a causa volta no corpo.
        with patch("lembretes.views.servicos.disparar", side_effect=ValueError("boom")), \
                self.assertLogs("lembretes", level="ERROR") as logs:
            resposta = self.client.post(self.rota, HTTP_X_CRON_SEGREDO="segredo-do-cron")
        self.assertEqual(resposta.status_code, 500)
        self.assertFalse(resposta.json()["ok"])
        self.assertIn("ValueError: boom", resposta.json()["erro"])
        self.assertTrue(any("LEMBRETES_CRON_FALHOU" in linha for linha in logs.output))

    @override_settings(WHATSAPP_CRON_SEGREDO="  segredo-do-cron\n", WHATSAPP_SIMULADO=True)
    def test_tolera_espaco_invisivel_no_segredo(self):
        # No painel do Render, o valor colado costuma vir com um \n no fim; o cron manda o valor limpo. Tem que casar.
        self.ana.whatsapp_agenda_manha = False
        with contexto.como(self.ana.pk):
            self.ana.save()
        resposta = self.client.post(self.rota, HTTP_X_CRON_SEGREDO="segredo-do-cron")
        self.assertEqual(resposta.status_code, 200)

    def test_sem_nada_na_hora_roda_sem_erro(self):
        # Prova que a ponte de papel/RLS funciona mesmo sem nada a enviar (agenda vazia → conta 0, sem explodir).
        self.ana.whatsapp_agenda_manha = False
        with contexto.como(self.ana.pk):
            self.ana.save()
        resposta = self.client.post(self.rota, HTTP_X_CRON_SEGREDO="segredo-do-cron")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["agenda_do_dia"], 0)

    def test_agenda_da_manha_sai_uma_vez(self):
        agora = timezone.localtime()
        with contexto.como(self.ana.pk):
            caso = cadastrar_paciente(Paciente(nome="Paciente X"))
            inicio = timezone.make_aware(datetime.combine(agora.date(), time(max(agora.hour, 1), 0)))
            cadastrar_avulsa(caso, estado="REALIZADA", inicio=inicio, cobrada=False)

        primeiro = self.client.post(self.rota, HTTP_X_CRON_SEGREDO="segredo-do-cron")
        self.assertEqual(primeiro.status_code, 200)
        self.assertEqual(primeiro.json()["agenda_do_dia"], 1)

        # Idempotente: o segundo disparo no mesmo dia não repete.
        segundo = self.client.post(self.rota, HTTP_X_CRON_SEGREDO="segredo-do-cron")
        self.assertEqual(segundo.json()["agenda_do_dia"], 0)

        with contexto.como(self.ana.pk):
            self.assertEqual(
                LembreteEnviado.objects.filter(assunto__startswith="agenda_do_dia").count(), 1)

    def test_lembrete_de_sessao_ao_paciente_sai_uma_vez(self):
        self.ana.whatsapp_agenda_manha = False  # isola do resumo da manhã
        inicio = timezone.localtime() + timedelta(hours=1, minutes=30)
        with contexto.como(self.ana.pk):
            self.ana.save()
            caso = cadastrar_paciente(Paciente(nome="João Silva", telefone="31999990000"))
            paciente = caso.pacientes.first()
            paciente.whatsapp_lembrete_sessao = True
            paciente.whatsapp_consentimento_em = timezone.localdate()
            paciente.whatsapp_antecedencia_horas = 2  # 1h30 até a sessão cai dentro da janela
            paciente.save()
            cadastrar_avulsa(caso, estado="AGENDADA", inicio=inicio, cobrada=False)

        primeiro = self.client.post(self.rota, HTTP_X_CRON_SEGREDO="segredo-do-cron")
        self.assertEqual(primeiro.json()["lembrete_compromisso"], 1)
        segundo = self.client.post(self.rota, HTTP_X_CRON_SEGREDO="segredo-do-cron")
        self.assertEqual(segundo.json()["lembrete_compromisso"], 0)

    def test_sem_consentimento_nao_manda_lembrete_de_sessao(self):
        self.ana.whatsapp_agenda_manha = False
        inicio = timezone.localtime() + timedelta(hours=1, minutes=30)
        with contexto.como(self.ana.pk):
            self.ana.save()
            caso = cadastrar_paciente(Paciente(nome="Maria Souza", telefone="31999990001"))
            paciente = caso.pacientes.first()
            paciente.whatsapp_lembrete_sessao = True   # ligado, mas SEM consentimento
            paciente.whatsapp_antecedencia_horas = 2
            paciente.save()
            cadastrar_avulsa(caso, estado="AGENDADA", inicio=inicio, cobrada=False)

        resposta = self.client.post(self.rota, HTTP_X_CRON_SEGREDO="segredo-do-cron")
        self.assertEqual(resposta.json()["lembrete_compromisso"], 0)

    def test_aviso_de_pagamento_no_vencimento_sai_uma_vez(self):
        self.ana.whatsapp_agenda_manha = False  # isola do resumo da manhã
        hoje = timezone.localdate()
        with contexto.como(self.ana.pk):
            self.ana.save()
            # Mensalidade que vence hoje (dia fixo = hoje), em aberto porque nada foi pago.
            caso = cadastrar_paciente(
                Paciente(nome="Carla Dias", telefone="31999990002"),
                valor=Decimal("300"), modalidade=CondicaoCobranca.Modalidade.MENSAL,
                dia_vencimento=hoje.day, vigente_desde=hoje.replace(day=1))
            paciente = caso.pacientes.first()
            paciente.whatsapp_aviso_pagamento = True
            paciente.whatsapp_consentimento_em = hoje
            paciente.save()

        primeiro = self.client.post(self.rota, HTTP_X_CRON_SEGREDO="segredo-do-cron")
        self.assertEqual(primeiro.json()["aviso_pagamento"], 1)
        segundo = self.client.post(self.rota, HTTP_X_CRON_SEGREDO="segredo-do-cron")
        self.assertEqual(segundo.json()["aviso_pagamento"], 0)
