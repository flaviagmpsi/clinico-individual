"""Calendário brasileiro para vencimentos: dia fixo, dia útil e feriados nacionais (ADR-063).

Não conhece domínio — responde perguntas de calendário. Vive em `core` porque `contas` (padrão do perfil) e
`pacientes` (vencimento de cada paciente) usam as mesmas escolhas, e nenhum dos dois pode depender do outro.

**Dia útil** é segunda a sexta, sem feriado nacional (decisão do usuário, Rodada 38). Feriado estadual e
municipal fica de fora: muda de cidade para cidade. Carnaval e Corpus Christi não entram — são ponto
facultativo, não feriado nacional.
"""

from calendar import monthrange
from datetime import date, timedelta
from functools import lru_cache

from django.db import models


class TipoDia(models.TextChoices):
    DIA_FIXO = "DIA_FIXO", "Dia fixo do mês"
    DIA_UTIL = "DIA_UTIL", "Dia útil do mês"


# Nenhum mês tem mais que 23 dias de segunda a sexta. "24º dia útil" não existe em mês nenhum.
MAIOR_DIA_UTIL = 23

# Lei nº 662/1949 e alterações. O 20 de novembro entra a partir de 2024 (Lei nº 14.759/2023).
_FERIADOS_FIXOS = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (12, 25)]


def pascoa(ano: int) -> date:
    """Domingo de Páscoa no calendário gregoriano (algoritmo de Meeus/Jones/Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 — nome do algoritmo publicado
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


@lru_cache(maxsize=64)
def feriados_nacionais(ano: int) -> frozenset[date]:
    fixos = list(_FERIADOS_FIXOS)
    if ano >= 2024:
        fixos.append((11, 20))
    sexta_feira_santa = pascoa(ano) - timedelta(days=2)
    return frozenset([date(ano, mes, dia) for mes, dia in fixos] + [sexta_feira_santa])


def dia_util(dia: date) -> bool:
    return dia.weekday() < 5 and dia not in feriados_nacionais(dia.year)


def dias_uteis(ano: int, mes: int) -> list[date]:
    return [dia for dia in (date(ano, mes, n) for n in range(1, monthrange(ano, mes)[1] + 1)) if dia_util(dia)]


def data_no_mes(tipo: str, numero: int, ano: int, mes: int) -> date:
    """O dia do mês que um vencimento indica.

    Número além do mês vira o último: dia 31 em fevereiro cai no último dia; 23º dia útil num mês com 20 cai
    no último dia útil. Assim nenhum vencimento some num mês curto.
    """
    if tipo == TipoDia.DIA_UTIL:
        uteis = dias_uteis(ano, mes)
        return uteis[min(numero, len(uteis)) - 1]
    return date(ano, mes, min(numero, monthrange(ano, mes)[1]))


def descrever_dia(tipo: str, numero: int) -> str:
    """"todo dia 10" ou "todo 5º dia útil"."""
    if tipo == TipoDia.DIA_UTIL:
        return f"todo {numero}º dia útil"
    return f"todo dia {numero}"
