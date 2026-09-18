"""O prontuário escrito à mão — um por participante, por sessão realizada (ADR-005, ADR-041, ADR-064).

**Rascunho até confirmar; congelado depois.** O texto vive em `VersaoProntuario`. Enquanto a versão não é
confirmada, é rascunho e se edita à vontade. Confirmada, não muda mais — nem pelo model, nem por SQL: a migração
de RLS põe um gatilho no banco.

**Editar é criar outra versão, em silêncio (ADR-075).** Para o psicólogo, a tela tem um botão "Editar" e nada
mais: sem motivo, sem falar em versão. Por baixo, cada edição grava uma versão nova e a anterior continua
guardada — é o que faz do prontuário meio de prova (Res. CFP 001/2009, Art. 4º, §2º), e o que o Manual do CFP
de 2025 pede de plataforma eletrônica: autenticidade do conteúdo.

Por enquanto, **um campo de texto livre** (decisão do usuário, Rodada 40). A IA, na etapa final (ADR-058), vai
preencher o mesmo rascunho.

Pendente não é gravado: é a sessão realizada cujo participante ainda não tem versão confirmada
(`prontuarios.servicos`).
"""

from django.core.exceptions import ValidationError
from django.db import models

from atendimentos.models import Consulta
from core.auditoria import Auditado
from core.models import TenantOwnedModel, exigir_mesmo_dono
from pacientes.models import Paciente


class VersaoCongelada(Exception):
    """Tentativa de alterar ou apagar uma versão de prontuário já confirmada."""


class Prontuario(Auditado, TenantOwnedModel):
    # `PROTECT` nos dois lados: prontuário tem guarda obrigatória e não sai junto com nada em silêncio (ADR-048).
    consulta = models.ForeignKey(Consulta, on_delete=models.PROTECT, related_name="prontuarios")
    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, related_name="prontuarios")

    class Meta:
        verbose_name = "Prontuário"
        verbose_name_plural = "Prontuários"
        constraints = [
            models.UniqueConstraint(fields=["consulta", "paciente"], name="um_prontuario_por_participante_por_sessao"),
        ]

    def __str__(self) -> str:
        return f"Prontuário de {self.paciente} · {self.consulta}"

    def auditoria_titular(self):
        return self.paciente

    def clean(self):
        super().clean()
        exigir_mesmo_dono(
            self,
            consulta=self.consulta if self.consulta_id else None,
            paciente=self.paciente if self.paciente_id else None,
        )
        if self.consulta_id and self.paciente_id:
            if self.consulta.estado != Consulta.Estado.REALIZADA:
                raise ValidationError("Só sessão realizada tem prontuário.")
            if not self.consulta.caso.participacoes.filter(paciente_id=self.paciente_id).exists():
                raise ValidationError("Este paciente não participa desta sessão.")


class VersaoProntuario(Auditado, TenantOwnedModel):
    prontuario = models.ForeignKey(Prontuario, on_delete=models.PROTECT, related_name="versoes")
    numero = models.PositiveSmallIntegerField("Versão")
    texto = models.TextField("Registro da sessão")
    # Não é mais pedido (ADR-075). Fica para as versões gravadas antes disso, que o têm.
    motivo = models.TextField("Motivo da correção", blank=True)
    confirmada_em = models.DateTimeField("Confirmada em", null=True, blank=True)

    class Meta:
        verbose_name = "Versão de prontuário"
        verbose_name_plural = "Versões de prontuário"
        ordering = ["numero"]
        constraints = [
            models.UniqueConstraint(fields=["prontuario", "numero"], name="numero_de_versao_unico"),
            models.UniqueConstraint(fields=["prontuario"], condition=models.Q(confirmada_em__isnull=True),
                                    name="um_rascunho_por_prontuario"),
        ]

    def __str__(self) -> str:
        return f"Versão {self.numero} · {self.prontuario}"

    def auditoria_titular(self):
        return self.prontuario.paciente

    def clean(self):
        super().clean()
        exigir_mesmo_dono(self, prontuario=self.prontuario if self.prontuario_id else None)
        if not (self.texto or "").strip():
            raise ValidationError({"texto": "Escreva o registro da sessão."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            confirmada_no_banco = (
                type(self).objects.filter(pk=self.pk).values_list("confirmada_em", flat=True).first())
            if confirmada_no_banco is not None:
                raise VersaoCongelada("Versão confirmada não se altera. Editar cria uma nova versão.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.confirmada_em is not None:
            raise VersaoCongelada("Versão confirmada de prontuário não se apaga.")
        return super().delete(*args, **kwargs)


class FichaDoProntuario(Auditado, TenantOwnedModel):
    """As partes do prontuário que são do **atendimento**, e não de uma sessão (ADR-079).

    A Res. CFP nº 001/2009 (Art. 2º) pede no prontuário: identificação; avaliação da demanda e definição dos
    objetivos do trabalho; evolução do trabalho; e registro de encaminhamento ou encerramento. A identificação já
    está no cadastro do paciente e a evolução são os registros de sessão (`Prontuario`). Faltavam as outras duas,
    que ficam aqui.

    **Só se acrescenta.** Cada vez que o texto muda, grava-se uma linha nova e a anterior fica guardada; a que vale
    é a mais recente. É a mesma garantia da versão confirmada (ADR-064), sem etapa de rascunho: nenhuma linha se
    altera nem se apaga, pelo model e por gatilho no banco.
    """

    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, related_name="fichas_do_prontuario")
    demanda = models.TextField("Avaliação da demanda e objetivos do trabalho", blank=True)
    encerramento = models.TextField("Encaminhamento ou encerramento", blank=True)
    registrada_em = models.DateTimeField("Registrada em", auto_now_add=True)

    class Meta:
        verbose_name = "Ficha do prontuário"
        verbose_name_plural = "Fichas do prontuário"
        ordering = ["-registrada_em", "-pk"]

    def __str__(self) -> str:
        return f"Ficha do prontuário de {self.paciente} · {self.registrada_em:%d/%m/%Y %H:%M}"

    def auditoria_titular(self):
        return self.paciente

    def clean(self):
        super().clean()
        exigir_mesmo_dono(self, paciente=self.paciente if self.paciente_id else None)
        if not (self.demanda or "").strip() and not (self.encerramento or "").strip():
            raise ValidationError("Escreva a avaliação da demanda ou o registro de encerramento.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise VersaoCongelada("A ficha do prontuário não se altera. Editar grava uma nova.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise VersaoCongelada("A ficha do prontuário não se apaga.")
