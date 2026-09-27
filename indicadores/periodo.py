"""O período de uma estatística: um mês ou um ano (ADR-103).

A aba de Estatísticas deixou de existir e os blocos dela foram para as telas de que falam — painel, agenda,
pacientes, financeiro (ADR-103). Cada um continua respondendo **pelo mês ou pelo ano**, e é aqui que essa escolha
mora, para as quatro telas lerem a URL do mesmo jeito e o seletor ser um pedaço de template só.

Na URL: `?periodo=ano&ano=2026` ou `?mes=2026-09`. Sem nada, ou com lixo, vale o mês corrente (ADR-087).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone

MESES_POR_EXTENSO = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                     "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


@dataclass(frozen=True)
class Periodo:
    ano: int
    mes: int | None  # `None` é o ano inteiro

    @property
    def primeiro_dia(self) -> date:
        return date(self.ano, self.mes or 1, 1)

    @property
    def ultimo_dia(self) -> date:
        if self.mes is None:
            return date(self.ano, 12, 31)
        return date(self.ano + (self.mes == 12), (self.mes % 12) + 1, 1) - timedelta(days=1)

    @property
    def inicio(self) -> datetime:
        return timezone.make_aware(datetime.combine(self.primeiro_dia, time.min))

    @property
    def fim(self) -> datetime:
        """Exclusivo: a meia-noite do dia seguinte ao último."""
        return timezone.make_aware(datetime.combine(self.ultimo_dia, time.min)) + timedelta(days=1)

    @property
    def rotulo(self) -> str:
        return f"{MESES_POR_EXTENSO[self.mes - 1]} de {self.ano}" if self.mes else str(self.ano)

    @property
    def por_mes(self) -> bool:
        return self.mes is not None

    def na_url(self) -> str:
        return f"mes={self.ano}-{self.mes:02d}" if self.mes else f"periodo=ano&ano={self.ano}"

    def anterior(self) -> "Periodo":
        if self.mes is None:
            return Periodo(self.ano - 1, None)
        return Periodo(self.ano - (self.mes == 1), 12 if self.mes == 1 else self.mes - 1)

    def proximo(self) -> "Periodo":
        if self.mes is None:
            return Periodo(self.ano + 1, None)
        return Periodo(self.ano + (self.mes == 12), 1 if self.mes == 12 else self.mes + 1)


def do_pedido(request, hoje: date | None = None) -> Periodo:
    hoje = hoje or timezone.localdate()
    if request.GET.get("periodo") == "ano":
        pedido = request.GET.get("ano", "")
        return Periodo(int(pedido) if pedido.isdigit() and 2000 <= int(pedido) <= 2100 else hoje.year, None)
    try:
        ano, mes = (int(parte) for parte in request.GET.get("mes", "").split("-"))
        date(ano, mes, 1)
        return Periodo(ano, mes)
    except ValueError:
        return Periodo(hoje.year, hoje.month)


def contexto_do_seletor(request, hoje: date | None = None) -> dict:
    """O que `indicadores/_periodo.html` precisa. Guarda os outros parâmetros da URL — filtro, busca, página.

    Sem isso, escolher "ano" na lista de pacientes jogaria fora o "encerrados" que estava aplicado.
    """
    hoje = hoje or timezone.localdate()
    periodo = do_pedido(request, hoje)
    outros = request.GET.copy()
    for chave in ("mes", "periodo", "ano", "page"):
        outros.pop(chave, None)
    resto = outros.urlencode()
    return {
        "periodo": periodo,
        "este_mes": Periodo(hoje.year, hoje.month),
        "este_ano": Periodo(hoje.year, None),
        "periodo_anterior": periodo.anterior(),
        "periodo_proximo": periodo.proximo(),
        "outros_parametros": f"&{resto}" if resto else "",
    }
