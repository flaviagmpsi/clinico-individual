"""Junta as peças da escrita assistida: quem anonimizar, o que a IA pode saber, e o que ela devolve (ADR-111).

Mora aqui, e não em `ia.py`, porque `ia.py` só sabe falar com a OpenAI — não conhece paciente, sessão nem
psicólogo. A separação é o que permite testar a anonimização e o contexto sem chamar a API, que é justamente o
que não se quer chamar num teste.
"""

from django.conf import settings
from django.utils import timezone

from atendimentos.models import Consulta
from contas import abordagens as catalogo
from pacientes.models import Paciente
from prontuarios import ia
from prontuarios.models import VersaoProntuario


def nomes_a_esconder(paciente: Paciente, psicologo=None) -> list[str]:
    """Todo nome de pessoa que o sistema conhece em volta deste atendimento.

    Vai tudo: o do paciente, o social, o de cada responsável legal e o do próprio psicólogo. O nome do
    profissional entra porque relato falado costuma dizer "eu, Ana, propus" — e num documento que a pessoa assina
    por fora, o nome dela no meio do texto é ruído, não informação.
    """
    nomes = [paciente.nome, paciente.nome_social]
    nomes += [responsavel.nome for responsavel in paciente.responsaveis.all()]
    if psicologo is not None:
        nomes.append(getattr(psicologo, "nome_completo", "") or "")
    return [nome for nome in nomes if (nome or "").strip()]


def contexto_da_sessao(consulta: Consulta, paciente: Paciente, psicologo=None) -> ia.Contexto:
    """O que a IA pode saber: como se trabalha, não com quem.

    Nada aqui identifica ninguém — é abordagem, modalidade, frequência e a contagem de sessões. A contagem entra
    porque "primeira sessão" e "vigésima" pedem registros de evolução diferentes.
    """
    abordagem = ""
    if psicologo is not None:
        abordagem = catalogo.descrever(getattr(psicologo, "abordagens", []) or [],
                                       catalogo.ROTULO_DA_ABORDAGEM,
                                       getattr(psicologo, "abordagem_outra", "") or "")
    recorrencia = consulta.caso.recorrencias.order_by("-inicio").first() if consulta.caso_id else None
    return ia.Contexto(
        abordagem=abordagem,
        modalidade=consulta.get_modalidade_display() if consulta.modalidade else "",
        frequencia=recorrencia.get_frequencia_display().lower() if recorrencia else "sem frequência fixa",
        numero_da_sessao=_quantas_sessoes_ate(consulta, paciente),
    )


def _quantas_sessoes_ate(consulta: Consulta, paciente: Paciente) -> int:
    """Em que número esta sessão está, contando as realizadas deste paciente até a data dela."""
    return Consulta.objects.filter(
        caso__participacoes__paciente=paciente,
        estado=Consulta.Estado.REALIZADA,
        inicio__lte=consulta.inicio,
    ).distinct().count()


def transcrever_sessao(audio, paciente: Paciente, psicologo=None, *, nome: str = "sessao.webm") -> str:
    """Áudio → texto **já sem os nomes que o sistema conhece**.

    A ordem importa: anonimiza logo depois de transcrever, e não na hora de sintetizar. Assim o texto que volta
    para a tela — e que o psicólogo pode revisar antes de gerar o registro — já está limpo.
    """
    bruto = ia.transcrever(audio, nome=nome)
    return ia.anonimizar(bruto, nomes=nomes_a_esconder(paciente, psicologo))


def redigir(relato: str, consulta: Consulta, paciente: Paciente, psicologo=None) -> str:
    """Relato → corpo do registro de evolução. Anonimiza de novo: o relato pode ter sido digitado à mão."""
    limpo = ia.anonimizar(relato, nomes=nomes_a_esconder(paciente, psicologo))
    return ia.sintetizar(limpo, contexto=contexto_da_sessao(consulta, paciente, psicologo))


def rodape_de_origem(agora=None) -> str:
    """A linha que marca o texto como rascunho de IA, enquanto ele não foi revisado e confirmado."""
    quando = (agora or timezone.localtime()).strftime("%d/%m/%Y às %H:%M")
    return f"\n\n— Rascunho gerado com apoio de IA em {quando}, a partir do relato do profissional. Revise antes de confirmar."


def quantas_sinteses_no_mes(agora=None) -> int:
    """Quantas sínteses esta conta já pediu no mês corrente.

    Conta pelas **versões de prontuário nascidas de IA**, e não por um contador próprio: contador é estado a
    mais para manter em sincronia, e esta é a mesma informação. Versão apagada deixa de contar, o que é justo —
    ela não existe mais.
    """
    agora = agora or timezone.localtime()
    return VersaoProntuario.objects.filter(
        origem=VersaoProntuario.Origem.IA,
        criado_em__year=agora.year,
        criado_em__month=agora.month,
    ).count()


def teto_do_mes() -> int:
    return int(getattr(settings, "IA_SINTESES_POR_MES", 0) or 0)


def passou_do_teto(agora=None) -> bool:
    teto = teto_do_mes()
    return bool(teto) and quantas_sinteses_no_mes(agora) >= teto
