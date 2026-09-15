"""Os números do painel (ADR-027, ADR-061): sessões, receita e situação de cada atendimento no mês.

Tudo é derivado — de consultas, frequências, condições de cobrança e pagamentos. Nada aqui grava.
`indicadores` depende de todos os apps, e nenhum depende dele (regra 2 de dependência).
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Max
from django.utils import timezone

from agenda.models import Recorrencia
from atendimentos.models import Consulta
from atendimentos.servicos import sessoes_pendentes, sessoes_previstas
from financeiro.servicos import cobrancas_do_mes, pagamentos_pendentes, ultimo_dia
from pacientes.models import Caso, CondicaoCobranca
from pacientes.servicos import casos_encerrados, pacientes_ativos

# ADR-061: mais que isso sem sessão realizada é "precisa de atenção". Avulso não tem ritmo e não entra.
LIMITE_DE_DIAS_SEM_SESSAO = {Recorrencia.Frequencia.SEMANAL: 14, Recorrencia.Frequencia.QUINZENAL: 21}


def _meia_noite(dia: date) -> datetime:
    return timezone.make_aware(datetime.combine(dia, time.min))


@dataclass
class Resumo:
    sessoes_feitas: int
    sessoes_faltam: int
    recebido: Decimal
    a_receber: Decimal
    pacientes_ativos: int
    precisam_de_atencao: int


@dataclass
class Linha:
    """Um atendimento em curso: como está, há quanto tempo sem sessão e como está o financeiro do mês."""

    caso: Caso
    sessoes_no_mes: int
    dias_sem_sessao: int | None
    devido: Decimal
    pago: Decimal
    vencido: bool
    formas: list = field(default_factory=list)
    motivos: list = field(default_factory=list)

    @property
    def atencao(self) -> bool:
        return bool(self.motivos)

    @property
    def situacao_financeira(self) -> str:
        if not self.devido and not self.pago:
            return "sem cobrança"
        if self.pago >= self.devido:
            return "pago"
        return "pendente" if self.vencido else "a vencer"


@dataclass
class Painel:
    hoje: date
    mes: date
    resumo: Resumo
    linhas: list
    sessoes_pendentes: list
    pagamentos_pendentes: list


def montar_painel(agora: datetime | None = None) -> Painel:
    agora = agora or timezone.now()
    hoje = timezone.localdate(agora)
    inicio, fim = date(hoje.year, hoje.month, 1), ultimo_dia(hoje.year, hoje.month)

    cobrancas = cobrancas_do_mes(hoje.year, hoje.month)
    pendentes_de_cadastro = sessoes_pendentes(agora)
    pendentes_de_pagamento = pagamentos_pendentes(hoje)
    # Só as futuras: a pendente de cadastro tem o seu próprio aviso e não é previsão (ADR-061).
    futuras = [sessao for sessao in sessoes_previstas(hoje, fim) if not sessao.pendente(agora)]

    realizadas = Consulta.objects.filter(estado=Consulta.Estado.REALIZADA)
    no_mes = realizadas.filter(inicio__gte=_meia_noite(inicio), inicio__lt=_meia_noite(fim + timedelta(days=1)))
    sessoes_por_caso = Counter(no_mes.values_list("caso_id", flat=True))
    ultima_por_caso = dict(realizadas.values("caso").annotate(ultima=Max("inicio")).values_list("caso", "ultima"))

    previsto_por_sessao = Decimal("0")
    for sessao in futuras:
        condicao = sessao.caso.condicao_vigente(sessao.data)
        if condicao is not None and condicao.modalidade == CondicaoCobranca.Modalidade.POR_SESSAO:
            previsto_por_sessao += condicao.valor

    casos_com_pagamento_vencido = {cobranca.caso.pk for cobranca in pendentes_de_pagamento}
    casos_com_sessao_pendente = {sessao.caso.pk for sessao in pendentes_de_cadastro}

    linhas = []
    em_curso = Caso.objects.exclude(pk__in=casos_encerrados().values("pk")).prefetch_related("pacientes")
    for caso in em_curso:
        do_caso = [cobranca for cobranca in cobrancas if cobranca.caso.pk == caso.pk]
        ultima = ultima_por_caso.get(caso.pk)
        ultima_data = timezone.localtime(ultima).date() if ultima else None

        motivos = []
        if caso.pk in casos_com_pagamento_vencido:
            motivos.append("pagamento vencido")
        if caso.pk in casos_com_sessao_pendente:
            motivos.append("sessão pendente de cadastro")
        regra = caso.regra_aberta()
        if regra is not None:
            sem_sessao = (hoje - (ultima_data or regra.inicio)).days
            if sem_sessao > LIMITE_DE_DIAS_SEM_SESSAO[regra.frequencia]:
                motivos.append(f"{sem_sessao} dias sem sessão")

        linhas.append(Linha(
            caso=caso,
            sessoes_no_mes=sessoes_por_caso.get(caso.pk, 0),
            dias_sem_sessao=(hoje - ultima_data).days if ultima_data else None,
            devido=sum((cobranca.devido for cobranca in do_caso), Decimal("0")),
            pago=sum((cobranca.pago for cobranca in do_caso), Decimal("0")),
            vencido=any(cobranca.pendente(hoje) for cobranca in do_caso),
            formas=sorted({forma for cobranca in do_caso for forma in cobranca.formas}),
            motivos=motivos,
        ))
    linhas.sort(key=lambda linha: (not linha.atencao, str(linha.caso)))

    resumo = Resumo(
        sessoes_feitas=no_mes.count(),
        sessoes_faltam=len(futuras),
        recebido=sum((cobranca.pago for cobranca in cobrancas), Decimal("0")),
        a_receber=sum((cobranca.saldo for cobranca in cobrancas), Decimal("0")) + previsto_por_sessao,
        pacientes_ativos=pacientes_ativos().count(),
        precisam_de_atencao=sum(1 for linha in linhas if linha.atencao),
    )
    return Painel(hoje=hoje, mes=inicio, resumo=resumo, linhas=linhas,
                  sessoes_pendentes=pendentes_de_cadastro, pagamentos_pendentes=pendentes_de_pagamento)
