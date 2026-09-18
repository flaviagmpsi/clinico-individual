"""Prontuário escrito à mão: o que está pendente, rascunho, confirmação e edição (ADR-064, ADR-075).

Tudo roda no escopo do psicólogo corrente. O que está **pendente** não é gravado: é a sessão realizada cujo
participante ainda não tem versão confirmada.
"""

from dataclasses import dataclass
from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from atendimentos.models import Consulta
from pacientes.models import Caso, Paciente
from prontuarios.models import FichaDoProntuario, Prontuario, VersaoProntuario


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
        return "em edição" if self.rascunho else "confirmado"

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
    """Cria ou atualiza o rascunho. Havendo versão confirmada, o rascunho é a edição dela — versão nova (ADR-075)."""
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



# --- O prontuário geral: as quatro partes da Res. CFP nº 001/2009 (ADR-079, ADR-080) ---------------------

@dataclass
class FolhaDoProntuario:
    """O prontuário inteiro de um paciente, na ordem em que a resolução o descreve."""

    paciente: Paciente
    ficha: FichaDoProntuario | None
    demanda: str
    demanda_sugerida: bool  # o texto veio do cadastro, e não de algo que o psicólogo já salvou
    encerramento: str
    encerramento_sugerido: bool
    evolucao: list  # `Registro`, da sessão mais antiga para a mais recente: prontuário se lê em ordem

    @property
    def sem_registro(self) -> int:
        return sum(1 for registro in self.evolucao if registro.vigente is None)


def ficha_de(paciente: Paciente) -> FichaDoProntuario | None:
    """A ficha que vale: a mais recente. As anteriores ficam guardadas."""
    return FichaDoProntuario.objects.filter(paciente=paciente).first()


def _casos(paciente: Paciente) -> list:
    casos = list(Caso.objects.filter(participacoes__paciente=paciente).prefetch_related("participacoes"))
    return sorted(casos, key=lambda caso: (not caso.individual, caso.pk))  # o individual primeiro


def _por_extenso(dia: date) -> str:
    return date_format(dia, "j \\d\\e F \\d\\e Y").lower()


def sugestao_de_demanda(paciente: Paciente) -> str:
    """O começo do texto, só com o que é administrativo (ADR-034): modalidade, frequência, duração e início.

    O motivo da busca e os objetivos são conteúdo clínico — esses o sistema não supõe.
    """
    caso = next(iter(_casos(paciente)), None)
    regra = caso.regra_aberta() if caso else None
    partes = [f"Atendimento psicológico {'individual' if caso is None or caso.individual else 'conjunto'}",
              f"na modalidade {paciente.get_modalidade_display().lower()}"]
    if regra is not None:
        partes.append(f"com frequência {regra.get_frequencia_display().lower()} "
                      f"({regra.get_dia_semana_display().lower()}, às {regra.hora:%H:%M}), "
                      f"em sessões de {regra.duracao} minutos")
    else:
        partes.append("com sessões marcadas conforme a necessidade, sem frequência fixa")
    inicio = paciente.data_primeira_sessao
    if inicio is None:
        primeira = (Consulta.objects.filter(caso__participacoes__paciente=paciente, estado=Consulta.Estado.REALIZADA)
                    .order_by("inicio").first())
        inicio = timezone.localtime(primeira.inicio).date() if primeira else None
    if inicio is not None:
        partes.append(f"iniciado em {_por_extenso(inicio)}")
    return ", ".join(partes) + "."


def sugestao_de_encerramento(paciente: Paciente) -> str:
    """Se o atendimento já tem desfecho registrado (ADR-055), ele vira o começo do registro de encerramento."""
    for caso in _casos(paciente):
        desfecho = caso.desfecho_aberto()
        if desfecho is None:
            continue
        texto = (f"Atendimento encerrado em {_por_extenso(desfecho.data)}. Desfecho: "
                 f"{desfecho.get_tipo_display().lower()}; iniciativa: {desfecho.get_iniciativa_display().lower()}.")
        return f"{texto} {desfecho.motivo.strip()}".strip()
    return ""


def folha_do_prontuario(paciente: Paciente) -> FolhaDoProntuario:
    ficha = ficha_de(paciente)
    demanda = ficha.demanda if ficha else ""
    encerramento = ficha.encerramento if ficha else ""
    return FolhaDoProntuario(
        paciente=paciente, ficha=ficha,
        demanda=demanda or sugestao_de_demanda(paciente), demanda_sugerida=not demanda,
        encerramento=encerramento or sugestao_de_encerramento(paciente), encerramento_sugerido=not encerramento,
        evolucao=list(reversed(registros(paciente=paciente))),
    )


@transaction.atomic
def salvar_folha(paciente: Paciente, *, demanda: str, encerramento: str) -> bool:
    """Grava a avaliação da demanda e o encerramento, se mudaram. Devolve se gravou.

    A **evolução não se escreve aqui** (ADR-080): ela é o conjunto dos registros de sessão, escritos na aba
    Prontuários. O prontuário geral só os reúne — assim o psicólogo nunca tem dúvida de qual dos dois está fazendo.
    """
    demanda, encerramento = demanda.strip(), encerramento.strip()
    ficha = ficha_de(paciente)
    atual = (ficha.demanda, ficha.encerramento) if ficha else ("", "")
    if (demanda, encerramento) == atual or not (demanda or encerramento):
        return False
    FichaDoProntuario.objects.create(paciente=paciente, demanda=demanda, encerramento=encerramento)
    return True


def folha_para_arquivo(paciente: Paciente, psicologo, hoje: date | None = None) -> dict:
    """A folha no formato que `core.exportacao` escreve em PDF e DOCX.

    Só entra o que está **confirmado**: rascunho de sessão não é prontuário e não sai em cópia.
    """
    folha = folha_do_prontuario(paciente)
    identificacao = [f"Nome completo: {paciente.nome}"]
    if paciente.data_nascimento:
        identificacao.append(f"Data de nascimento: {paciente.data_nascimento:%d/%m/%Y}")
    if paciente.cpf:
        cpf = paciente.cpf
        identificacao.append(f"CPF: {cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}")
    for responsavel in paciente.responsaveis.all():
        parentesco = f" ({responsavel.parentesco})" if responsavel.parentesco else ""
        identificacao.append(f"Responsável legal: {responsavel.nome}{parentesco}")
    identificacao.append(f"Psicóloga(o) responsável: {psicologo.nome_completo} — CRP {psicologo.crp}")
    sessoes = []
    for registro in folha.evolucao:
        if registro.vigente is None:
            continue
        inicio = timezone.localtime(registro.consulta.inicio)
        sessoes.append(f"{inicio:%d/%m/%Y}, {inicio:%H:%M} — {registro.vigente.texto.strip()}")
    sem_texto = "Sem registro até esta data."
    hoje = hoje or timezone.localdate()
    return {
        "titulo": "PRONTUÁRIO PSICOLÓGICO", "subtitulo": "",
        "blocos": [
            ("Identificação", "\n".join(identificacao)),
            ("Avaliação da demanda e objetivos do trabalho", (folha.ficha.demanda if folha.ficha else "") or sem_texto),
            ("Evolução do trabalho e procedimentos adotados", "\n\n".join(sessoes) or sem_texto),
            ("Encaminhamento ou encerramento", (folha.ficha.encerramento if folha.ficha else "") or sem_texto),
        ],
        "local_e_data": ", ".join(parte for parte in [psicologo.cidade, _por_extenso(hoje)] if parte),
        "assinatura_nome": psicologo.nome_completo, "assinatura_crp": f"CRP {psicologo.crp}",
        "tracos": False,
    }
