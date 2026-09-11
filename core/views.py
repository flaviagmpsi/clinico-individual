"""O painel — a tela que responde "o que eu preciso fazer hoje?" (ADR-027).

⚠️ **Degradar com honestidade** (ADR-012): metade dos indicadores do painel depende de
`Consulta`, que é o passo 2. Em vez de inventar número ou esconder o widget, a tela mostra o que
sabe e **declara o que ainda não sabe**, nomeando o passo que resolve. O psicólogo vê o produto
tomando forma em vez de ver uma tela mentindo que está pronta.
"""

from datetime import date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from pacientes.models import Paciente


class Painel(LoginRequiredMixin, TemplateView):
    template_name = "painel.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        hoje = date.today()

        pacientes = Paciente.objects.all()
        contexto["total_pacientes"] = pacientes.count()
        contexto["novos_no_mes"] = pacientes.filter(
            criado_em__year=hoje.year, criado_em__month=hoje.month
        ).count()
        contexto["sem_cpf"] = pacientes.filter(cpf="").count()
        contexto["ultimos"] = pacientes.order_by("-criado_em")[:5]

        # Herdado do original: o alerta é o paciente que sumiu, não o que está em dia. Sem
        # `Consulta`, a única data de atendimento que existe é a da primeira sessão — serve para
        # provar o cálculo, não para confiar nele. O aviso na tela diz isso.
        limite = hoje - timedelta(days=30)
        contexto["sem_contato_ha_muito"] = pacientes.filter(
            data_primeira_sessao__lt=limite
        ).order_by("data_primeira_sessao")[:5]

        contexto["pendentes"] = [
            ("Agenda e consultas", "passo 2", "A consulta é a âncora do prontuário e da cobrança."),
            ("Prontuário por IA", "passo 3", "A razão de o produto existir (ADR-005)."),
            ("Financeiro", "passo 4", "Depende de consulta contabilizada (ADR-023)."),
            ("Documentos", "passo 5", "Contrato, declaração e cópias emitidas (ADR-021)."),
        ]
        return contexto
