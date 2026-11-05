"""O motor dos lembretes (ADR-144): o cron chama, ele decide quem está na hora e envia pelo adaptador.

Roda **fora** do ciclo de requisição de um usuário — a rota do cron é anônima. Então ele mesmo faz a ponte que o
middleware faz para uma requisição autenticada: lê a lista de psicólogos como `hamilton_web` (o único papel que
enxerga a tabela de login sem escopo), desce para `hamilton_app` e, por psicólogo, define o escopo no Python
(`contexto`) e no Postgres (`db.aplicar_escopo`) — as três camadas da ADR-001. Exige uma transação aberta: a rota
a tem pelo middleware; o comando a abre com `transaction.atomic`.

Idempotente (RF08): antes de enviar confere o `LembreteEnviado`; depois de enviar, registra. Em modo simulado o
adaptador não toca a Meta — ainda assim registramos, para o cron não ficar "reenviando" a cada 15 minutos.
"""

import hashlib
import logging
from collections import namedtuple
from datetime import datetime, time, timedelta

from django.conf import settings
from django.utils import timezone

from atendimentos.models import Consulta
from atendimentos.servicos import sessoes_previstas
from contas.models import Psicologo
from core import contexto, db
from financeiro.servicos import cobrancas_em_aberto
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
    contagem = {"agenda_do_dia": 0, "pendencias_da_semana": 0, "lembrete_compromisso": 0, "aviso_pagamento": 0}
    for psicologo in psicologos:
        contexto.definir(psicologo.pk)
        db.aplicar_escopo(psicologo.pk)
        try:
            if _agenda_da_manha(psicologo, agora):
                contagem["agenda_do_dia"] += 1
            if _pendencias_da_semana(psicologo, agora):
                contagem["pendencias_da_semana"] += 1
            contagem["lembrete_compromisso"] += _lembretes_de_sessao(psicologo, agora)
            contagem["aviso_pagamento"] += _avisos_de_pagamento(psicologo, agora)
        finally:
            contexto.definir(None)
    return contagem


def _primeiro_nome(psicologo) -> str:
    return (psicologo.nome_completo or psicologo.email).split()[0]


def _ja_saiu(assunto: str) -> bool:
    return LembreteEnviado.objects.filter(assunto=assunto).exists()


def _registrar(assunto: str, envio: meta.Envio) -> None:
    LembreteEnviado.objects.get_or_create(
        assunto=assunto, defaults={"simulado": envio.simulado, "wamid": envio.id_mensagem or ""})


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


# ── A resposta do paciente (RF11, RF12) ─────────────────────────────────────────────────────────────────────────
#
# O paciente clica [Sim]/[Não] no `lembrete_compromisso`. A Meta chama o webhook, que corre anônimo (`hamilton_web`).
# A resposta volta com `context.id` = o `wamid` da mensagem que enviamos — é a chave que liga o clique de volta à
# sessão e, por ela, ao psicólogo dono. Como `wamid` é único no mundo, só um tenant tem aquele `LembreteEnviado`:
# descemos psicólogo a psicólogo (a mesma ponte do cron) e paramos no que reconhece a mensagem.
#
# RF12: a resposta **não cria nem altera** consulta, presença ou cobrança (ADR-060). Só avisa o psicólogo e agradece
# ao paciente. Nada clínico sai: ao psicólogo, primeiro nome + a hora; ao paciente, texto fixo de cortesia.

_Resposta = namedtuple("_Resposta", "context_id de confirmou")

_AGRADECE = "Agradecemos sua confirmação!"
_REMARCAR = ("Obrigado por nos informar, seu/sua psicólogo(a) irá entrar em contato com você para uma "
             "possível remarcação.")


def processar_webhook(payload: dict) -> dict:
    """Lê o que a Meta mandou e responde a cada Sim/Não. Idempotente — a Meta reenvia até receber 200.

    **Precisa de uma transação aberta** (a view anônima a tem pelo middleware), como o `disparar`."""
    respostas = [r for r in _respostas_do_payload(payload) if r.context_id]
    resultado = {"confirmou": 0, "nao_vem": 0, "ignoradas": 0}
    if not respostas:
        return resultado
    psicologos = list(Psicologo.objects.all())  # como `hamilton_web`: a lista de tenants sai daqui
    db.assumir_papel_da_aplicacao()
    for psicologo in psicologos:
        if not respostas:
            break
        contexto.definir(psicologo.pk)
        db.aplicar_escopo(psicologo.pk)
        try:
            respostas = [r for r in respostas if not _resolver(psicologo, r, resultado)]
        finally:
            contexto.definir(None)
    resultado["ignoradas"] = len(respostas)
    return resultado


def _respostas_do_payload(payload: dict):
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            valor = change.get("value") or {}
            numero = (valor.get("metadata") or {}).get("phone_number_id", "")
            # Confere que a mensagem chegou no **nosso** número. Em dev/simulado o id não está configurado — aí não há
            # o que conferir e seguimos (nenhum envio real acontece de qualquer modo).
            if settings.WHATSAPP_PHONE_NUMBER_ID and numero != settings.WHATSAPP_PHONE_NUMBER_ID:
                continue
            for mensagem in valor.get("messages") or []:
                resposta = _extrair(mensagem)
                if resposta:
                    yield resposta


