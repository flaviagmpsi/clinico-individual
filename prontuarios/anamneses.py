"""A anamnese por blocos (ADR-101): o roteiro do psicólogo e as respostas de cada paciente."""

from django.core.exceptions import ValidationError
from django.db import transaction

from core import auditoria

from prontuarios.models import Anamnese, RespostaDeAnamnese, TemaDeAnamnese
from prontuarios.temas import TEMAS_SUGERIDOS


def roteiro(*, com_arquivados: bool = False):
    """Os temas do psicólogo, na ordem dele. Cria os sugeridos na primeira vez que alguém abre uma anamnese."""
    temas = TemaDeAnamnese.objects.all()
    if not temas.exists():
        criar_roteiro_sugerido()
        temas = TemaDeAnamnese.objects.all()
    return temas if com_arquivados else temas.filter(arquivado=False)


@transaction.atomic
def criar_roteiro_sugerido() -> list[TemaDeAnamnese]:
    return [
        TemaDeAnamnese.objects.create(titulo=titulo, ajuda=ajuda, ordem=(i + 1) * 10, origem=chave)
        for i, (chave, titulo, ajuda) in enumerate(TEMAS_SUGERIDOS)
    ]


def blocos(anamnese: Anamnese | None):
    """Os blocos a mostrar: o roteiro de hoje, mais os temas arquivados que este paciente já respondeu.

    Arquivar um tema tira-o das anamneses novas — não some o que já foi escrito em quem tem resposta nele.
    """
    atuais = list(roteiro())
    respostas = {r.tema_id: r for r in anamnese.respostas.select_related("tema")} if anamnese else {}
    for tema_id, resposta in respostas.items():
        if resposta.tema.arquivado and resposta.texto.strip():
            atuais.append(resposta.tema)
    atuais.sort(key=lambda t: (t.ordem, t.pk))
    return [(tema, respostas.get(tema.pk)) for tema in atuais]


@transaction.atomic
def salvar(paciente, textos: dict[int, str]) -> Anamnese | None:
    """Grava o que foi escrito. `textos` é {id do tema: texto}.

    Anamnese que ainda não existe e chega sem uma linha escrita **não é criada**: é o mesmo cuidado da ADR-085 —
    abrir a aba e sair não deve deixar registro clínico vazio para trás.
    """
    anamnese = Anamnese.objects.filter(paciente=paciente).first()
    escreveu = any((texto or "").strip() for texto in textos.values())
    criada = anamnese is None
    if criada:
        if not escreveu:
            return None
        anamnese = Anamnese.objects.create(paciente=paciente)

    existentes = {r.tema_id: r for r in anamnese.respostas.select_related("tema")}
    mexidos = []
    for tema_id, texto in textos.items():
        texto = (texto or "").strip()
        resposta = existentes.get(tema_id)
        if resposta is None:
            if texto:
                nova = RespostaDeAnamnese.objects.create(anamnese=anamnese, tema_id=tema_id, texto=texto)
                mexidos.append(nova.tema.titulo)
        elif resposta.texto != texto:
            resposta.texto = texto
            resposta.save()
            mexidos.append(resposta.tema.titulo)
    # A trilha continua acusando que a anamnese mudou, e **quais temas** — nunca o que foi escrito (ADR-085). O
    # texto mora na resposta, que não é auditada; sem esta linha, editar a anamnese não deixaria rastro nenhum.
    if mexidos and not criada:
        auditoria.registrar(auditoria.Acao.ALTERAR, anamnese, mexidos)
    return anamnese


@transaction.atomic
def criar_tema(titulo: str, ajuda: str = "") -> TemaDeAnamnese:
    """Um bloco novo, no fim do roteiro. Título repetido é recusado — inclusive o de um tema arquivado."""
    titulo = " ".join((titulo or "").split())
    if not titulo:
        raise ValidationError("Dê um nome ao tema.")
    if TemaDeAnamnese.objects.filter(titulo__iexact=titulo).exists():
        raise ValidationError(f"Você já tem um tema chamado “{titulo}”.")
    roteiro()  # garante o roteiro sugerido antes de acrescentar o primeiro tema próprio
    ultimo = TemaDeAnamnese.objects.order_by("-ordem").first()
    return TemaDeAnamnese.objects.create(titulo=titulo, ajuda=ajuda.strip(),
                                         ordem=(ultimo.ordem if ultimo else 0) + 10)


def arquivar(tema: TemaDeAnamnese, *, arquivado: bool = True) -> TemaDeAnamnese:
    tema.arquivado = arquivado
    tema.save()
    return tema


@transaction.atomic
def mover(tema: TemaDeAnamnese, *, para_cima: bool) -> None:
    """Troca a ordem com o vizinho. A tela move um passo de cada vez, que é como se organiza uma lista curta."""
    vizinhos = TemaDeAnamnese.objects.filter(arquivado=False)
    vizinho = (vizinhos.filter(ordem__lt=tema.ordem).order_by("-ordem").first() if para_cima
               else vizinhos.filter(ordem__gt=tema.ordem).order_by("ordem").first())
    if vizinho is None:
        return
    tema.ordem, vizinho.ordem = vizinho.ordem, tema.ordem
    tema.save()
    vizinho.save()
