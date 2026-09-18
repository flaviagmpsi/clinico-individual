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
from core.enderecos import codigo_postal_de_fora, no_brasil, telefone_de_qualquer_pais
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

    class RacaCor(models.TextChoices):
        # As categorias do IBGE, que são as dos sistemas de saúde. "Prefiro não informar" é resposta, não vazio.
        BRANCA = "BRANCA", "Branca"
        PRETA = "PRETA", "Preta"
        PARDA = "PARDA", "Parda"
        AMARELA = "AMARELA", "Amarela"
        INDIGENA = "INDIGENA", "Indígena"
        NAO_INFORMA = "NAO_INFORMA", "Prefiro não informar"

    class EstadoCivil(models.TextChoices):
        SOLTEIRO = "SOLTEIRO", "Solteiro(a)"
        CASADO = "CASADO", "Casado(a)"
        UNIAO_ESTAVEL = "UNIAO_ESTAVEL", "União estável"
        SEPARADO = "SEPARADO", "Separado(a)"
        DIVORCIADO = "DIVORCIADO", "Divorciado(a)"
        VIUVO = "VIUVO", "Viúvo(a)"

    nome = models.CharField("Nome completo", max_length=255)
    # ADR-081. Nome social é o nome pelo qual a pessoa é tratada: quando existe, é o que as telas mostram ao lado
    # do nome civil, e o que o documento usa se o psicólogo assim escolher.
    nome_social = models.CharField("Nome social", max_length=255, blank=True)
    # Raça/cor e gênero são **dado sensível** (LGPD, Art. 5º, II): sempre opcionais, nunca inferidos.
    raca_cor = models.CharField("Raça/cor", max_length=12, choices=RacaCor.choices, blank=True)
    genero = models.CharField("Gênero", max_length=60, blank=True)
    estado_civil = models.CharField("Estado civil", max_length=15, choices=EstadoCivil.choices, blank=True)
    profissao = models.CharField("Profissão", max_length=120, blank=True)
    # Para quem não tem CPF por não ser brasileiro: passaporte ou RNM, como texto.
    documento_estrangeiro = models.CharField("Documento (estrangeiro)", max_length=40, blank=True,
                                             help_text="Passaporte ou RNM, para quem não tem CPF.")

    # Sem CPF é aceitável: quem nasceu antes de 2018 pode não ter (ADR-040 / P-34). A tela avisa,
    # não bloqueia — o CPF só vira obrigatório quando houver saída fiscal, que está fora do MVP.
    cpf = models.CharField("CPF", max_length=11, blank=True, validators=[cpf_valido])
    data_nascimento = models.DateField("Data de nascimento", null=True, blank=True)

    # Telefone e CEP são validados em `clean()`, e não no campo: o formato depende do **país** (ADR-082).
    telefone = models.CharField("Telefone", max_length=20, blank=True)
    email = models.EmailField("E-mail", blank=True)

    cep = models.CharField("CEP", max_length=12, blank=True)
    logradouro = models.CharField("Logradouro", max_length=255, blank=True)
    numero = models.CharField("Número", max_length=20, blank=True)
    complemento = models.CharField("Complemento", max_length=100, blank=True)
    bairro = models.CharField("Bairro", max_length=100, blank=True)
    cidade = models.CharField("Cidade", max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, choices=UF.choices, blank=True)
    pais = models.CharField("País", max_length=60, blank=True, default="Brasil")
    # A UF é lista fechada dos estados brasileiros. Quem mora fora escreve o estado ou a província à mão (ADR-082).
    estado_exterior = models.CharField("Estado ou província", max_length=60, blank=True,
                                       help_text="Só para endereço fora do Brasil.")

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
    def mora_no_brasil(self) -> bool:
        return no_brasil(self.pais)

    def clean(self):
        """O formato de telefone e de CEP é o do país (ADR-082).

        No Brasil valem as regras de sempre: DDD mais número, CEP de oito números. Fora dele, nada disso existe —
        e exigir seria impedir o cadastro de quem mora fora, que é justamente quem o atendimento online alcança.
        """
        super().clean()
        erros = {}
        regras = ([("telefone", telefone_valido), ("cep", cep_valido)] if self.mora_no_brasil
                  else [("telefone", telefone_de_qualquer_pais), ("cep", codigo_postal_de_fora)])
        for campo, validar in regras:
            try:
                validar(getattr(self, campo) or "")
            except ValidationError as erro:
                erros[campo] = erro.messages
        if erros:
            raise ValidationError(erros)
        if self.mora_no_brasil:
            self.estado_exterior = ""
        else:
            self.uf = ""

    @property
    def endereco(self) -> str:
        """Endereço em uma linha, pulando o que estiver vazio."""
        rua = " ".join(p for p in [self.logradouro, self.numero] if p)
        partes = [rua, self.complemento, self.bairro, self.cidade, self.uf or self.estado_exterior]
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
        carregadas = self._ja_carregado("condicoes")
        if carregadas is not None:
            validas = [condicao for condicao in carregadas if condicao.vigente_desde <= em]
            return max(validas, key=lambda condicao: condicao.vigente_desde, default=None)
        return self.condicoes.filter(vigente_desde__lte=em).order_by("-vigente_desde").first()

    def _ja_carregado(self, relacao: str):
        """A lista de uma relação reversa, se alguém já a trouxe com `prefetch_related`; senão, `None` (ADR-086).

        As telas de financeiro e de indicadores percorrem centenas de cobranças, e cada uma pergunta pela condição
        vigente do caso. Com a relação carregada de uma vez, a resposta sai da memória — sem isso, era uma consulta
        ao banco por cobrança. Quem não carregou continua funcionando igual, pela consulta.
        """
        return getattr(self, "_prefetched_objects_cache", {}).get(relacao)

    def proxima_condicao(self):
        """A troca já agendada e ainda não em vigor, se houver — para a ficha avisar o que vem."""
        from datetime import date

        return self.condicoes.filter(vigente_desde__gt=date.today()).order_by("vigente_desde").first()

    def regra_aberta(self):
        """A regra de frequência ainda sem data de encerramento; `None` quando o atendimento é avulso (ADR-053).

        Usa o nome reverso `recorrencias` em vez de importar `agenda`: `agenda` depende deste app, e o
        caminho contrário criaria um ciclo (regra 5 de dependência).
        """
        carregadas = self._ja_carregado("recorrencias")
        if carregadas is not None:
            return max((regra for regra in carregadas if regra.fim is None), key=lambda regra: regra.inicio,
                       default=None)
        return self.recorrencias.filter(fim__isnull=True).order_by("-inicio").first()

    def desfecho_aberto(self):
        """O desfecho ainda não retomado — é o que faz o atendimento contar como encerrado (ADR-055).

        `None` enquanto o atendimento está em curso. Nome reverso `desfechos`, pelo mesmo motivo de `regra_aberta`.
        """
        carregados = self._ja_carregado("desfechos")
        if carregados is not None:
            return next((desfecho for desfecho in carregados if desfecho.retomado_em is None), None)
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
    telefone = models.CharField("Telefone", max_length=20, blank=True, validators=[telefone_de_qualquer_pais])
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



