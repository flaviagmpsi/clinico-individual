"""O paciente — a pessoa atendida.

⚠️ Escopo desta versão: o **cadastro**. O vínculo terapêutico (`Caso`), o responsável legal e o
pagador vêm no passo 2 (ADR-026, ADR-014, ADR-009). A pessoa é única entre atendimentos: Maria
em terapia individual e Maria no casal serão o mesmo registro, e é por isso que os dados
pessoais moram aqui e não no `Caso`.

Os campos são os declarados no escopo ("Cadastro de paciente ampliado", `perguntas.md`). Quase
todos são opcionais de propósito — ADR-012, degradar com honestidade: quem cadastra um paciente
no meio do dia não tem o CEP à mão, e exigir tudo transforma cadastro em barreira.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

from core.auditoria import Auditado
from core.calendario import MAIOR_DIA_UTIL, TipoDia, data_no_mes, descrever_dia
from core.models import TenantOwnedModel

# Formato exato, e não só "dígitos": `^\d*$` aceitava CPF "1". Todos admitem vazio porque os
# campos são opcionais (ADR-012) — o que se recusa é o preenchido errado.
cpf_valido = RegexValidator(r"^(\d{11})?$", "CPF tem 11 números, sem pontos ou traços.")
telefone_valido = RegexValidator(r"^(\d{10,11})?$", "Telefone com DDD: 10 ou 11 números, sem espaços ou traços.")
cep_valido = RegexValidator(r"^(\d{8})?$", "CEP tem 8 números, sem traço.")


class Paciente(Auditado, TenantOwnedModel):
    """Dado do paciente é auditado (ADR-057): criar, alterar e excluir entram na trilha; a ficha registra a visualização."""

    class UF(models.TextChoices):
        AC = "AC", "Acre"; AL = "AL", "Alagoas"; AP = "AP", "Amapá"; AM = "AM", "Amazonas"
        BA = "BA", "Bahia"; CE = "CE", "Ceará"; DF = "DF", "Distrito Federal"
        ES = "ES", "Espírito Santo"; GO = "GO", "Goiás"; MA = "MA", "Maranhão"
        MT = "MT", "Mato Grosso"; MS = "MS", "Mato Grosso do Sul"; MG = "MG", "Minas Gerais"
        PA = "PA", "Pará"; PB = "PB", "Paraíba"; PR = "PR", "Paraná"; PE = "PE", "Pernambuco"
        PI = "PI", "Piauí"; RJ = "RJ", "Rio de Janeiro"; RN = "RN", "Rio Grande do Norte"
        RS = "RS", "Rio Grande do Sul"; RO = "RO", "Rondônia"; RR = "RR", "Roraima"
        SC = "SC", "Santa Catarina"; SP = "SP", "São Paulo"; SE = "SE", "Sergipe"
        TO = "TO", "Tocantins"

    class Modalidade(models.TextChoices):
        PRESENCIAL = "PRESENCIAL", "Presencial"
        ONLINE = "ONLINE", "Online"

    nome = models.CharField("Nome completo", max_length=255)

    # Sem CPF é aceitável: quem nasceu antes de 2018 pode não ter (ADR-040 / P-34). A tela avisa,
    # não bloqueia — o CPF só vira obrigatório quando houver saída fiscal, que está fora do MVP.
    cpf = models.CharField("CPF", max_length=11, blank=True, validators=[cpf_valido])
    data_nascimento = models.DateField("Data de nascimento", null=True, blank=True)

    telefone = models.CharField("Telefone", max_length=20, blank=True, validators=[telefone_valido])
    email = models.EmailField("E-mail", blank=True)

    cep = models.CharField("CEP", max_length=8, blank=True, validators=[cep_valido])
    logradouro = models.CharField("Logradouro", max_length=255, blank=True)
    numero = models.CharField("Número", max_length=20, blank=True)
    complemento = models.CharField("Complemento", max_length=100, blank=True)
    bairro = models.CharField("Bairro", max_length=100, blank=True)
    cidade = models.CharField("Cidade", max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, choices=UF.choices, blank=True)

    # Texto livre, e não um catálogo de medicamentos: o psicólogo não prescreve, ele **registra
    # o que o paciente relata usar**. Estruturar isso sugeriria uma precisão clínica que o dado
    # não tem, e puxaria o produto para perto de prontuário médico, que não é o que ele é.
    medicamento = models.TextField("Medicamento em uso", blank=True)

    # Padrão deste paciente; cada sessão pode ser diferente (ADR-065).
    modalidade = models.CharField("Modalidade padrão", max_length=10, choices=Modalidade.choices,
                                  default=Modalidade.PRESENCIAL)
    data_primeira_sessao = models.DateField("Data da primeira sessão", null=True, blank=True)
    observacoes = models.TextField("Observações", blank=True)

    class Meta:
        verbose_name = "Paciente"
        verbose_name_plural = "Pacientes"
        ordering = ["nome"]
        constraints = [
            # Por psicólogo, e não global: dois psicólogos podem atender a mesma pessoa sem
            # saber um do outro, e o sistema não pode deixar isso transparecer (ADR-001).
            # `condition` exclui o branco, senão o segundo paciente sem CPF seria recusado.
            models.UniqueConstraint(
                fields=["psicologo", "cpf"],
                condition=models.Q(cpf__gt=""),
                name="cpf_unico_por_psicologo",
            ),
        ]

    def __str__(self) -> str:
        return self.nome

    @property
    def endereco(self) -> str:
        """Endereço em uma linha, pulando o que estiver vazio."""
        rua = " ".join(p for p in [self.logradouro, self.numero] if p)
        partes = [rua, self.complemento, self.bairro, self.cidade, self.uf]
        return " · ".join(p for p in partes if p)

    @property
    def idade(self) -> int | None:
        if not self.data_nascimento:
            return None
        from datetime import date

        hoje = date.today()
        faz_anos = (hoje.month, hoje.day) >= (self.data_nascimento.month, self.data_nascimento.day)
        return hoje.year - self.data_nascimento.year - (0 if faz_anos else 1)


def _exigir_mesmo_dono(registro, **relacionados) -> None:
    """Movida para `core.models.exigir_mesmo_dono`, que os apps de agenda e atendimentos também usam.
    Mantida aqui só como ponte, para não reescrever os `clean()` deste arquivo."""
    from core.models import exigir_mesmo_dono

    exigir_mesmo_dono(registro, **relacionados)


class Caso(TenantOwnedModel):
    """O vínculo terapêutico — de 1 a N pacientes (ADR-026).

    **Uma forma só no banco, duas formas na tela.** Todo paciente individual tem um caso de um,
    criado em silêncio pelo cadastro (`pacientes.servicos`); a palavra "caso" só aparece para
    quem atende casal ou família. Não pode ser opcional: sem ele, a Maria que faz terapia
    individual e depois entra num casal exigiria migrar dado com o sistema no ar, e cobrança,
    agenda e prontuário teriam dois caminhos cada.

    O que é do **vínculo** mora aqui: quem participa, quem paga, quanto e como se cobra. O que é
    da **pessoa** — dados pessoais, responsável legal — mora em `Paciente`.
    """

    pacientes = models.ManyToManyField(
        Paciente, through="Participacao", related_name="casos", verbose_name="Pacientes")

    # Opcional: um caso de um se chama pelo nome do paciente; só casal e família precisam de rótulo.
    descricao = models.CharField("Descrição", max_length=120, blank=True,
                                 help_text='Ex.: "Maria e João — casal". Vazio no atendimento individual.')

    # --- Pagador (ADR-009) -------------------------------------------------------------------
    # Quem paga é eixo diferente de quem é atendido: pai pagando pelo filho, um cônjuge pagando o
    # casal. O pagador é **um dos participantes** ou **uma pessoa de fora**, nunca os dois.
    pagador_paciente = models.ForeignKey(
        Paciente, on_delete=models.PROTECT, null=True, blank=True, related_name="casos_que_paga",
        verbose_name="Pagador (participante)")
    pagador_nome = models.CharField("Nome do pagador", max_length=255, blank=True)
    pagador_cpf = models.CharField("CPF do pagador", max_length=11, blank=True, validators=[cpf_valido])

    class Meta:
        verbose_name = "Caso"
        verbose_name_plural = "Casos"

    def __str__(self) -> str:
        return self.descricao or " e ".join(p.nome for p in self.pacientes.all()) or f"Caso {self.pk}"

    def clean(self):
        super().clean()
        _exigir_mesmo_dono(self, pagador_paciente=self.pagador_paciente)
        tem_participante = self.pagador_paciente_id is not None
        tem_externo = bool(self.pagador_nome or self.pagador_cpf)
        if tem_participante and tem_externo:
            raise ValidationError(
                "O pagador é um participante ou uma pessoa de fora, não os dois.")
        if self.pagador_cpf and not self.pagador_nome:
            raise ValidationError({"pagador_nome": "Informe o nome de quem paga."})

    @property
    def individual(self) -> bool:
        return self.participacoes.count() == 1

    def condicao_vigente(self, em=None):
        """A condição de cobrança valendo numa data — por padrão, hoje.

        Ver `CondicaoCobranca`: trocar a forma de cobrança cria uma condição nova com data de
        vigência, em vez de sobrescrever a anterior.
        """
        from datetime import date

        em = em or date.today()
        return self.condicoes.filter(vigente_desde__lte=em).order_by("-vigente_desde").first()

    def proxima_condicao(self):
        """A troca já agendada e ainda não em vigor, se houver — para a ficha avisar o que vem."""
        from datetime import date

        return self.condicoes.filter(vigente_desde__gt=date.today()).order_by("vigente_desde").first()

    def regra_aberta(self):
        """A regra de frequência ainda sem data de encerramento; `None` quando o atendimento é avulso (ADR-053).

        Usa o nome reverso `recorrencias` em vez de importar `agenda`: `agenda` depende deste app, e o
        caminho contrário criaria um ciclo (regra 5 de dependência).
        """
        return self.recorrencias.filter(fim__isnull=True).order_by("-inicio").first()

    def desfecho_aberto(self):
        """O desfecho ainda não retomado — é o que faz o atendimento contar como encerrado (ADR-055).

        `None` enquanto o atendimento está em curso. Nome reverso `desfechos`, pelo mesmo motivo de `regra_aberta`.
        """
        return self.desfechos.filter(retomado_em__isnull=True).first()

    def desfechos_anteriores(self):
        """Os desfechos já retomados — o histórico de idas e vindas, do mais recente ao mais antigo."""
        return self.desfechos.filter(retomado_em__isnull=False).order_by("-data")


class Participacao(TenantOwnedModel):
    """Um paciente dentro de um caso.

    Tabela de junção **com dono**, e não o `ManyToManyField` automático do Django: a tabela
    automática não teria `psicologo_id`, e portanto não teria RLS. Pelo SQL cru dela sairia quem
    atende quem — de todos os psicólogos do produto.
    """

    caso = models.ForeignKey(Caso, on_delete=models.CASCADE, related_name="participacoes")
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name="participacoes")

    class Meta:
        verbose_name = "Participação"
        verbose_name_plural = "Participações"
        constraints = [
            models.UniqueConstraint(fields=["caso", "paciente"], name="paciente_uma_vez_por_caso"),
        ]

    def __str__(self) -> str:
        return f"{self.paciente} em {self.caso_id}"

    def clean(self):
        super().clean()
        _exigir_mesmo_dono(
            self,
            caso=self.caso if self.caso_id else None,
            paciente=self.paciente if self.paciente_id else None,
        )


class CondicaoCobranca(TenantOwnedModel):
    """Quanto e como um caso é cobrado, **a partir de uma data** (ADR-002).

    Guardada com vigência, e nunca sobrescrita, por dois motivos:

    1. Cobrança já gerada pode ter pagamento registrado; reescrever a condição que a originou
       desfaria a conta.
    2. A regra de **quando** uma troca passa a valer ainda está em discussão (rodada atual:
       na hora, ou no dia 1º do mês seguinte). Com vigência, as duas respostas cabem no mesmo
       modelo — muda só a data que o sistema preenche.
    """

    class Modalidade(models.TextChoices):
        POR_SESSAO = "POR_SESSAO", "Por sessão"
        MENSAL = "MENSAL", "Mensalidade"

    caso = models.ForeignKey(Caso, on_delete=models.CASCADE, related_name="condicoes")
    modalidade = models.CharField("Forma de cobrança", max_length=12, choices=Modalidade.choices,
                                  default=Modalidade.POR_SESSAO)
    valor = models.DecimalField("Valor", max_digits=10, decimal_places=2,
                                validators=[MinValueValidator(Decimal("0"))])
    # Um dia do mês, e não "início" ou "fim": o lembrete de cobrança precisa de uma data para avisar (ADR-059).
    dia_vencimento = models.PositiveSmallIntegerField(
        "Dia do vencimento", null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text="Só para mensalidade. Em mês mais curto, vale o último dia.")
    # Dia fixo ("todo dia 10") ou dia útil ("todo 5º dia útil") — ADR-063. Vazio no por sessão.
    tipo_vencimento = models.CharField(
        "Tipo de vencimento", max_length=8, choices=TipoDia.choices, blank=True,
        help_text="Dia fixo (todo dia 10) ou dia útil (todo 5º dia útil). Só para mensalidade.")
    vigente_desde = models.DateField("Vale a partir de")

    class Meta:
        verbose_name = "Condição de cobrança"
        verbose_name_plural = "Condições de cobrança"
        ordering = ["-vigente_desde"]
        constraints = [
            models.UniqueConstraint(fields=["caso", "vigente_desde"], name="uma_condicao_por_data"),
        ]

    def __str__(self) -> str:
        return f"{self.get_modalidade_display()} R$ {self.valor} desde {self.vigente_desde:%d/%m/%Y}"

    def clean(self):
        super().clean()
        _exigir_mesmo_dono(self, caso=self.caso if self.caso_id else None)
        if self.modalidade == self.Modalidade.POR_SESSAO:
            # Por sessão vence no dia de cada sessão (ADR-063): não tem data no mês.
            self.dia_vencimento = None
            self.tipo_vencimento = ""
            return
        if not self.dia_vencimento:
            raise ValidationError({"dia_vencimento": "Mensalidade precisa do dia de vencimento."})
        self.tipo_vencimento = self.tipo_vencimento or TipoDia.DIA_FIXO
        if self.tipo_vencimento == TipoDia.DIA_UTIL and self.dia_vencimento > MAIOR_DIA_UTIL:
            raise ValidationError({"dia_vencimento": f"Nenhum mês tem mais que {MAIOR_DIA_UTIL} dias úteis."})

    def vencimento_em(self, ano: int, mes: int):
        """A data em que a mensalidade de um mês vence — dia fixo ou N-ésimo dia útil (ADR-063).

        Além do mês, vira o último: dia 31 em fevereiro, ou 23º dia útil num mês com 20.
        """
        if not self.dia_vencimento:
            return None
        return data_no_mes(self.tipo_vencimento or TipoDia.DIA_FIXO, self.dia_vencimento, ano, mes)

    @property
    def descricao_vencimento(self) -> str:
        if not self.dia_vencimento:
            return ""
        return descrever_dia(self.tipo_vencimento or TipoDia.DIA_FIXO, self.dia_vencimento)


class ResponsavelLegal(Auditado, TenantOwnedModel):
    """Quem autoriza e responde pelo atendimento de criança ou adolescente (ADR-014).

    Pertence ao **paciente**, não ao caso: continua sendo o responsável se a criança passar a
    integrar um atendimento de família. Admite mais de um, porque em guarda compartilhada o
    Código de Ética recomenda a autorização de ambos.

    A autorização em si vive dentro do contrato terapêutico (ADR-015), não aqui.
    """

    class Guarda(models.TextChoices):
        COMPARTILHADA = "COMPARTILHADA", "Compartilhada"
        UNILATERAL = "UNILATERAL", "Unilateral"
        NAO_INFORMADA = "NAO_INFORMADA", "Não informada"

    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name="responsaveis")
    nome = models.CharField("Nome completo", max_length=255)
    parentesco = models.CharField("Parentesco", max_length=60, blank=True, help_text="Ex.: mãe, avô, tutora.")
    cpf = models.CharField("CPF", max_length=11, blank=True, validators=[cpf_valido])
    telefone = models.CharField("Telefone", max_length=20, blank=True, validators=[telefone_valido])
    email = models.EmailField("E-mail", blank=True)
    guarda = models.CharField("Guarda", max_length=15, choices=Guarda.choices, default=Guarda.NAO_INFORMADA)
    detem_guarda = models.BooleanField(
        "Detém a guarda", default=True,
        help_text="Em guarda unilateral, só quem a detém autoriza o atendimento (ADR-014).")

    class Meta:
        verbose_name = "Responsável legal"
        verbose_name_plural = "Responsáveis legais"
        ordering = ["nome"]

    def __str__(self) -> str:
        return f"{self.nome} ({self.parentesco})" if self.parentesco else self.nome

    def auditoria_titular(self):
        return self.paciente

    def clean(self):
        super().clean()
        _exigir_mesmo_dono(self, paciente=self.paciente if self.paciente_id else None)
