"""Guardar, listar e apagar arquivo que o psicólogo trouxe de fora (ADR-112).

A validação mora aqui, e não só no formulário, porque um dia outro caminho vai gravar arquivo — o comprovante de
despesa (N-06) e os anexos de avaliação já estão previstos. Formulário é conversa com quem está na tela; isto é a
regra.

**O tipo do arquivo não é o que o navegador diz.** O `content_type` que chega no upload vem do cliente e é
trivialmente forjável: basta renomear. Quem decide aqui é a **assinatura dos primeiros bytes**, que é o que os
leitores de verdade olham. Um executável renomeado para `contrato.pdf` é recusado por não começar com `%PDF-`.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from core import auditoria
from documentos.arquivos import TAMANHO_MAXIMO, TIPOS_ACEITOS, ArquivoGuardado, ConteudoDeArquivo
from pacientes.models import Paciente

# Assinatura dos primeiros bytes de cada formato aceito. É o que um leitor de PDF ou de imagem realmente procura.
_ASSINATURAS: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


@dataclass(frozen=True)
class ArquivoRecebido:
    """O que sobrou do upload depois de conferido: bytes, nome e o formato que os bytes dizem ser."""

    conteudo: bytes
    nome: str
    tipo_mime: str


def conferir(enviado) -> ArquivoRecebido:
    """Lê o upload inteiro e devolve o que serve para gravar, ou levanta `ValidationError` com um recado útil."""
    if enviado is None:
        raise ValidationError("Escolha um arquivo.")
    # O tamanho é conferido **antes** de ler: `enviado.size` vem do cabeçalho, e ler 2 GB para depois recusar
    # seria pagar o custo do ataque.
    if (enviado.size or 0) > TAMANHO_MAXIMO:
        raise ValidationError("Arquivo acima de 10 MB. Digitalize em preto e branco ou reduza a resolução da foto.")
    conteudo = enviado.read()
    if not conteudo:
        raise ValidationError("O arquivo chegou vazio.")
    if len(conteudo) > TAMANHO_MAXIMO:          # o cabeçalho pode mentir; o que foi lido, não
        raise ValidationError("Arquivo acima de 10 MB. Digitalize em preto e branco ou reduza a resolução da foto.")
    tipo_mime = _formato_real(conteudo)
    if tipo_mime is None:
        raise ValidationError("Formato não aceito. Guarde o arquivo em PDF, JPG ou PNG.")
    return ArquivoRecebido(conteudo=conteudo, nome=_nome_seguro(enviado.name, tipo_mime), tipo_mime=tipo_mime)


def _formato_real(conteudo: bytes) -> str | None:
    """O formato que os **bytes** dizem ser — não o que o nome ou o navegador afirmam."""
    for assinatura, tipo_mime in _ASSINATURAS:
        if conteudo.startswith(assinatura):
            return tipo_mime
    return None


def _nome_seguro(nome: str, tipo_mime: str) -> str:
    """Um nome de arquivo que não carrega caminho nem extensão mentirosa.

    O nome vem do computador de quem envia e vai parar num cabeçalho `Content-Disposition` no download. Barra,
    contrabarra e quebra de linha saem; a extensão passa a ser a do formato que os bytes provaram ser.
    """
    limpo = (nome or "arquivo").replace("\\", "/").split("/")[-1]
    limpo = "".join(c for c in limpo if c.isprintable() and c not in '"\r\n').strip() or "arquivo"
    tronco = limpo.rsplit(".", 1)[0][:120] or "arquivo"
    return tronco + TIPOS_ACEITOS[tipo_mime]


@transaction.atomic
def guardar(paciente: Paciente, recebido: ArquivoRecebido, *, titulo: str, tipo: str,
            restrito: bool = False) -> ArquivoGuardado:
    """Grava o metadado e os bytes, numa transação só — arquivo sem conteúdo não chega a existir."""
    arquivo = ArquivoGuardado(
        paciente=paciente, tipo=tipo, titulo=titulo.strip(), restrito=restrito,
        nome_do_arquivo=recebido.nome, tipo_mime=recebido.tipo_mime, tamanho=len(recebido.conteudo),
    )
    arquivo.save()
    ConteudoDeArquivo.objects.create(arquivo=arquivo, bytes_do_arquivo=recebido.conteudo)
    return arquivo


def do_paciente(paciente: Paciente) -> list[ArquivoGuardado]:
    """Os arquivos guardados daquele paciente. Sem os bytes: listar não precisa deles."""
    return list(ArquivoGuardado.objects.filter(paciente=paciente))


def conteudo(arquivo: ArquivoGuardado) -> bytes:
    """Os bytes, para baixar. Entra na trilha: baixar arquivo de paciente é ver dado dele (ADR-057)."""
    auditoria.registrar(auditoria.Acao.VER, arquivo)
    return bytes(arquivo.conteudo.bytes_do_arquivo)
