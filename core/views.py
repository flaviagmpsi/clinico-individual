"""O painel — a tela que responde "o que eu preciso fazer hoje?" (ADR-027).

⚠️ **Degradar com honestidade** (ADR-012): parte dos indicadores do painel depende de módulos que ainda
não existem. Em vez de inventar número ou esconder o widget, a tela mostra o que sabe e **declara o que
ainda não sabe**, nomeando o passo que resolve.

⚠️ O painel vive em `core` provisoriamente e importa apps de domínio, o que a regra 1 de dependência não
permite a `core`. O lugar dele é o app `indicadores` (regra 2), que ainda não existe.
"""

from datetime import date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from atendimentos.servicos import sessoes_pendentes
from financeiro.servicos import pagamentos_pendentes
from pacientes.servicos import pacientes_ativos


class Painel(LoginRequiredMixin, TemplateView):
    template_name = "painel.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        hoje = date.today()

        # ADR-027: o painel fala de quem está em atendimento. Encerrados ficam na lista própria (ADR-055).
        pacientes = pacientes_ativos()
        contexto["total_pacientes"] = pacientes.count()
        contexto["novos_no_mes"] = pacientes.filter(
            criado_em__year=hoje.year, criado_em__month=hoje.month
        ).count()
        contexto["sem_cpf"] = pacientes.filter(cpf="").count()
        contexto["ultimos"] = pacientes.order_by("-criado_em")[:5]

        # ADR-052 e ADR-060: sessão prevista que passou sem cadastro. É pendência, nunca cadastro automático.
        pendentes_de_cadastro = sessoes_pendentes()
        contexto["total_pendentes"] = len(pendentes_de_cadastro)
        contexto["sessoes_pendentes"] = pendentes_de_cadastro[:5]

        # ADR-063: o lembrete de pagamento. Aparece no vencimento e some quando o pago cobre o devido.
        pagamentos = pagamentos_pendentes()
        contexto["total_pagamentos_pendentes"] = len(pagamentos)
        contexto["pagamentos_pendentes"] = pagamentos[:5]

        # Herdado do original: o alerta é o paciente que sumiu, não o que está em dia. Enquanto o painel não
        # olha as consultas realizadas, a única data de atendimento que ele usa é a da primeira sessão.
        limite = hoje - timedelta(days=30)
        contexto["sem_contato_ha_muito"] = pacientes.filter(
            data_primeira_sessao__lt=limite
        ).order_by("data_primeira_sessao")[:5]

        contexto["pendentes"] = [
            ("Lixeira de pacientes", "passo 2",
             "Paciente com atendimento registrado ainda não pode ser excluído (ADR-048)."),
            ("Prontuário por IA", "passo 3", "A razão de o produto existir (ADR-005)."),
            ("Painel novo", "próximo", "Sessões, receita e situação de cada paciente no mês (ADR-061)."),
            ("Documentos", "passo 5", "Contrato, declaração e cópias emitidas (ADR-021)."),
        ]
        return contexto
