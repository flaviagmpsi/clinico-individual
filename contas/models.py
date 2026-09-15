"""O psicólogo — raiz do isolamento e, aqui, também o usuário que faz login.

**Decisão de projeto:** `Psicologo` é o próprio `AUTH_USER_MODEL`, não um perfil pendurado
nele. Há exatamente um login por psicólogo (ADR-039: não existe superfície para paciente, e
ADR-001: não existe supervisor), então separar usuário de psicólogo criaria um join em toda
requisição para representar uma relação que é sempre 1-para-1. O `id` do usuário **é** o
identificador do tenant.
"""

from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

from core.models import ValidaAoSalvar


class PsicologoManager(DjangoUserManager):
    """Login por e-mail. `AbstractUser` assume `username`, e aqui não há username."""

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("E-mail é obrigatório.")
        email = self.normalize_email(email)
        usuario = self.model(email=email, **extra_fields)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_user(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra_fields)


validar_apenas_digitos = RegexValidator(r"^\d+$", "Informe apenas números, sem pontos ou traços.")

# Formato exato. `^\d+$` aceitava CPF "1" — `max_length` limita o teto, não o piso (P-69).
cpf_valido = RegexValidator(r"^\d{11}$", "CPF tem 11 números, sem pontos ou traços.")
telefone_valido = RegexValidator(r"^\d{10,11}$", "Telefone com DDD: 10 ou 11 números, sem espaços ou traços.")
regiao_crp_valida = RegexValidator(r"^\d{2}$", "A região do CRP tem 2 números, como 04.")
cnpj_valido = RegexValidator(r"^(\d{14})?$", "CNPJ tem 14 números, sem pontos, barra ou traço.")


class Psicologo(ValidaAoSalvar, AbstractUser):
    """`ValidaAoSalvar` vem **antes** de `AbstractUser` na herança de propósito: a validação tem
    de rodar antes do `save()` do usuário, que já grava no banco."""

    class Regime(models.TextChoices):
        PF = "PF", "Pessoa física"
        PJ = "PJ", "Pessoa jurídica"

    class SituacaoRegistro(models.TextChoices):
        # ADR-044: a verificação no cadastro do CFP ficou adiada, mas **reversível**. Os
        # campos existem vazios para que retomá-la não exija migration com o sistema em
        # produção. Não construir a integração; só não fechar a porta.
        NAO_VERIFICADO = "NAO_VERIFICADO", "Não verificado"
        ATIVO = "ATIVO", "Ativo"
        CANCELADO = "CANCELADO", "Cancelado"
        TRANSFERIDO = "TRANSFERIDO", "Transferido"

    username = None  # substituído pelo e-mail
    email = models.EmailField("E-mail", unique=True)

    nome_completo = models.CharField("Nome completo", max_length=255)
    cpf = models.CharField("CPF", max_length=11, unique=True, validators=[cpf_valido])
    telefone = models.CharField("Telefone", max_length=20, validators=[telefone_valido])

    # CRP em duas partes, e não em texto livre: a região é filtro e agrupamento em
    # relatório, e um campo único obrigaria a fatiar string em toda consulta (ADR-044).
    crp_regiao = models.CharField("Região do CRP", max_length=2, validators=[regiao_crp_valida])
    crp_numero = models.CharField("Número do CRP", max_length=15, validators=[validar_apenas_digitos])

    situacao_registro = models.CharField(
        "Situação do registro",
        max_length=20,
        choices=SituacaoRegistro.choices,
        default=SituacaoRegistro.NAO_VERIFICADO,
    )
    verificado_em = models.DateTimeField("Verificado em", null=True, blank=True)

    regime = models.CharField("Regime", max_length=2, choices=Regime.choices, default=Regime.PF)
    cnpj = models.CharField("CNPJ", max_length=14, blank=True, validators=[cnpj_valido])
    crp_empresa = models.CharField("CRP da empresa", max_length=20, blank=True)

    # --- Padrões de atendimento (ADR-025, C-03) -------------------------------------------------
    # "Configura uma vez, ajusta na exceção": cada um é o valor que o sistema propõe, e todos são
    # sobrescrevíveis no nível mais específico — paciente, caso ou consulta. Nenhum é regra.

    duracao_sessao = models.PositiveSmallIntegerField(
        "Duração da sessão (minutos)", default=50,
        validators=[MinValueValidator(10), MaxValueValidator(240)],
        help_text="A convenção é 50. Ajustável por paciente: infantil costuma ser mais curta, casal mais longa.")
    # Dia do mês (ADR-059). "Cobro falta" saiu com a ADR-060: a escolha é feita em cada falta.
    dia_vencimento_mensalidade = models.PositiveSmallIntegerField(
        "Dia de vencimento da mensalidade", default=10,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text="Proposto a cada paciente que pagar por mês. Em mês mais curto, vale o último dia.")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nome_completo", "cpf", "crp_regiao", "crp_numero"]

    objects = PsicologoManager()

    class Meta:
        verbose_name = "Psicólogo"
        verbose_name_plural = "Psicólogos"
        constraints = [
            models.UniqueConstraint(fields=["crp_regiao", "crp_numero"], name="crp_unico"),
        ]

    def __str__(self) -> str:
        return f"{self.nome_completo} (CRP {self.crp})"

    @property
    def crp(self) -> str:
        return f"{self.crp_regiao}/{self.crp_numero}"
