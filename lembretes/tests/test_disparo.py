"""A rota do cron e o motor (ADR-144), em modo simulado.

`TransactionTestCase` porque o motor troca o papel do Postgres com `SET LOCAL ROLE`, que se prende à transação —
o mesmo motivo dos testes de tela. Aqui isso é essencial: a rota é anônima (corre sob `hamilton_web`) e o motor
desce para `hamilton_app` por psicólogo. Se a ponte de papel/RLS estiver errada, o disparo falha aqui.
"""

from datetime import datetime, time

from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from atendimentos.servicos import cadastrar_avulsa
from contas.models import Psicologo
from core import contexto
from lembretes.models import LembreteEnviado
from pacientes.models import Paciente
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
