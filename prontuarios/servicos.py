"""Prontuário escrito à mão: o que está pendente, rascunho, confirmação e correção (ADR-064).

Tudo roda no escopo do psicólogo corrente. O que está **pendente** não é gravado: é a sessão realizada cujo
participante ainda não tem versão confirmada.
"""

from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from atendimentos.models import Consulta
from pacientes.models import Paciente
from prontuarios.models import Prontuario, VersaoProntuario


@dataclass
class Registro:
    """O prontuário de um participante numa sessão realizada — exista ele no banco ou não."""

    consulta: Consulta
    paciente: Paciente
    prontuario: Prontuario | None = None

    @property
    def versoes(self) -> list:
        return list(self.prontuario.versoes.all()) if self.prontuario else []

    @property
    def confirmadas(self) -> list:
        return [versao for versao in self.versoes if versao.confirmada_em is not None]

    @property
    def rascunho(self) -> VersaoProntuario | None:
        return next((versao for versao in self.versoes if versao.confirmada_em is None), None)

    @property
    def vigente(self) -> VersaoProntuario | None:
        confirmadas = self.confirmadas
        return confirmadas[-1] if confirmadas else None

    @property
    def pendente(self) -> bool:
        return not self.confirmadas

    @property
    def situacao(self) -> str:
        if not self.versoes:
            return "não escrito"
        if not self.confirmadas:
            return "rascunho"
        return "em correção" if self.rascunho else "confirmado"

    @property
    def url(self) -> str:
        return reverse("prontuarios:escrever", args=[self.consulta.pk, self.paciente.pk])


def registros(*, paciente: Paciente | None = None, somente_pendentes: bool = False) -> list[Registro]:
    """Um registro por participante de cada sessão realizada, da mais recente para a mais antiga."""
    consultas = (
        Consulta.objects.filter(estado=Consulta.Estado.REALIZADA)
        .select_related("caso").prefetch_related("caso__pacientes", "prontuarios__versoes")
        .order_by("-inicio")
    )
    if paciente is not None:
        consultas = consultas.filter(caso__participacoes__paciente=paciente)
    lista = []
    for consulta in consultas:
        por_paciente = {prontuario.paciente_id: prontuario for prontuario in consulta.prontuarios.all()}
        for participante in consulta.caso.pacientes.all():
            if paciente is not None and participante.pk != paciente.pk:
                continue
            registro = Registro(consulta, participante, por_paciente.get(participante.pk))
            if somente_pendentes and not registro.pendente:
                continue
            lista.append(registro)
    return lista


def prontuarios_pendentes() -> list[Registro]:
    return registros(somente_pendentes=True)


def registro_de(consulta: Consulta, paciente: Paciente) -> Registro:
    prontuario = Prontuario.objects.filter(consulta=consulta, paciente=paciente).prefetch_related("versoes").first()
    return Registro(consulta, paciente, prontuario)


@transaction.atomic
def salvar_rascunho(consulta: Consulta, paciente: Paciente, *, texto: str, motivo: str = "") -> VersaoProntuario:
    """Cria ou atualiza o rascunho. Havendo versão confirmada, o rascunho é uma correção e pede motivo."""
    prontuario = Prontuario.objects.filter(consulta=consulta, paciente=paciente).first()
    if prontuario is None:
        prontuario = Prontuario.objects.create(consulta=consulta, paciente=paciente)
    rascunho = prontuario.versoes.filter(confirmada_em__isnull=True).first()
    if rascunho is None:
        ultimo = prontuario.versoes.aggregate(maior=Max("numero"))["maior"] or 0
        rascunho = VersaoProntuario(prontuario=prontuario, numero=ultimo + 1)
    rascunho.texto = texto
    rascunho.motivo = motivo if rascunho.numero > 1 else ""
    rascunho.save()
    return rascunho


@transaction.atomic
def confirmar(consulta: Consulta, paciente: Paciente, *, texto: str, motivo: str = "",
              agora: datetime | None = None) -> VersaoProntuario:
    """Salva e confirma. Depois disto, a versão não muda mais (ADR-064)."""
    versao = salvar_rascunho(consulta, paciente, texto=texto, motivo=motivo)
    versao.confirmada_em = agora or timezone.now()
    versao.save()
    return versao


@transaction.atomic
def descartar_rascunho(consulta: Consulta, paciente: Paciente) -> None:
    """Joga fora o rascunho. Versão confirmada não é tocada; prontuário que fica sem versão nenhuma sai também."""
    prontuario = Prontuario.objects.filter(consulta=consulta, paciente=paciente).first()
    rascunho = prontuario.versoes.filter(confirmada_em__isnull=True).first() if prontuario else None
    if rascunho is None:
        raise ValidationError("Não há rascunho para descartar.")
    rascunho.delete()
    if not prontuario.versoes.exists():
        prontuario.delete()
