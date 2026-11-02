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

from django.utils import timezone

from contas.models import Psicologo
from core import contexto, db
from indicadores.servicos import montar_painel
from lembretes import meta
from lembretes.models import LembreteEnviado

logger = logging.getLogger("lembretes")


def disparar(agora=None) -> dict:
    """Varre os psicólogos com WhatsApp ligado e envia o que está na hora. Devolve a contagem por tipo.

    **Precisa de uma transação aberta** (SET LOCAL ROLE e set_config só valem dentro de uma)."""
    agora = agora or timezone.now()
    # Lida como a superfície anônima: `hamilton_web` enxerga a tabela de login inteira; é daqui que sai a lista.
    psicologos = list(Psicologo.objects.filter(whatsapp_ligado=True))
    db.assumir_papel_da_aplicacao()  # a partir daqui o domínio é acessível, trancado pela variável de tenant
    contagem = {"agenda_do_dia": 0, "pendencias_da_semana": 0}
    for psicologo in psicologos:
        contexto.definir(psicologo.pk)
        db.aplicar_escopo(psicologo.pk)
        try:
            if _agenda_da_manha(psicologo, agora):
                contagem["agenda_do_dia"] += 1
            if _pendencias_da_semana(psicologo, agora):
                contagem["pendencias_da_semana"] += 1
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
