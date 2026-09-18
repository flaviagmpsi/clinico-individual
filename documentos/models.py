"""O documento psicológico preenchido a partir de um modelo — rascunho até emitir, congelado depois (ADR-076).

**Por que guardar.** A cópia do documento produzido e entregue compõe o registro documental obrigatório
(Res. CFP nº 01/2009, Art. 2º, VI — a nossa D-05), e o Conselho Regional pode pedir a fundamentação de um atestado
em até cinco anos. Um modelo que só imprimisse obrigaria o psicólogo a arquivar o PDF à mão, em outro lugar.

**Por que congelar.** O que foi entregue é o que foi entregue: a cópia guardada tem de ser idêntica à que saiu. O
model recusa alterar e apagar o emitido, e a migração de RLS põe um gatilho no banco — o mesmo desenho do
prontuário (ADR-064). Corrigir é emitir outro: "Novo a partir deste" copia o conteúdo para um rascunho.

O conteúdo vive em `dados`, um JSON com um valor por campo do modelo. A estrutura não é coluna porque cada
modalidade tem os seus itens, e eles mudam com a norma — `documentos.modelos` é quem sabe quais são.
"""

from django.core.exceptions import ValidationError
from django.db import models

from core.auditoria import Auditado
from core.models import TenantOwnedModel, exigir_mesmo_dono
from documentos import modelos
from pacientes.models import Paciente


class DocumentoEmitido(Exception):
    """Tentativa de alterar ou apagar um documento já emitido."""


class Documento(Auditado, TenantOwnedModel):
    modelo = models.CharField("Modelo", max_length=40)
    # `PROTECT`: documento emitido tem guarda obrigatória e não sai junto com o paciente em silêncio (ADR-048).
    # Opcional porque o parecer pode não tratar de paciente nenhum.
    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="documentos")
    dados = models.JSONField("Conteúdo", default=dict, blank=True)
    emitido_em = models.DateTimeField("Emitido em", null=True, blank=True)

    class Meta:
        verbose_name = "Documento psicológico"
        verbose_name_plural = "Documentos psicológicos"
        ordering = ["-atualizado_em"]
        indexes = [models.Index(fields=["psicologo", "modelo"], name="documento_dono_modelo")]

    def __str__(self) -> str:
        return f"{self.nome} · {self.atendido or 'sem identificação'}"

    @property
    def definicao(self) -> modelos.ModeloDeDocumento | None:
        return modelos.obter(self.modelo)

    @property
    def nome(self) -> str:
        return self.definicao.nome if self.definicao else self.modelo

    @property
    def rascunho(self) -> bool:
        return self.emitido_em is None

    # O que a D-05 pede da cópia guardada: a quem se refere, para quê e para quem.
    @property
    def atendido(self) -> str:
        return (self.dados.get("atendido") or self.dados.get("recebedor") or "").strip()

    @property
    def finalidade(self) -> str:
        return (self.dados.get("finalidade") or self.dados.get("motivo") or "").strip()

    @property
    def destinatario(self) -> str:
        return (self.dados.get("solicitante") or self.dados.get("destino") or "").strip()

    def auditoria_titular(self):
        return self.paciente if self.paciente_id else self

    def clean(self):
        super().clean()
        exigir_mesmo_dono(self, paciente=self.paciente if self.paciente_id else None)
        if self.definicao is None:
            raise ValidationError({"modelo": "Modelo de documento desconhecido."})
        if not isinstance(self.dados, dict):
            raise ValidationError({"dados": "Conteúdo inválido."})
        conhecidos = {campo.nome for campo in self.definicao.campos}
        estranhos = set(self.dados) - conhecidos
        if estranhos:
            raise ValidationError({"dados": f"Campos que este modelo não tem: {', '.join(sorted(estranhos))}."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            emitido_no_banco = type(self).objects.filter(pk=self.pk).values_list("emitido_em", flat=True).first()
            if emitido_no_banco is not None:
                raise DocumentoEmitido("Documento emitido não se altera. Crie um novo a partir dele.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.emitido_em is not None:
            raise DocumentoEmitido("Documento emitido faz parte do registro documental e não se apaga.")
        return super().delete(*args, **kwargs)
