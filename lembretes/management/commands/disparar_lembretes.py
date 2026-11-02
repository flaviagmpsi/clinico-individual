"""Dispara os lembretes por WhatsApp que estão na hora (ADR-144).

O cron externo normalmente bate na rota `/lembretes/disparar/`; este comando é para rodar à mão e depurar. Abre a
transação que o motor exige (SET LOCAL ROLE e set_config só valem dentro de uma). Em modo simulado, só registra.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from lembretes import servicos


class Command(BaseCommand):
    help = "Dispara os lembretes por WhatsApp que estão na hora. Em modo simulado, só registra (não chama a Meta)."

    def handle(self, *args, **opcoes):
        with transaction.atomic():
            contagem = servicos.disparar()
        self.stdout.write(self.style.SUCCESS(f"Lembretes disparados: {contagem}"))
