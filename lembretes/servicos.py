"""O motor dos lembretes (ADR-144): o cron chama, ele decide quem está na hora e envia pelo adaptador.

Roda **fora** do ciclo de requisição de um usuário — a rota do cron é anônima. Então ele mesmo faz a ponte que o
middleware faz para uma requisição autenticada: lê a lista de psicólogos como `hamilton_web` (o único papel que
enxerga a tabela de login sem escopo), desce para `hamilton_app` e, por psicólogo, define o escopo no Python
(`contexto`) e no Postgres (`db.aplicar_escopo`) — as três camadas da ADR-001. Exige uma transação aberta: a rota
a tem pelo middleware; o comando a abre com `transaction.atomic`.

Idempotente (RF08): antes de enviar confere o `LembreteEnviado`; depois de enviar, registra. Em modo simulado o
adaptador não toca a Meta — ainda assim registramos, para o cron não ficar "reenviando" a cada 15 minutos.
"""

import logging
from datetime import datetime, time, timedelta

from django.utils import timezone

from atendimentos.models import Consulta
from atendimentos.servicos import sessoes_previstas
from contas.models import Psicologo
from core import contexto, db
from indicadores.servicos import montar_painel
from lembretes import meta
from lembretes.models import LembreteEnviado
from pacientes.models import Paciente

logger = logging.getLogger("lembretes")

# Quanto tempo depois do "momento do lembrete" o sistema ainda dispara, se o cron não tiver pego na hora exata. Cobre
# atrasos/hiccups do cron (que roda a cada ~15 min) sem reenviar (a idempotência garante uma vez só) e, de quebra,
# honra o "não envia retroativo" (ADR-144, RF09): sessão cuja hora de lembrete passou faz tempo não recebe nada.
_MARGEM_LEMBRETE = timedelta(hours=1)


def disparar(agora=None) -> dict:
    """Varre os psicólogos com WhatsApp ligado e envia o que está na hora. Devolve a contagem por tipo.

    **Precisa de uma transação aberta** (SET LOCAL ROLE e set_config só valem dentro de uma)."""
    agora = agora or timezone.now()
    # Lida como a superfície anônima: `hamilton_web` enxerga a tabela de login inteira; é daqui que sai a lista.
    psicologos = list(Psicologo.objects.filter(whatsapp_ligado=True))
    db.assumir_papel_da_aplicacao()  # a partir daqui o domínio é acessível, trancado pela variável de tenant
    contagem = {"agenda_do_dia": 0, "pendencias_da_semana": 0, "lembrete_compromisso": 0}
    for psicologo in psicologos:
        contexto.definir(psicologo.pk)
        db.aplicar_escopo(psicologo.pk)
        try:
            if _agenda_da_manha(psicologo, agora):
                contagem["agenda_do_dia"] += 1
            if _pendencias_da_semana(psicologo, agora):
                contagem["pendencias_da_semana"] += 1
            contagem["lembrete_compromisso"] += _lembretes_de_sessao(psicologo, agora)
        finally:
            contexto.definir(None)
    return contagem


def _primeiro_nome(psicologo) -> str:
    return (psicologo.nome_completo or psicologo.email).split()[0]


def _ja_saiu(assunto: str) -> bool:
    return LembreteEnviado.objects.filter(assunto=assunto).exists()


def _registrar(assunto: str, envio: meta.Envio) -> None:
    LembreteEnviado.objects.get_or_create(assunto=assunto, defaults={"simulado": envio.simulado})


def _agenda_da_manha(psicologo, agora) -> bool:
    """Resumo da agenda de hoje, uma vez por dia, a partir do horário configurado. Dia vazio não vira WhatsApp."""
    if not psicologo.whatsapp_agenda_manha:
        return False
    if timezone.localtime(agora).time() < psicologo.whatsapp_agenda_manha_hora:
        return False
    assunto = f"agenda_do_dia:{timezone.localdate(agora).isoformat()}"
    if _ja_saiu(assunto):
        return False
    painel = montar_painel(agora)
    if not painel.hoje_itens:
        return False
    primeiro = timezone.localtime(painel.hoje_itens[0].inicio).strftime("%H:%M")
    envio = meta.enviar_modelo(psicologo.telefone, "agenda_do_dia",
                               [_primeiro_nome(psicologo), len(painel.hoje_itens), primeiro])
    if envio.ok:
        _registrar(assunto, envio)
        return True
    logger.warning("agenda_do_dia não saiu para o psicólogo %s: %s", psicologo.pk, envio.erro)
    return False


