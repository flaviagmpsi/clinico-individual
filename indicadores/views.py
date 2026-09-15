"""O painel — a tela que responde "o que eu preciso fazer hoje?" (ADR-027, ADR-061).

Mora em `indicadores`, que depende de todos os apps e de quem ninguém depende (regra 2). Até a Rodada 39 vivia em
`core`, importando domínio — exceção que a regra 1 não permite e que sai com este app.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from indicadores.servicos import montar_painel


class Painel(LoginRequiredMixin, TemplateView):
    template_name = "painel.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        painel = montar_painel()
        contexto.update(
            mes=painel.mes, resumo=painel.resumo, linhas=painel.linhas,
            sessoes_pendentes=painel.sessoes_pendentes[:5], total_pendentes=len(painel.sessoes_pendentes),
            pagamentos_pendentes=painel.pagamentos_pendentes[:5],
            total_pagamentos_pendentes=len(painel.pagamentos_pendentes),
        )
        return contexto
