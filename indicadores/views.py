"""O painel — a tela que responde "o que eu preciso fazer agora?" (ADR-027, ADR-061, ADR-069, ADR-072).

Mora em `indicadores`, que depende de todos os apps e de quem ninguém depende (regra 2). Até a Rodada 39 vivia em
`core`, importando domínio — exceção que a regra 1 não permite e que sai com este app.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from django.utils import timezone

from indicadores import estatisticas, periodo
from indicadores.servicos import montar_painel


class Painel(LoginRequiredMixin, TemplateView):
    template_name = "painel.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        painel = montar_painel()
        pendencias = painel.pendencias
        agora = timezone.now()
        # A próxima sessão do dia: a primeira ainda por acontecer. É o que a tela destaca (ADR-089).
        proxima = next((item for item in painel.hoje_itens if not item.cadastrada and item.inicio >= agora), None)
        contexto.update(
            hoje=painel.hoje, mes=painel.mes, resumo=painel.resumo,
            itens=painel.hoje_itens, proxima=proxima,
            online=sum(1 for item in painel.hoje_itens if item.online), total_hoje=len(painel.hoje_itens),
            total_pendencias=pendencias.total,
            # A lista é inteira: o bloco rola por dentro em vez de cortar (ADR-074).
            sessoes_pendentes=pendencias.sessoes, total_sessoes_pendentes=len(pendencias.sessoes),
            pagamentos_pendentes=pendencias.pagamentos, total_pagamentos_pendentes=len(pendencias.pagamentos),
            prontuarios_pendentes=pendencias.prontuarios, total_prontuarios_pendentes=len(pendencias.prontuarios),
            aniversariantes=estatisticas.aniversariantes_do_mes(painel.hoje),
        )
        # ADR-103: "como a clínica funcionou" mora aqui, e não numa aba à parte — responde pelo mês ou pelo ano.
        contexto.update(periodo.contexto_do_seletor(self.request, painel.hoje))
        retrato = estatisticas.retrato_da_clinica(contexto["periodo"])
        contexto.update(retrato=retrato, grafico={
            "presenca": [retrato.presenca.presentes, retrato.presenca.faltas,
                         retrato.presenca.canceladas_pelo_cliente],
            "composicao": [retrato.composicao.semanais, retrato.composicao.quinzenais, retrato.composicao.avulsos],
        })
        return contexto