def _pendencias_da_semana(psicologo, agora) -> bool:
    """Resumo das pendências, uma vez por semana, no dia e horário configurados. Semana limpa não vira WhatsApp."""
    if not psicologo.whatsapp_pendencias_semana:
        return False
    local = timezone.localtime(agora)
    if local.weekday() != psicologo.whatsapp_pendencias_dia or local.time() < psicologo.whatsapp_pendencias_hora:
        return False
    assunto = f"pendencias:{local.date().isoformat()}"
    if _ja_saiu(assunto):
        return False
    painel = montar_painel(agora)
    prontuarios = len(painel.pendencias.prontuarios)
    cobrancas = len(painel.pendencias.pagamentos) + len(painel.pendencias.pendentes)
    if not prontuarios and not cobrancas:
        return False
    envio = meta.enviar_modelo(psicologo.telefone, "pendencias_da_semana",
                               [_primeiro_nome(psicologo), prontuarios, cobrancas])
    if envio.ok:
        _registrar(assunto, envio)
        return True
    logger.warning("pendencias_da_semana não saiu para o psicólogo %s: %s", psicologo.pk, envio.erro)
    return False


def _primeiro_nome_de(paciente) -> str:
    return (paciente.nome_social or paciente.nome).split()[0]


def _meia_noite(dia):
    return timezone.make_aware(datetime.combine(dia, time.min))


def _lembretes_de_sessao(psicologo, agora) -> int:
    """Lembrete de confirmação ao paciente, X horas antes de cada sessão (RF07). Um por sessão (idempotente).

    As sessões vêm da frequência (`sessoes_previstas`) e das avulsas marcadas como futuras (estado AGENDADA). Cada
    participante do caso com **opt-in, consentimento e telefone** recebe (RF10). Dispara quando `agora` cai na janela
    do lembrete `[inicio - antecedência, + margem)` — o que também honra o "não retroativo" (RF09).
    """
    hoje = timezone.localdate(agora)
    fim = hoje + timedelta(days=8)  # cobre a maior antecedência (168h = 7 dias)
    ocorrencias = [(s.inicio, s.caso, s.modalidade) for s in sessoes_previstas(hoje, fim)]
    futuras = (Consulta.objects.filter(estado=Consulta.Estado.AGENDADA, inicio__gt=agora, inicio__lt=_meia_noite(fim))
               .select_related("caso").prefetch_related("caso__pacientes"))
    ocorrencias += [(c.inicio, c.caso, c.modalidade) for c in futuras]

    enviados = 0
    for inicio, caso, modalidade in ocorrencias:
        for paciente in caso.pacientes.all():
            if not (paciente.whatsapp_lembrete_sessao and paciente.whatsapp_consentimento_em and paciente.telefone):
                continue
            momento = inicio - timedelta(hours=paciente.whatsapp_antecedencia_horas)
            if not (momento <= agora < momento + _MARGEM_LEMBRETE and agora < inicio):
                continue
            assunto = f"sessao:{paciente.pk}:{timezone.localtime(inicio).strftime('%Y%m%d%H%M')}"
            if _ja_saiu(assunto):
                continue
            local = timezone.localtime(inicio)
            envio = meta.enviar_modelo(paciente.telefone, "lembrete_compromisso", [
                _primeiro_nome_de(paciente), psicologo.nome_completo,
                local.strftime("%d/%m"), local.strftime("%H:%M"),
                "online" if modalidade == Paciente.Modalidade.ONLINE else "presencialmente"])
            if envio.ok:
                _registrar(assunto, envio)
                enviados += 1
    return enviados