class ContatoDeEmergencia(Auditado, TenantOwnedModel):
    """Quem avisar se algo acontecer com o paciente (ADR-081). Até dois por paciente, na ordem em que foram dados.

    Não é responsável legal (ADR-014) nem pagador (ADR-009): é só um nome e um telefone, que o psicólogo usa numa
    situação de risco. Pertence ao paciente e sai junto com ele.
    """

    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name="contatos_de_emergencia")
    nome = models.CharField("Nome", max_length=255)
    parentesco = models.CharField("Parentesco", max_length=60, blank=True, help_text="Ex.: mãe, irmão, amiga.")
    telefone = models.CharField("Telefone", max_length=20, validators=[telefone_de_qualquer_pais])

    class Meta:
        verbose_name = "Contato de emergência"
        verbose_name_plural = "Contatos de emergência"
        ordering = ["pk"]

    def __str__(self) -> str:
        return f"{self.nome} ({self.parentesco})" if self.parentesco else self.nome

    def auditoria_titular(self):
        return self.paciente

    def clean(self):
        super().clean()
        _exigir_mesmo_dono(self, paciente=self.paciente if self.paciente_id else None)


class ConviteDeCadastro(TenantOwnedModel):
    """O link que o psicólogo manda para o paciente preencher o próprio cadastro (ADR-081).

    **O convite é uma sala de espera, e não um atalho para dentro do sistema.** Quem abre o link é anônimo e corre
    sob `hamilton_web`, que não alcança tabela clínica nenhuma. O que ele preenche fica guardado **aqui**, em
    `respostas`, e só vira paciente quando o psicólogo — autenticado, no escopo dele — revisa e salva. Link vazado
    não cria paciente, não lê paciente e não revela nada além do nome de quem convidou.

    - **Só o hash do token é guardado.** O link aparece uma vez, na hora de gerar; quem lê o banco não o reconstrói.
    - **Uso único e com validade.** Respondido, o link morre. Sem resposta, expira.
    - **Sem cópia sobrando.** Ao virar paciente, `respostas` é esvaziado: o dado passa a existir num lugar só.
    - No banco, `hamilton_web` enxerga **uma linha**: a do token que a requisição apresentou (migração de RLS).

    Não é `Auditado`: a trilha é gravada pelo papel da aplicação, que o visitante anônimo não tem. O que interessa
    auditar — a criação do paciente — acontece depois, pelo psicólogo, e entra na trilha normalmente.
    """

    token_hash = models.CharField("Hash do token", max_length=64, unique=True, editable=False)
    rotulo = models.CharField("Para quem é", max_length=120, blank=True,
                              help_text="Só para você reconhecer o link na lista. O paciente não vê.")
    expira_em = models.DateTimeField("Expira em")
    respondido_em = models.DateTimeField("Respondido em", null=True, blank=True)
    respostas = models.JSONField("Respostas", default=dict, blank=True)
    aceito_em = models.DateTimeField("Cadastrado em", null=True, blank=True)
    paciente = models.ForeignKey(Paciente, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="convites_de_cadastro")

    class Meta:
        verbose_name = "Convite de cadastro"
        verbose_name_plural = "Convites de cadastro"
        ordering = ["-criado_em"]

    def __str__(self) -> str:
        return f"Convite {self.pk} · {self.situacao}"

    @property
    def situacao(self) -> str:
        from django.utils import timezone

        if self.aceito_em is not None:
            return "cadastrado"
        if self.respondido_em is not None:
            return "respondido"
        return "expirado" if self.expira_em <= timezone.now() else "aguardando"

    @property
    def nome_informado(self) -> str:
        return (self.respostas or {}).get("nome", "")
