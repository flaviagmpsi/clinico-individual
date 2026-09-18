"""O painel (ADR-027, ADR-061, ADR-069, ADR-072): a agenda de hoje, as pendências e os números do mês.

O painel responde **"o que eu faço agora"** — e só isso. Três coisas, cada uma num lugar só (ADR-072):

- as **sessões de hoje**, em ordem de horário;
- as **pendências** — sessão que passou sem cadastro, pagamento vencido, prontuário por escrever;
- o **resumo do mês** — sessões, receita, pacientes ativos.

"Dias sem sessão" não existe mais (ADR-072): com a sessão sempre cadastrada, esse número já é a própria agenda.

Tudo é derivado — de consultas, frequências, condições de cobrança e pagamentos. Nada aqui grava.
`indicadores` depende de todos os apps, e nenhum depende dele (regra 2 de dependência).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

from atendimentos.models import Consulta
from atendimentos.servicos import sessoes_pendentes, sessoes_previstas, sessoes_remarcadas
from financeiro.despesas import previsto_por_mes
from financeiro.servicos import carregar, cobrancas_do_mes, pagamentos_pendentes, ultimo_dia
from pacientes.models import Paciente
from pacientes.servicos import pacientes_ativos
from prontuarios.servicos import prontuarios_pendentes


def _meia_noite(dia: date) -> datetime:
    return timezone.make_aware(datetime.combine(dia, time.min))


@dataclass
class Resumo:
    sessoes_feitas: int
    sessoes_faltam: int
    recebido: Decimal
    a_receber: Decimal
    pacientes_ativos: int


@dataclass
class ItemDoDia:
    """Uma sessão de hoje: a que já foi cadastrada, a que a frequência prevê, a que foi remarcada para cá.

    Só a agenda do dia. Os avisos moram no bloco de pendências, uma vez cada (ADR-072).
    """

    inicio: datetime
    caso: object
    modalidade: str
    situacao: str
    consulta: Consulta | None = None
    espera: object | None = None

    @property
    def cadastrada(self) -> bool:
        return self.consulta is not None

    @property
    def online(self) -> bool:
        return self.modalidade == Paciente.Modalidade.ONLINE


@dataclass
class Pendencias:
    """Tudo o que espera o psicólogo, num bloco só (ADR-072).

    `sessoes` são as de **dias anteriores**: a de hoje que já passou aparece na agenda do dia como
    "a cadastrar", e repeti-la aqui seria o ruído que a ADR-072 tira.
    """

    sessoes: list
    pagamentos: list
    prontuarios: list

    @property
    def total(self) -> int:
        return len(self.sessoes) + len(self.pagamentos) + len(self.prontuarios)


@dataclass
class Painel:
    hoje: date
    mes: date
    resumo: Resumo
    hoje_itens: list
    pendencias: Pendencias


def _itens_de_hoje(agora: datetime, hoje: date) -> list[ItemDoDia]:
    """As sessões de hoje: as cadastradas, as previstas pela frequência e as remarcadas para cá."""
    itens = []
    cadastradas = (
        Consulta.objects.filter(inicio__gte=_meia_noite(hoje), inicio__lt=_meia_noite(hoje + timedelta(days=1)))
        .select_related("caso").prefetch_related("caso__pacientes")
    )
    for consulta in cadastradas:
        itens.append(ItemDoDia(inicio=consulta.inicio, caso=consulta.caso, modalidade=consulta.modalidade,
                               situacao=consulta.get_estado_display(), consulta=consulta))
    for sessao in sessoes_previstas(hoje, hoje) + sessoes_remarcadas(hoje, hoje):
        itens.append(ItemDoDia(inicio=sessao.inicio, caso=sessao.caso, modalidade=sessao.modalidade,
                               situacao="a cadastrar" if sessao.pendente(agora) else "prevista", espera=sessao))
    return sorted(itens, key=lambda item: item.inicio)


def montar_painel(agora: datetime | None = None) -> Painel:
    agora = agora or timezone.now()
    hoje = timezone.localdate(agora)
    inicio, fim = date(hoje.year, hoje.month, 1), ultimo_dia(hoje.year, hoje.month)

    # Uma carga só para o mês (ADR-086): as cobranças e a previsão leem dela, e não do banco a cada item.
    carga = carregar(inicio, fim)
    cobrancas = cobrancas_do_mes(hoje.year, hoje.month, carga=carga)
    # Só as futuras: a que passou sem cadastro é pendência, não previsão (ADR-061).
    futuras = [sessao for sessao in sessoes_previstas(hoje, fim) if not sessao.pendente(agora)]
    previsto_por_sessao = previsto_por_mes(hoje, fim, agora, carga).get(inicio, Decimal("0"))

    feitas = Consulta.objects.filter(
        estado=Consulta.Estado.REALIZADA,
        inicio__gte=_meia_noite(inicio), inicio__lt=_meia_noite(fim + timedelta(days=1))).count()

    resumo = Resumo(
        sessoes_feitas=feitas,
        sessoes_faltam=len(futuras),
        recebido=sum((cobranca.pago for cobranca in cobrancas), Decimal("0")),
        a_receber=sum((cobranca.saldo for cobranca in cobrancas), Decimal("0")) + previsto_por_sessao,
        pacientes_ativos=pacientes_ativos().count(),
    )
    pendencias = Pendencias(
        sessoes=[s for s in sessoes_pendentes(agora) if timezone.localtime(s.inicio).date() < hoje],
        pagamentos=pagamentos_pendentes(hoje),
        prontuarios=prontuarios_pendentes(),
    )
    return Painel(hoje=hoje, mes=inicio, resumo=resumo, hoje_itens=_itens_de_hoje(agora, hoje),
                  pendencias=pendencias)
