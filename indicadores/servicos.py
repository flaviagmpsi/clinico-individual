"""O painel (ADR-027, ADR-061, ADR-069): a agenda de hoje, o que ficou para trás e os números do mês.

O painel responde **"o que eu faço agora"**; a agenda responde "como está a minha semana". Por isso aqui
vêm as sessões de hoje em ordem de horário, e logo acima o que passou sem cadastro — que é justamente o
que trava cobrança e prontuário.

Tudo é derivado — de consultas, frequências, condições de cobrança e pagamentos. Nada aqui grava.
`indicadores` depende de todos os apps, e nenhum depende dele (regra 2 de dependência).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Max
from django.utils import timezone

from agenda.models import Recorrencia
from atendimentos.models import Consulta
from atendimentos.servicos import sessoes_pendentes, sessoes_previstas, sessoes_remarcadas
from financeiro.servicos import cobrancas_do_mes, pagamentos_pendentes, ultimo_dia
from pacientes.models import Caso, CondicaoCobranca, Paciente
from pacientes.servicos import casos_encerrados, pacientes_ativos
from prontuarios.servicos import prontuarios_pendentes

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
class ItemDoDia:
    """Uma sessão de hoje: a que já foi cadastrada, a que a frequência prevê, a que foi remarcada para cá.

    Os avisos que a linha carrega são os que mudam o que o psicólogo faz agora — dinheiro em aberto e
    prontuário por escrever. "Dias sem sessão" não está aqui de propósito (ADR-069): com a sessão sempre
    cadastrada, esse número já é a própria agenda; ele vira alerta só quando o ritmo se perde.
    """

    inicio: datetime
    caso: Caso
    modalidade: str
    situacao: str
    consulta: Consulta | None = None
    espera: object | None = None
    pagamento_em_aberto: bool = False
    prontuario_pendente: bool = False

    @property
    def cadastrada(self) -> bool:
        return self.consulta is not None

    @property
    def online(self) -> bool:
        return self.modalidade == Paciente.Modalidade.ONLINE


@dataclass
class Alerta:
    """Atendimento em curso que passou do próprio ritmo sem nenhuma sessão realizada (ADR-069)."""

    caso: Caso
    dias: int
    frequencia: str


@dataclass
class Painel:
    hoje: date
    mes: date
    resumo: Resumo
    hoje_itens: list
    atrasadas: list
    alertas: list
    pagamentos_pendentes: list
    prontuarios_pendentes: list = field(default_factory=list)


def _itens_de_hoje(agora: datetime, hoje: date, pendentes_de_cadastro: list,
                   casos_devendo: set, consultas_sem_prontuario: set) -> list[ItemDoDia]:
    """As sessões de hoje: as cadastradas, as previstas pela frequência e as remarcadas para cá."""
    itens = []
    cadastradas = (
        Consulta.objects.filter(inicio__gte=_meia_noite(hoje), inicio__lt=_meia_noite(hoje + timedelta(days=1)))
        .select_related("caso").prefetch_related("caso__pacientes")
    )
    for consulta in cadastradas:
        itens.append(ItemDoDia(
            inicio=consulta.inicio, caso=consulta.caso, modalidade=consulta.modalidade,
            situacao=consulta.get_estado_display(), consulta=consulta,
            pagamento_em_aberto=consulta.caso_id in casos_devendo,
            prontuario_pendente=consulta.pk in consultas_sem_prontuario))

    esperadas = sessoes_previstas(hoje, hoje) + sessoes_remarcadas(hoje, hoje)
    for sessao in esperadas:
        itens.append(ItemDoDia(
            inicio=sessao.inicio, caso=sessao.caso, modalidade=sessao.modalidade,
            situacao="a cadastrar" if sessao.pendente(agora) else "prevista", espera=sessao,
            pagamento_em_aberto=sessao.caso.pk in casos_devendo))
    return sorted(itens, key=lambda item: item.inicio)


def _alertas(hoje: date, em_curso, ultima_por_caso: dict) -> list[Alerta]:
    """Quem passou do próprio ritmo sem sessão realizada. Avulso não tem ritmo e não entra (ADR-061)."""
    alertas = []
    for caso in em_curso:
        regra = caso.regra_aberta()
        if regra is None:
            continue
        ultima = ultima_por_caso.get(caso.pk)
        desde = timezone.localtime(ultima).date() if ultima else regra.inicio
        dias = (hoje - desde).days
        if dias > LIMITE_DE_DIAS_SEM_SESSAO[regra.frequencia]:
            alertas.append(Alerta(caso=caso, dias=dias, frequencia=regra.get_frequencia_display()))
    return sorted(alertas, key=lambda alerta: -alerta.dias)


def montar_painel(agora: datetime | None = None) -> Painel:
    agora = agora or timezone.now()
    hoje = timezone.localdate(agora)
    inicio, fim = date(hoje.year, hoje.month, 1), ultimo_dia(hoje.year, hoje.month)

    cobrancas = cobrancas_do_mes(hoje.year, hoje.month)
    pendentes_de_cadastro = sessoes_pendentes(agora)
    pendentes_de_pagamento = pagamentos_pendentes(hoje)
    pendentes_de_prontuario = prontuarios_pendentes()
    # Só as futuras: a pendente de cadastro tem o seu próprio lugar no painel e não é previsão (ADR-061).
    futuras = [sessao for sessao in sessoes_previstas(hoje, fim) if not sessao.pendente(agora)]

    realizadas = Consulta.objects.filter(estado=Consulta.Estado.REALIZADA)
    no_mes = realizadas.filter(inicio__gte=_meia_noite(inicio), inicio__lt=_meia_noite(fim + timedelta(days=1)))
    ultima_por_caso = dict(realizadas.values("caso").annotate(ultima=Max("inicio")).values_list("caso", "ultima"))

    previsto_por_sessao = Decimal("0")
    for sessao in futuras:
        condicao = sessao.caso.condicao_vigente(sessao.data)
        if condicao is not None and condicao.modalidade == CondicaoCobranca.Modalidade.POR_SESSAO:
            previsto_por_sessao += condicao.valor

    casos_devendo = {cobranca.caso.pk for cobranca in pendentes_de_pagamento}
    consultas_sem_prontuario = {registro.consulta.pk for registro in pendentes_de_prontuario}
    em_curso = list(Caso.objects.exclude(pk__in=casos_encerrados().values("pk")).prefetch_related("pacientes"))

    itens = _itens_de_hoje(agora, hoje, pendentes_de_cadastro, casos_devendo, consultas_sem_prontuario)
    # O que ficou para trás: a pendência de hoje já aparece na agenda do dia, e repeti-la seria ruído.
    atrasadas = [sessao for sessao in pendentes_de_cadastro
                 if timezone.localtime(sessao.inicio).date() < hoje]
    alertas = _alertas(hoje, em_curso, ultima_por_caso)

    precisam_de_atencao = len({sessao.caso.pk for sessao in atrasadas} | casos_devendo
                              | {alerta.caso.pk for alerta in alertas})
    resumo = Resumo(
        sessoes_feitas=no_mes.count(),
        sessoes_faltam=len(futuras),
        recebido=sum((cobranca.pago for cobranca in cobrancas), Decimal("0")),
        a_receber=sum((cobranca.saldo for cobranca in cobrancas), Decimal("0")) + previsto_por_sessao,
        pacientes_ativos=pacientes_ativos().count(),
        precisam_de_atencao=precisam_de_atencao,
    )
    return Painel(hoje=hoje, mes=inicio, resumo=resumo, hoje_itens=itens, atrasadas=atrasadas, alertas=alertas,
                  pagamentos_pendentes=pendentes_de_pagamento, prontuarios_pendentes=pendentes_de_prontuario)