def _extrair(mensagem: dict) -> _Resposta | None:
    """Tira da mensagem a resposta de botão. `None` para qualquer outra coisa (texto solto, mídia, status)."""
    context_id = (mensagem.get("context") or {}).get("id", "")
    de = mensagem.get("from", "")
    tipo = mensagem.get("type")
    if tipo == "button":
        rotulo = (mensagem.get("button") or {}).get("text", "")
    elif tipo == "interactive":
        rotulo = ((mensagem.get("interactive") or {}).get("button_reply") or {}).get("title", "")
    else:
        return None
    confirmou = _e_sim(rotulo)
    if confirmou is None:
        return None
    return _Resposta(context_id=context_id, de=de, confirmou=confirmou)


def _e_sim(rotulo: str) -> bool | None:
    """Os botões do modelo são **Sim**/**Não**. True para sim, False para não, `None` se não reconhecer."""
    texto = (rotulo or "").strip().lower()
    if texto.startswith("sim"):
        return True
    if texto.startswith("n"):  # "não"/"nao"
        return False
    return None


def _resolver(psicologo, resposta: _Resposta, resultado: dict) -> bool:
    """Tenta tratar a resposta neste tenant. True se a mensagem é daqui (tratada ou já tratada antes)."""
    lembrete = LembreteEnviado.objects.filter(wamid=resposta.context_id).first()
    if lembrete is None:
        return False  # não é deste psicólogo — tenta o próximo
    chave = f"resposta:{hashlib.sha1(resposta.context_id.encode()).hexdigest()[:24]}"
    if _ja_saiu(chave):
        return True  # a Meta reenviou; já respondemos
    paciente = _paciente_do_assunto(lembrete.assunto)
    if paciente is None:
        return True
    if paciente.telefone and resposta.de and not meta.mesmo_numero(resposta.de, paciente.telefone):
        # Não deveria acontecer — o `wamid` já identifica a mensagem com exatidão. Fica como diagnóstico, tolerante
        # ao 9º dígito para não disparar alarme falso por formatação (RF16). Seguimos: o `wamid` é a verdade.
        logger.warning("resposta de %s não casa com o telefone do paciente %s", resposta.de, paciente.pk)
    hora = _hora_do_assunto(lembrete.assunto)
    primeiro = _primeiro_nome_de(paciente)
    avisar = psicologo.whatsapp_ligado and psicologo.whatsapp_confirmacoes
    if resposta.confirmou:
        if avisar:
            meta.enviar_modelo(psicologo.telefone, "paciente_confirmou", [primeiro, hora])
        meta.enviar_texto(paciente.telefone, _AGRADECE)
        resultado["confirmou"] += 1
    else:
        if avisar:
            meta.enviar_modelo(psicologo.telefone, "paciente_nao_vem", [primeiro, hora])
        meta.enviar_texto(paciente.telefone, _REMARCAR)
        resultado["nao_vem"] += 1
    _registrar(chave, meta.Envio(ok=True, simulado=settings.WHATSAPP_SIMULADO))
    return True


def _paciente_do_assunto(assunto: str):
    """O paciente que gerou o lembrete, a partir do assunto `sessao:{pk}:{carimbo}`."""
    partes = assunto.split(":")
    if len(partes) >= 2 and partes[0] == "sessao" and partes[1].isdigit():
        return Paciente.objects.filter(pk=int(partes[1])).first()
    return None


def _hora_do_assunto(assunto: str) -> str:
    """A hora da sessão (HH:MM) a partir do carimbo `YYYYMMDDHHMM` no assunto. Vazia se não der para ler."""
    partes = assunto.split(":")
    carimbo = partes[2] if len(partes) >= 3 else ""
    return f"{carimbo[8:10]}:{carimbo[10:12]}" if len(carimbo) >= 12 else ""


def _avisos_de_pagamento(psicologo, agora) -> int:
    """Aviso ao paciente no dia do vencimento de uma cobrança em aberto (RF13), identificando o psicólogo.

    Só no **dia do vencimento** (não retroativo, não antecipado) e só de cobrança ainda em aberto. Cada paciente do
    caso com **opt-in de aviso, consentimento e telefone** recebe; idempotente por cobrança e paciente — o cron
    roda a cada ~15 min e não repete. Nada clínico sai: só o primeiro nome do paciente, o nome do psicólogo e a data.
    """
    hoje = timezone.localdate(agora)
    enviados = 0
    for cobranca in cobrancas_em_aberto(hoje):
        if cobranca.vencimento != hoje:
            continue
        chave = f"mensalidade:{cobranca.mes:%Y%m}" if cobranca.e_mensalidade else f"sessao:{cobranca.consulta.pk}"
        for paciente in cobranca.caso.pacientes.all():
            if not (paciente.whatsapp_aviso_pagamento and paciente.whatsapp_consentimento_em and paciente.telefone):
                continue
            assunto = f"pagamento:{chave}:{paciente.pk}"
            if _ja_saiu(assunto):
                continue
            envio = meta.enviar_modelo(paciente.telefone, "aviso_pagamento", [
                _primeiro_nome_de(paciente), psicologo.nome_completo, cobranca.vencimento.strftime("%d/%m")])
            if envio.ok:
                _registrar(assunto, envio)
                enviados += 1
    return enviados
