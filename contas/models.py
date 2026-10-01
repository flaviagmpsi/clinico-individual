"""O psicólogo — raiz do isolamento e, aqui, também o usuário que faz login.

**Decisão de projeto:** `Psicologo` é o próprio `AUTH_USER_MODEL`, não um perfil pendurado
nele. Há exatamente um login por psicólogo (ADR-039: não existe superfície para paciente, e
ADR-001: não existe supervisor), então separar usuário de psicólogo criaria um join em toda
requisição para representar uma relação que é sempre 1-para-1. O `id` do usuário **é** o
identificador do tenant.
"""

from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from contas import abordagens
from core.calendario import TipoDia
from core.enderecos import UF, cep_valido, telefone_opcional
from core.models import TenantOwnedModel, ValidaAoSalvar


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
        """Conta criada por **código** — semente, teste, shell — já nasce com o cadastro concluído.

        Só o quiz (ADR-071) cria conta incompleta, porque é ele quem coleta o que falta, passo a passo. Quem
        chama daqui está informando tudo de uma vez, e trancar essa conta no quiz seria travar a semente e os
        testes num fluxo de tela que eles não estão exercitando.
        """
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("quiz_concluido_em", timezone.now())
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

    # ADR-094: a conta nasce só com e-mail, senha e CRP; nome, CPF e telefone chegam no quiz. Por isso o banco os
    # aceita vazios — e quem os torna obrigatórios é o quiz e o perfil, que são as duas telas que os gravam. O
    # sistema só abre depois do quiz (`CadastroCompletoMiddleware`), então nenhum documento sai sem eles.
    # CPF vazio é `NULL`, e não "": a coluna é única, e duas contas a meio caminho colidiriam em "".
    nome_completo = models.CharField("Nome completo", max_length=255, blank=True)
    cpf = models.CharField("CPF", max_length=11, unique=True, null=True, blank=True, validators=[cpf_valido])
    telefone = models.CharField("Telefone", max_length=20, blank=True, validators=[telefone_valido])

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
    razao_social = models.CharField("Razão social", max_length=255, blank=True)
    crp_empresa = models.CharField("CRP da empresa", max_length=20, blank=True)

    # --- Como atende (C-10, ADR-071, ADR-094, ADR-107) -------------------------------------------
    # ADR-107: as duas voltam a ser **lista fechada**, e o que se guarda é o código do catálogo
    # (`contas.abordagens`), não o texto. Texto livre não conta: "Psicanálise" e "psicanálise" viravam duas
    # respostas. Quem não está na lista marca OUTRA e escreve no campo ao lado — o que vem por ali fica
    # separado de propósito, para ser lido e promovido quando repetir.
    # Abordagem é **como** a pessoa trabalha; área é o que ela faz **além** da clínica. Avaliação
    # neuropsicológica é área, não abordagem: nas duas listas, a mesma pessoa contaria duas vezes.
    abordagens = models.JSONField("Abordagens", default=list, blank=True)
    abordagem_outra = models.CharField("Qual abordagem", max_length=120, blank=True)
    outras_areas = models.JSONField("Outras áreas de atuação", default=list, blank=True)
    area_outra = models.CharField("Qual área", max_length=120, blank=True)
    atende_online = models.BooleanField("Atende online", default=False)
    atende_presencial = models.BooleanField("Atende presencialmente", default=True)

    # ADR-100: o psicólogo decide se o sistema controla as despesas dele. Quem não quer não vê a aba, e o fluxo
    # de caixa vira só a receita. Liga e desliga em Configurações; desligar **não apaga** nada.
    usa_despesas = models.BooleanField("Controlar despesas", default=True)

    # ADR-111: a escrita assistida manda o relato da sessão para um serviço de fora (OpenAI). Isso é decisão de
    # sigilo de quem atende, não nossa — então nasce **desligada**, e quem quiser liga sabendo. Desligada, a tela
    # do registro de sessão é a de sempre: escrever à mão nunca saiu do escopo (ADR-058).
    usa_ia_no_prontuario = models.BooleanField("Escrita assistida no registro de sessão", default=False)

    # Quando o quiz de cadastro foi concluído. Vazio: a conta existe, mas o sistema ainda não sabe o
    # bastante para propor nada — e manda o psicólogo terminar o cadastro antes de qualquer tela.
    quiz_concluido_em = models.DateTimeField("Cadastro concluído em", null=True, blank=True)

    # --- Clínica ou consultório (C-11) -----------------------------------------------------------
    # Onde o psicólogo atende. Hoje serve à identificação do profissional na tela; é também o endereço
    # que o recibo e o documento com timbre vão pedir quando existirem (ADR-008, ADR-030).
    nome_clinica = models.CharField("Nome da clínica ou consultório", max_length=255, blank=True)
    telefone_clinica = models.CharField(
        "Telefone da clínica", max_length=20, blank=True, validators=[telefone_opcional])
    cep = models.CharField("CEP", max_length=8, blank=True, validators=[cep_valido])
    logradouro = models.CharField("Logradouro", max_length=255, blank=True)
    numero = models.CharField("Número", max_length=20, blank=True)
    complemento = models.CharField("Complemento", max_length=100, blank=True)
    bairro = models.CharField("Bairro", max_length=100, blank=True)
    cidade = models.CharField("Cidade", max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, choices=UF.choices, blank=True)

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
    tipo_vencimento_mensalidade = models.CharField(
        "Vencimento da mensalidade em", max_length=8, choices=TipoDia.choices, default=TipoDia.DIA_FIXO,
        help_text="Dia fixo (todo dia 10) ou dia útil (todo 5º dia útil) — ADR-063.")

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
        return f"{self.nome_completo or self.email} (CRP {self.crp})"

    @property
    def cadastro_completo(self) -> bool:
        return self.quiz_concluido_em is not None

    @property
    def abordagem_descrita(self) -> str:
        return abordagens.descrever(self.abordagens, abordagens.ROTULO_DA_ABORDAGEM, self.abordagem_outra)

    @property
    def areas_descritas(self) -> str:
        return abordagens.descrever(self.outras_areas, abordagens.ROTULO_DA_AREA, self.area_outra)

    @property
    def emite_nota_fiscal(self) -> bool:
        """Só a pessoa jurídica emite nota de serviço — é o regime que abre a integração de nota (ADR-094)."""
        return self.regime == self.Regime.PJ

    @property
    def atendimento_descrito(self) -> str:
        formas = [nome for nome, sim in [("online", self.atende_online), ("presencial", self.atende_presencial)] if sim]
        return " e ".join(formas)

    @property
    def crp(self) -> str:
        return f"{self.crp_regiao}/{self.crp_numero}"

    @property
    def mudancas_de_regime(self):
        """O histórico de troca de regime, do mais recente para o mais antigo (ADR-100).

        `TenantOwnedModel` dá ao FK o `related_name` padrão `contas_mudancaderegime`; este nome existe para a view
        e o template não terem de saber disso.

        Usa `objetos_todos` **filtrando pelo próprio psicólogo**, e não o manager de escopo: o dono aqui é este
        objeto, então o filtro é explícito e não há como escapar dele. Sem isso, `regime_em` só funcionaria dentro
        de uma requisição — e ele será chamado também de comando, relatório e teste.
        """
        return MudancaDeRegime.objetos_todos.filter(psicologo=self)

    def regime_em(self, dia) -> str:
        """O regime que valia num dia (ADR-100).

        Trocar de PF para PJ não reescreve o passado: o recibo que saiu em maio saiu como pessoa física, e a
        apuração daquele mês é a de pessoa física. Sem mudança nenhuma registrada, vale o regime de hoje — é a
        conta que existia antes desta ADR, e continua certa para quem nunca trocou.
        """
        anterior = self.mudancas_de_regime.filter(vigente_desde__gt=dia).order_by("vigente_desde").first()
        return anterior.regime_anterior if anterior is not None else self.regime


class MudancaDeRegime(TenantOwnedModel):
    """O dia em que o psicólogo passou de pessoa física a jurídica, ou o contrário (ADR-100).

    Guardado porque a apuração é por período: até a véspera vale um regime, do dia em diante vale o outro. É
    **histórico**, então não se edita nem se apaga — o mesmo princípio do pagamento e da versão de prontuário.
    """

    regime_anterior = models.CharField("Regime anterior", max_length=2, choices=Psicologo.Regime.choices)
    regime_novo = models.CharField("Regime novo", max_length=2, choices=Psicologo.Regime.choices)
    vigente_desde = models.DateField("Vale a partir de")

    class Meta:
        verbose_name = "Mudança de regime"
        verbose_name_plural = "Mudanças de regime"
        ordering = ["-vigente_desde"]

    def __str__(self) -> str:
        return f"{self.get_regime_anterior_display()} → {self.get_regime_novo_display()} em {self.vigente_desde:%d/%m/%Y}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Mudança de regime é histórico: não se altera.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Mudança de regime é histórico: não se apaga.")
