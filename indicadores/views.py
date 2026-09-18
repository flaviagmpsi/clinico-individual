"""O painel — a tela que responde "o que eu preciso fazer agora?" (ADR-027, ADR-061, ADR-069, ADR-072).

Mora em `indicadores`, que depende de todos os apps e de quem ninguém depende (regra 2). Até a Rodada 39 vivia em
`core`, importando domínio — exceção que a regra 1 não permite e que sai com este app.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from django.utils import timezone

from indicadores import estatisticas
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
            aniversariantes=estatisticas.aniversariantes_do_mes(painel.hoje),
        )
        return contexto


class Estatisticas(LoginRequiredMixin, TemplateView):
    """A aba de estatísticas (ADR-084): o ano em receitas e despesas, e o retrato dos atendimentos."""

    template_name = "indicadores/estatisticas.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        hoje = timezone.localdate()
        pedido = self.request.GET.get("ano", "")
        ano = int(pedido) if pedido.isdigit() and 2000 <= int(pedido) <= 2100 else hoje.year
        dados = estatisticas.montar(ano)
        contexto.update(
            ano=ano, este_ano=hoje.year, e=dados,
            # O que os gráficos leem. Só números e rótulos — nenhum nome de paciente vai para o JavaScript.
            grafico={
                "meses": estatisticas.MESES,
                "receitas_recebidas": [float(f.receitas_recebidas) for f in dados.fluxos],
                "receitas_a_receber": [float(f.receitas_a_receber) for f in dados.fluxos],
                "despesas_pagas": [float(f.despesas_pagas) for f in dados.fluxos],
                "despesas_a_pagar": [float(f.despesas_a_pagar) for f in dados.fluxos],
                "resultado": [float(f.resultado) for f in dados.fluxos],
                "horarios": {"rotulos": [r for r, _ in dados.horarios], "valores": [n for _, n in dados.horarios]},
                "dias": {"rotulos": [r for r, _ in dados.dias], "valores": [n for _, n in dados.dias]},
                "composicao": [dados.composicao.semanais, dados.composicao.quinzenais, dados.composicao.avulsos],
                "presenca": [dados.presenca.presentes, dados.presenca.faltas, dados.presenca.canceladas_pelo_cliente],
            })
        return contexto
