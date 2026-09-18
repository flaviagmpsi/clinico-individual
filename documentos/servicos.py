"""Documentos psicológicos: sugerir o que é administrativo, guardar rascunho, emitir e copiar (ADR-076).

Tudo roda no escopo do psicólogo corrente. **Nada aqui lê prontuário, consulta ou qualquer dado clínico**: o que
o sistema sugere é identificação do paciente escolhido e o bloco de assinatura do perfil. O texto do documento é
de quem o assina (Manual do CFP, 2025: a responsabilidade pelo documento é integralmente da profissional).
"""

from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from documentos import modelos
from documentos.models import Documento
from pacientes.models import Paciente


def _cpf(cpf: str) -> str:
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else cpf


def _telefone(numero: str) -> str:
    if len(numero) == 11:
        return f"({numero[:2]}) {numero[2:7]}-{numero[7:]}"
    if len(numero) == 10:
        return f"({numero[:2]}) {numero[2:6]}-{numero[6:]}"
    return numero


def sugestoes(modelo: modelos.ModeloDeDocumento, psicologo, paciente: Paciente | None = None,
              hoje: date | None = None) -> dict:
    """Os valores que o sistema propõe para um modelo em branco — só identificação e assinatura, nada clínico."""
    hoje = hoje or timezone.localdate()
    fontes = {
        "hoje": hoje.isoformat(),
        "psicologo.nome": psicologo.nome_completo,
        "psicologo.crp": f"CRP {psicologo.crp}",
        "psicologo.nome_e_crp": f"{psicologo.nome_completo} — CRP {psicologo.crp}",
        "psicologo.cidade": psicologo.cidade,
        "psicologo.contato": " ou ".join(parte for parte in [
            _telefone(psicologo.telefone_clinica or psicologo.telefone), psicologo.email] if parte),
    }
    if paciente is not None:
        identificacao = []
        if paciente.data_nascimento:
            identificacao.append(f"Data de nascimento: {paciente.data_nascimento:%d/%m/%Y}")
        if paciente.cpf:
            identificacao.append(f"CPF: {_cpf(paciente.cpf)}")
        fontes.update({
            "paciente.nome": paciente.nome,
            "paciente.cpf": _cpf(paciente.cpf),
            "paciente.data_nascimento": paciente.data_nascimento.isoformat() if paciente.data_nascimento else "",
            "paciente.identificacao": "\n".join(identificacao),
        })
    return {campo.nome: fontes[campo.origem] for campo in modelo.campos if fontes.get(campo.origem)}


def _limpar(modelo: modelos.ModeloDeDocumento, dados: dict) -> dict:
    """Só os campos do modelo, sem espaço sobrando. Campo vazio não é gravado."""
    limpos = {campo.nome: (dados.get(campo.nome) or "").strip() for campo in modelo.campos}
    return {nome: valor for nome, valor in limpos.items() if valor}


def _exigir_modelo(codigo: str) -> modelos.ModeloDeDocumento:
    modelo = modelos.obter(codigo)
    if modelo is None:
        raise ValidationError("Modelo de documento desconhecido.")
    return modelo


@transaction.atomic
def salvar_rascunho(codigo: str, dados: dict, *, paciente: Paciente | None = None,
                    documento: Documento | None = None) -> Documento:
    """Cria o rascunho ou grava por cima dele. Rascunho aceita campo em branco; a emissão é que exige."""
    modelo = _exigir_modelo(codigo)
    if documento is None:
        documento = Documento(modelo=codigo)
    elif documento.modelo != codigo:
        raise ValidationError("O modelo de um documento não muda depois de criado.")
    documento.paciente = paciente
    documento.dados = _limpar(modelo, dados)
    documento.save()
    return documento


def faltando(documento: Documento) -> list:
    """Os campos obrigatórios do modelo que ainda estão em branco."""
    return [campo for campo in documento.definicao.obrigatorios if not (documento.dados.get(campo.nome) or "").strip()]


@transaction.atomic
def emitir(documento: Documento, agora: datetime | None = None) -> Documento:
    """Congela o documento: a partir daqui ele é a cópia do que foi entregue (D-05) e não muda mais."""
    if not documento.rascunho:
        raise ValidationError("Este documento já foi emitido.")
    pendentes = faltando(documento)
    if pendentes:
        raise ValidationError("Para emitir, preencha: " + "; ".join(campo.rotulo for campo in pendentes) + ".")
    documento.emitido_em = agora or timezone.now()
    documento.save()
    return documento


@transaction.atomic
def excluir_rascunho(documento: Documento) -> None:
    if not documento.rascunho:
        raise ValidationError("Documento emitido faz parte do registro documental e não se apaga.")
    documento.delete()


@transaction.atomic
def duplicar(documento: Documento, hoje: date | None = None) -> Documento:
    """Um rascunho novo com o mesmo conteúdo — é como se corrige ou se reemite um documento já entregue."""
    dados = dict(documento.dados)
    if "data" in dados:
        dados["data"] = (hoje or timezone.localdate()).isoformat()
    return salvar_rascunho(documento.modelo, dados, paciente=documento.paciente)


def documentos(*, paciente: Paciente | None = None):
    lista = Documento.objects.select_related("paciente")
    return lista.filter(paciente=paciente) if paciente is not None else lista
