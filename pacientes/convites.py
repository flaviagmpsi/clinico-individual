"""Convite de cadastro: o paciente preenche os próprios dados por um link (ADR-081).

Dois lados, com papéis de banco diferentes:

- **O psicólogo** (autenticado, `hamilton_app`, no escopo dele) gera o link, acompanha, revisa a resposta e a
  transforma em paciente.
- **O visitante** (anônimo, `hamilton_web`) apresenta o token, vê o nome de quem o convidou e responde **uma vez**.
  Ele nunca toca tabela clínica: a resposta fica no próprio convite, esperando a revisão.
"""

import hashlib
import secrets
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core import db
from pacientes.models import Caso, ConviteDeCadastro, Paciente, ResponsavelLegal

VALIDADE = timedelta(days=7)

# O que das respostas cai direto num campo do paciente. O resto — responsável, pagador, contatos de emergência —
# tem destino próprio.
CAMPOS_DO_PACIENTE = (
    "nome", "nome_social", "raca_cor", "cpf", "documento_estrangeiro", "data_nascimento", "estado_civil",
    "telefone", "email", "pais", "cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf",
    "estado_exterior", "genero", "profissao", "medicamento",
)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- O lado do psicólogo -------------------------------------------------------------------------------------------

def gerar_convite(rotulo: str = "", agora=None) -> tuple[ConviteDeCadastro, str]:
    """Cria o convite e devolve o token **em claro, esta única vez**: no banco fica só o hash."""
    token = secrets.token_urlsafe(32)
    convite = ConviteDeCadastro.objects.create(
        token_hash=_hash(token), rotulo=rotulo.strip(), expira_em=(agora or timezone.now()) + VALIDADE)
    return convite, token


def convites() -> list[ConviteDeCadastro]:
    """Os do psicólogo corrente: primeiro o que espera revisão, depois o resto, do mais novo para o mais antigo."""
    todos = list(ConviteDeCadastro.objects.select_related("paciente")[:100])
    ordem = {"respondido": 0, "aguardando": 1, "expirado": 2, "cadastrado": 3}
    return sorted(todos, key=lambda convite: ordem[convite.situacao])


def esperando_revisao() -> int:
    return ConviteDeCadastro.objects.filter(respondido_em__isnull=False, aceito_em__isnull=True).count()


def cancelar(convite: ConviteDeCadastro) -> None:
    """Apaga o convite — e, com ele, o que o paciente tiver respondido. Convite que já virou paciente fica."""
    if convite.aceito_em is not None:
        raise ValidationError("Este convite já virou cadastro.")
    convite.delete()


def iniciais_do_paciente(convite: ConviteDeCadastro) -> dict:
    """As respostas no formato do formulário de paciente do psicólogo, para ele revisar antes de salvar."""
    respostas = convite.respostas or {}
    iniciais = {campo: respostas[campo] for campo in CAMPOS_DO_PACIENTE if respostas.get(campo)}
    for posicao, contato in enumerate(respostas.get("contatos_de_emergencia", [])[:2], start=1):
        for campo in ("nome", "parentesco", "telefone"):
            iniciais[f"emergencia{posicao}_{campo}"] = contato.get(campo, "")
    return iniciais


@transaction.atomic
def aceitar(convite: ConviteDeCadastro, paciente: Paciente, agora=None) -> None:
    """Depois de o psicólogo salvar o paciente revisado: cria o que veio junto, e esvazia a sala de espera.

    O paciente e os contatos de emergência já foram gravados pelo formulário. Aqui entram o **responsável legal**
    (cadastro de criança ou adolescente) e o **responsável financeiro**, que têm model próprio. No fim, as
    respostas são apagadas do convite: o dado passa a existir num lugar só, o cadastro.
    """
    if convite.aceito_em is not None:
        raise ValidationError("Este convite já virou cadastro.")
    respostas = convite.respostas or {}
    responsavel = respostas.get("responsavel") or {}
    if responsavel.get("nome"):
        ResponsavelLegal.objects.create(
            paciente=paciente, nome=responsavel["nome"], parentesco=responsavel.get("parentesco", ""),
            cpf=responsavel.get("cpf", ""), telefone=responsavel.get("telefone", ""),
            email=responsavel.get("email", ""))
    pagador = respostas.get("pagador") or {}
    if pagador.get("nome"):
        caso = Caso.objects.filter(participacoes__paciente=paciente).first()
        if caso is not None:
            caso.pagador_paciente = None
            caso.pagador_nome = pagador["nome"]
            caso.pagador_cpf = pagador.get("cpf", "")
            caso.save()
    convite.paciente = paciente
    convite.aceito_em = agora or timezone.now()
    convite.respostas = {}
    convite.save()


# --- O lado do visitante (anônimo, sob `hamilton_web`) ---------------------------------------------------------------

def apresentar(token: str) -> ConviteDeCadastro | None:
    """O convite deste token, ou `None`. Diz o hash ao banco antes de perguntar: sem isso, o RLS não devolve nada."""
    token_hash = _hash(token)
    db.aplicar_convite(token_hash)
    return (ConviteDeCadastro.objetos_todos.select_related("psicologo")
            .filter(token_hash=token_hash).first())


def responder(convite: ConviteDeCadastro, respostas: dict, agora=None) -> bool:
    """Grava a resposta, **uma vez**. Devolve `False` se o convite já tinha sido respondido ou expirou.

    `update()` condicional, e não `save()`: a condição vai no próprio `UPDATE`, então dois envios ao mesmo tempo não
    passam os dois — e o visitante, que não tem escopo de psicólogo, não passa pelo `save()` do `TenantOwnedModel`.
    """
    agora = agora or timezone.now()
    gravados = (ConviteDeCadastro.objetos_todos
                .filter(pk=convite.pk, respondido_em__isnull=True, aceito_em__isnull=True, expira_em__gt=agora)
                .update(respostas=respostas, respondido_em=agora, atualizado_em=agora))
    return gravados == 1


def idade_em(nascimento: date, hoje: date | None = None) -> int:
    hoje = hoje or timezone.localdate()
    return hoje.year - nascimento.year - ((hoje.month, hoje.day) < (nascimento.month, nascimento.day))
