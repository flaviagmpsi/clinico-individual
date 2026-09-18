"""O painel — a tela que responde "o que eu preciso fazer agora?" (ADR-027, ADR-061, ADR-069, ADR-072).

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
        pendencias = painel.pendencias
        contexto.update(
            hoje=painel.hoje, mes=painel.mes, resumo=painel.resumo,
            itens=painel.hoje_itens,
            online=sum(1 for item in painel.hoje_itens if item.online), total_hoje=len(painel.hoje_itens),
            total_pendencias=pendencias.total,
            # A lista é inteira: o bloco rola por dentro em vez de cortar (ADR-074).
            sessoes_pendentes=pendencias.sessoes, total_sessoes_pendentes=len(pendencias.sessoes),
            pagamentos_pendentes=pendencias.pagamentos, total_pagamentos_pendentes=len(pendencias.pagamentos),
            prontuarios_pendentes=pendencias.prontuarios, total_prontuarios_pendentes=len(pendencias.prontuarios),
        )
        return contexto
