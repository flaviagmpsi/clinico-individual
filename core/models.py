"""Base de todo modelo de domínio.

ADR-001: o dono é explícito em cada tabela. Não há modelo de domínio sem dono — se algum
aparecer, é porque alguém esqueceu de herdar daqui, e o RLS (terceira camada) vai recusar
o acesso mesmo assim.
"""

from django.conf import settings
from django.db import models

from core import contexto
from core.managers import TenantManager, TodosManager


class ValidaAoSalvar(models.Model):
    """Roda os validadores do model em toda gravação, não só em formulário (P-69).

    Sem isto, `RegexValidator` de CPF e telefone só valia dentro de `ModelForm`: um comando de
    management, o shell ou uma view futura sem formulário gravavam `cpf="111.111.111"` sem
    reclamar. A regra tem de valer independentemente de por onde o dado entra.

    **Gravação parcial valida só o que grava.** O login do Django faz
    `save(update_fields=["last_login"])`; validar a linha inteira ali trancaria para fora do
    sistema qualquer psicólogo com um dado legado fora do formato — punindo o login por um
    campo que ele nem está alterando. Unicidade e constraints também ficam de fora nesse caso:
    o banco continua garantindo as duas.
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        campos_gravados = kwargs.get("update_fields")
        if campos_gravados is None:
            self.full_clean()
        else:
            nomes = set(campos_gravados)
            fora = [f.name for f in self._meta.concrete_fields
                    if f.name not in nomes and f.attname not in nomes]
            self.full_clean(exclude=fora, validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)


class TenantOwnedModel(ValidaAoSalvar):
    """Modelo que pertence a um psicólogo.

    O FK aponta para `settings.TENANT_MODEL` em vez de para `contas.Psicologo` porque
    `core` não pode depender de app de domínio (regra 1 de dependência). O mesmo padrão que
    o Django usa em `AUTH_USER_MODEL`.
    """

    psicologo = models.ForeignKey(
        settings.TENANT_MODEL,
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s",
        editable=False,
        verbose_name="Psicólogo",
    )

    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    objects = TenantManager()
    objetos_todos = TodosManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Preencher o dono a partir do contexto, e não pedir a quem chama, elimina a classe
        # inteira de bug "salvei sem dono" e a de "salvei com o dono errado por copiar e colar".
        if self.psicologo_id is None:
            self.psicologo_id = contexto.exigir()
        elif self.psicologo_id != contexto.exigir():
            raise contexto.EscopoNaoDefinido(
                f"Tentativa de gravar registro do psicólogo {self.psicologo_id} "
                f"dentro do escopo do psicólogo {contexto.atual()}."
            )
        super().save(*args, **kwargs)

    # `contexto.exigir()` em vez de comparar com `contexto.atual()` tolerando `None`: a versão
    # anterior pulava a checagem exatamente quando não havia escopo — comando de management,
    # tarefa agendada, shell —, que é onde não existe middleware para corrigir o engano. Gravar
    # para outro psicólogo passava em silêncio. Quem precisa mesmo gravar fora de requisição
    # declara para quem, com `contexto.como(psicologo_id)`.


class RegistroImutavel(Exception):
    """Alguém tentou regravar ou apagar um registro da trilha de auditoria (ADR-057)."""


class RegistroAuditoria(TenantOwnedModel):
    """Uma linha da trilha: o psicólogo viu, criou, alterou, excluiu ou exportou um dado clínico (F-05, ADR-057).

    **Guarda nomes de campo, nunca valores**, e não guarda nome de ninguém — só tipo e número do registro.
    A trilha não se apaga, e o paciente excluído por engano não pode sobreviver nela (ADR-048).

    Vive em `core` porque não conhece domínio: `alvo` e `titular` são rótulos de model ("pacientes.paciente")
    e números, sem chave estrangeira — o registro precisa sobreviver à exclusão do que descreve.
    """

    class Acao(models.TextChoices):
        VER = "VER", "Visualizou"
        CRIAR = "CRIAR", "Criou"
        ALTERAR = "ALTERAR", "Alterou"
        EXCLUIR = "EXCLUIR", "Excluiu"
        EXPORTAR = "EXPORTAR", "Exportou"

    acao = models.CharField("Ação", max_length=8, choices=Acao.choices)
    alvo = models.CharField("Tipo do registro", max_length=60)
    alvo_id = models.BigIntegerField("Número do registro")
    # De quem é o dado — o paciente. É o que junta, no histórico dele, o cadastro e o responsável legal.
    titular = models.CharField("Tipo do titular", max_length=60)
    titular_id = models.BigIntegerField("Número do titular")
    campos = models.JSONField("Campos alterados", default=list, blank=True)

    class Meta:
        verbose_name = "Registro de auditoria"
        verbose_name_plural = "Registros de auditoria"
        ordering = ["-criado_em", "-id"]
        indexes = [models.Index(fields=["psicologo", "titular", "titular_id"], name="auditoria_por_titular")]

    def __str__(self) -> str:
        return f"{self.get_acao_display()} {self.alvo} {self.alvo_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RegistroImutavel("A trilha de auditoria só acrescenta: um registro não é regravado.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RegistroImutavel("A trilha de auditoria só acrescenta: um registro não é apagado.")

    def _modelo(self):
        from django.apps import apps

        try:
            return apps.get_model(self.alvo)
        except (LookupError, ValueError):
            return None

    @property
    def descricao_alvo(self) -> str:
        modelo = self._modelo()
        return str(modelo._meta.verbose_name).capitalize() if modelo else self.alvo

    @property
    def campos_legiveis(self) -> list[str]:
        modelo = self._modelo()
        nomes = []
        for campo in self.campos:
            try:
                nomes.append(str(modelo._meta.get_field(campo).verbose_name) if modelo else campo)
            except Exception:  # campo que deixou de existir no model continua legível pelo nome
                nomes.append(campo)
        return nomes


def exigir_mesmo_dono(registro, **relacionados) -> None:
    """Recusa ligar registros de psicólogos diferentes. Chamar no `clean()` de todo model com FK de domínio.

    Não é redundante com o RLS, e a razão é sutil: a checagem de **chave estrangeira** do Postgres
    ignora as policies. Um `INSERT` apontando para o caso de outro psicólogo passaria pelo banco se o
    id fosse adivinhado — a policy só olha o `psicologo_id` da própria linha. Esta checagem roda no
    `full_clean()` que `ValidaAoSalvar` dispara em toda gravação (P-69), e fecha a porta que o banco
    deixa aberta.

    Vive no `core` porque é genérica — compara donos, não conhece domínio — e todo app com relação
    entre registros precisa dela.
    """
    from django.core.exceptions import ValidationError

    # Durante a validação de um formulário o `psicologo_id` ainda está vazio: ele só é preenchido no
    # `save()`. Nesse momento o dono é o escopo corrente; no `save()` a checagem roda de novo.
    dono = registro.psicologo_id or contexto.atual()
    if dono is None:
        return
    for campo, outro in relacionados.items():
        if outro is not None and outro.psicologo_id != dono:
            # Erro geral, e não preso ao campo: se o campo não estiver no formulário, o Django transforma
            # um erro de campo desconhecido em exceção — um 500 no lugar de uma recusa.
            raise ValidationError(f"{campo}: registro de outro psicólogo.")
