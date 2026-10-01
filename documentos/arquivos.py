"""O que o psicólogo guarda, mas não foi feito aqui (ADR-112, fecha D-01, D-02 e D-04).

O contrato terapêutico é o caso que originou isto: a ADR-015 decidiu, lá na Rodada 8, que o psicólogo escreve o
próprio contrato fora do sistema e o Hamilton oferece **um lugar para guardar**. A ADR-021 generalizou — arquivo
ligado a um paciente, com tipo e regra de quem vê —, e a ADR-019 escolheu onde: **bytes no Postgres**, porque é
pequeno, raro e tem valor de prova, e porque o disco do Render é efêmero (I-04).

**Por que um model separado do `Documento`.** O `Documento` é o que o sistema **gera** a partir de um modelo: ele
tem `dados` em JSON, congela ao ser emitido e nunca se apaga (ADR-076). O arquivo guardado não tem nada disso —
pode ser substituído quando o contrato é renovado, e pode ser apagado. Na mesma tabela, quase todo campo ficaria
opcional e quase toda regra, condicional. Na tela os dois aparecem juntos, que é o que importa para quem usa.

**Os bytes ficam numa tabela à parte** (`ConteudoDeArquivo`). O Postgres guarda `bytea` fora da linha, mas toda
consulta que listasse arquivos ainda carregaria a coluna se ela estivesse ali — e listar é o que mais acontece.
Separando, a lista lê só metadado, e os bytes só são lidos por quem clica em baixar.
"""

from django.core.exceptions import ValidationError
from django.db import models

from core.auditoria import Auditado
from core.models import TenantOwnedModel, exigir_mesmo_dono
from pacientes.models import Paciente

# 10 MB: cobre contrato escaneado e foto de celular com folga. Acima disso, bytes no Postgres deixam de ser a
# escolha certa — e o recado na tela ensina a reduzir em vez de só recusar.
TAMANHO_MAXIMO = 10 * 1024 * 1024

# O que se guarda é o que foi **assinado**, não o que se edita. Por isso não há .docx aqui: formato de edição não
# é formato de guarda, e aceitar um convida a guardar a versão errada.
TIPOS_ACEITOS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


class ArquivoGuardado(Auditado, TenantOwnedModel):
    class Tipo(models.TextChoices):
        CONTRATO = "CONTRATO", "Contrato terapêutico"
        AUTORIZACAO = "AUTORIZACAO", "Autorização ou consentimento"
        AVALIACAO = "AVALIACAO", "Anexo de avaliação psicológica"
        ENCAMINHAMENTO = "ENCAMINHAMENTO", "Encaminhamento ou relatório de outro profissional"
        OUTRO = "OUTRO", "Outro"

    # `PROTECT` como no resto do registro documental: arquivo guardado não sai junto com o paciente em silêncio
    # (ADR-048). Apagar o paciente exige apagar o que foi guardado sobre ele, de propósito.
    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, related_name="arquivos")
    tipo = models.CharField("Tipo", max_length=20, choices=Tipo.choices, default=Tipo.CONTRATO)
    titulo = models.CharField("Título", max_length=160,
                              help_text="Como você reconhece este arquivo na lista.")
    nome_do_arquivo = models.CharField("Nome do arquivo", max_length=255)
    tipo_mime = models.CharField("Formato", max_length=80)
    tamanho = models.PositiveIntegerField("Tamanho em bytes")
    # Res. CFP 01/2009, Art. 2º, inciso V: anexo de avaliação é de **acesso exclusivo do psicólogo** — não entra
    # no que a pessoa atendida pode pedir. É uma marca, e não uma pasta separada, porque pasta obrigaria a mover
    # arquivo entre lugares; a marca é o mesmo campo que a P-84 vai precisar para o registro privativo.
    restrito = models.BooleanField(
        "Somente eu vejo", default=False,
        help_text="Marque para anexo de avaliação e material que não compõe o que o paciente pode solicitar.")

    class Meta:
        verbose_name = "Arquivo guardado"
        verbose_name_plural = "Arquivos guardados"
        ordering = ["-criado_em"]
        indexes = [models.Index(fields=["psicologo", "paciente"], name="arquivo_dono_paciente")]

    def __str__(self) -> str:
        return f"{self.titulo} · {self.get_tipo_display()}"

    def auditoria_titular(self):
        return self.paciente

    @property
    def extensao(self) -> str:
        return TIPOS_ACEITOS.get(self.tipo_mime, "")

    @property
    def e_imagem(self) -> bool:
        return self.tipo_mime.startswith("image/")

    @property
    def tamanho_legivel(self) -> str:
        if self.tamanho < 1024:
            return f"{self.tamanho} B"
        if self.tamanho < 1024 * 1024:
            return f"{self.tamanho / 1024:.0f} KB"
        return f"{self.tamanho / (1024 * 1024):.1f} MB".replace(".", ",")

    def clean(self):
        super().clean()
        exigir_mesmo_dono(self, paciente=self.paciente if self.paciente_id else None)
        if self.tipo_mime not in TIPOS_ACEITOS:
            raise ValidationError({"tipo_mime": "Formato não aceito. Guarde em PDF, JPG ou PNG."})
        if self.tamanho > TAMANHO_MAXIMO:
            raise ValidationError({"tamanho": "Arquivo acima de 10 MB."})
        if self.tamanho <= 0:
            raise ValidationError({"tamanho": "Arquivo vazio."})


class ConteudoDeArquivo(models.Model):
    """Os bytes, numa tabela só deles.

    Não é `TenantOwnedModel` porque não precisa ser: ele só existe pendurado num `ArquivoGuardado`, que é, e o
    `CASCADE` garante que os bytes morrem junto. Pôr um `psicologo` aqui seria uma segunda fonte da verdade sobre
    de quem é o arquivo — e duas fontes discordam um dia.
    """

    arquivo = models.OneToOneField(ArquivoGuardado, on_delete=models.CASCADE, related_name="conteudo",
                                   primary_key=True)
    bytes_do_arquivo = models.BinaryField("Conteúdo")

    class Meta:
        verbose_name = "Conteúdo de arquivo"
        verbose_name_plural = "Conteúdos de arquivo"

    def __str__(self) -> str:
        return f"Conteúdo de {self.arquivo_id}"
