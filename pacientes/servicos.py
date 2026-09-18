"""Regras de cadastro que atravessam mais de um model.

Existe porque cadastrar um paciente **não é** gravar uma linha: é gravar o paciente, o caso de um
que o acompanha em silêncio (ADR-026), a participação que liga os dois e, se informada, a
condição de cobrança. Se isso ficasse na view, a próxima tela que cadastrasse paciente — a
importação, o comando `semear` — esqueceria o caso, e o invariante "todo paciente tem caso"
quebraria sem ninguém perceber.

Tudo roda dentro do escopo do psicólogo corrente: na requisição, o middleware já o definiu; fora
dela, quem chama declara com `core.contexto.como(psicologo_id)`.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from pacientes.models import Caso, CondicaoCobranca, ContatoDeEmergencia, Paciente, Participacao


@transaction.atomic
def criar_caso_coletivo(pacientes, *, descricao: str = "", pagador_paciente: Paciente | None = None) -> Caso:
    """Casal ou família: um caso, vários participantes (ADR-026).

    **Não toca nos casos individuais de ninguém.** Maria continua tendo o dela, com valor e
    recorrência próprios, e passa a ter também o do casal. É exatamente esse cenário que tornou a
    estrutura de caso obrigatória: dois vínculos da mesma pessoa, sem um sobrescrever o outro.

    Sem pagador informado, paga o primeiro participante — ajustável depois, como no individual.
    """
    pacientes = list(pacientes)
    if len(pacientes) < 2:
        raise ValidationError("Atendimento de casal ou família tem pelo menos dois participantes.")
    caso = Caso.objects.create(descricao=descricao, pagador_paciente=pagador_paciente or pacientes[0])
    for paciente in pacientes:
        Participacao.objects.create(caso=caso, paciente=paciente)
    return caso


@transaction.atomic
def cadastrar_paciente(
    paciente: Paciente,
    *,
    valor: Decimal | None = None,
    modalidade: str = CondicaoCobranca.Modalidade.POR_SESSAO,
    dia_vencimento: int | None = None,
    tipo_vencimento: str = "",
    vigente_desde: date | None = None,
) -> Caso:
    """Grava o paciente com o caso individual dele.

    O **pagador padrão é o próprio paciente** (ADR-009): o caso comum — adulto pagando a própria
    terapia — não pede campo nenhum a mais. Pai pagando pelo filho é exceção que se ajusta depois.

    A condição de cobrança é opcional de propósito (ADR-012): quem cadastra no meio do dia pode
    ainda não ter combinado valor, e isso não pode barrar o cadastro.
    """
    paciente.save()
    caso = Caso.objects.create(pagador_paciente=paciente)
    Participacao.objects.create(caso=caso, paciente=paciente)
    if valor is not None:
        CondicaoCobranca.objects.create(
            caso=caso,
            modalidade=modalidade,
            valor=valor,
            dia_vencimento=dia_vencimento, tipo_vencimento=tipo_vencimento,
            vigente_desde=vigente_desde or date.today(),
        )
    return caso


def caso_individual_de(paciente: Paciente) -> Caso | None:
    """O caso de um deste paciente — o que a tela do paciente edita sem dizer a palavra "caso".

    Pode haver mais de um ao longo do tempo (alta e retorno anos depois); vale o mais recente.
    """
    candidatos = (
        Caso.objects.filter(participacoes__paciente=paciente)
        .order_by("-criado_em")
        .prefetch_related("participacoes")
    )
    for caso in candidatos:
        if caso.participacoes.count() == 1:
            return caso
    return None


def _tem_atendimento(caso: Caso) -> bool:
    """Sessão presente ou cobrada, ou um desfecho registrado, **é atendimento** (ADR-048, ADR-049, ADR-065).

    Cancelamento e remarcação sem cobrança não são: a sessão não aconteceu e nada foi cobrado. Estados como texto
    e nomes reversos (`consultas`, `desfechos`), sem importar `atendimentos`, que depende deste app (regra 5).
    """
    # Pagamento também conta: é registro financeiro de um atendimento que houve (ADR-063).
    return (caso.consultas.filter(estado="REALIZADA").exists()
            or caso.consultas.filter(cobrada=True).exists()
            or caso.desfechos.exists() or caso.pagamentos.exists())


@transaction.atomic
def excluir_paciente(paciente: Paciente) -> None:
    """Exclusão de verdade — a regra para cadastro feito por engano (ADR-048).

    Paciente **sem atendimento** é apagado de fato. Paciente **com** atendimento é recusado: pela ADR-048
    ele iria para a lixeira, que ainda não existe — e até ela existir, recusar é o lado certo do erro. O
    caminho para tirá-lo da lista de ativos é registrar o desfecho (ADR-055).

    Leva junto o caso individual dele — sem isso, o `PROTECT` do pagador impediria a exclusão de
    qualquer paciente, já que todo paciente paga o próprio caso. **Recusa** se ele participa de
    atendimento de casal ou família: apagá-lo ali alteraria em silêncio o vínculo de outra pessoa.
    """
    casos = list(Caso.objects.filter(participacoes__paciente=paciente).prefetch_related("participacoes"))
    if any(caso.participacoes.count() > 1 for caso in casos):
        raise ValidationError(
            "Este paciente participa de um atendimento de casal ou família. "
            "Exclua esse atendimento antes de excluir o paciente.")
    if any(_tem_atendimento(caso) for caso in casos):
        raise ValidationError(
            "Este paciente já tem atendimento registrado e não pode ser apagado — o prontuário tem guarda "
            "obrigatória. Para tirá-lo da lista de ativos, registre o desfecho do atendimento.")
    # Documento emitido é registro documental (ADR-076). Nome reverso `documentos`, sem importar o app, que
    # depende deste (regra 5 de dependência). Rascunho não é registro de nada e sai junto.
    if paciente.documentos.filter(emitido_em__isnull=False).exists():
        raise ValidationError(
            "Este paciente tem documento psicológico emitido, que faz parte do registro documental e tem guarda "
            "obrigatória. Não pode ser apagado.")
    # A ficha do prontuário (ADR-079) pode existir antes da primeira sessão — a avaliação da demanda se escreve na
    # entrevista inicial. Escrita, é prontuário. Nome reverso, pelo mesmo motivo de `documentos`.
    if paciente.fichas_do_prontuario.exists():
        raise ValidationError(
            "Este paciente já tem prontuário escrito, que tem guarda obrigatória. Não pode ser apagado.")
    for rascunho in paciente.documentos.all():
        rascunho.delete()
    for caso in casos:
        caso.consultas.all().delete()  # restam só cancelamentos e remarcações sem cobrança
        caso.delete()
    paciente.delete()


@transaction.atomic
def excluir_caso_coletivo(caso: Caso) -> None:
    """Desfaz um atendimento de casal ou família criado por engano. Os casos individuais não são tocados.

    Mesma regra do paciente: com atendimento registrado, recusa. Sem isso, o `PROTECT` das consultas
    transformaria a exclusão de um casal com sessões agendadas num erro de servidor.
    """
    if caso.individual:
        raise ValidationError("O atendimento individual acompanha o paciente e sai junto com ele.")
    if _tem_atendimento(caso):
        raise ValidationError(
            "Este atendimento já tem sessão registrada e não pode ser apagado — o prontuário tem guarda "
            "obrigatória. Para encerrá-lo, registre o desfecho.")
    caso.consultas.all().delete()
    caso.delete()


def casos_encerrados():
    """Casos com desfecho em aberto (ADR-055).

    As duas condições no **mesmo** `filter`, para falarem da mesma linha de desfecho. `retomado_em__isnull`
    sozinho casaria também com o caso que nunca teve desfecho nenhum, pelo `LEFT JOIN`.
    """
    return Caso.objects.filter(desfechos__data__isnull=False, desfechos__retomado_em__isnull=True)


def pacientes_encerrados():
    """Quem tem atendimento encerrado e **nenhum** em curso. Continua no histórico — nunca é apagado por isso (ADR-048).

    Definido pelo encerramento, e não pela falta de atendimento em curso: um cadastro sem caso nenhum — que o
    produto não produz, mas um import ou o admin podem — não termina escondido na aba de encerrados.
    """
    encerrados = casos_encerrados().values("pk")
    em_curso = Caso.objects.exclude(pk__in=encerrados)
    return (
        Paciente.objects.filter(pk__in=Participacao.objects.filter(caso__in=encerrados).values("paciente"))
        .exclude(pk__in=Participacao.objects.filter(caso__in=em_curso).values("paciente"))
    )


def pacientes_ativos():
    """Todo paciente que não está encerrado. Terminou o individual e segue no casal: continua ativo."""
    return Paciente.objects.exclude(pk__in=pacientes_encerrados().values("pk"))


def primeiro_dia_do_mes_seguinte(hoje: date | None = None) -> date:
    hoje = hoje or date.today()
    return date(hoje.year + (1 if hoje.month == 12 else 0), hoje.month % 12 + 1, 1)


@transaction.atomic
def trocar_condicao(
    caso: Caso,
    *,
    valor: Decimal,
    modalidade: str,
    dia_vencimento: int | None = None,
    tipo_vencimento: str = "",
    hoje: date | None = None,
) -> CondicaoCobranca:
    """Muda o valor ou a forma de cobrança de um caso — a partir do dia 1º do mês seguinte.

    Decidido com o usuário, a partir de dois exemplos concretos: valer **na hora** faz um dos lados
    perder dinheiro. De sessão para mensalidade no dia 15, as sessões da segunda quinzena ficariam
    sem cobrança nenhuma — o psicólogo atende de graça. De mensalidade para sessão, a mensalidade do
    mês já foi gerada e as sessões restantes seriam cobradas de novo — o paciente paga em dobro.
    Virar no mês resolve os dois sem cálculo proporcional.

    Três regras que decorrem disso:

    - **A condição anterior nunca é alterada.** Continua valendo até o último dia do mês, e o que
      já foi cobrado por ela pode ter pagamento registrado.
    - **Quem nunca teve valor combinado começa hoje.** Não há condição anterior com que conflitar.
    - **Trocar duas vezes no mesmo mês substitui a troca agendada.** Ela ainda não começou a valer,
      então nenhuma cobrança depende dela — é mudança de ideia, não histórico.
    """
    hoje = hoje or date.today()
    tem_condicao = caso.condicoes.filter(vigente_desde__lte=hoje).exists()
    vigente_desde = primeiro_dia_do_mes_seguinte(hoje) if tem_condicao else hoje

    caso.condicoes.filter(vigente_desde=vigente_desde).delete()
    return CondicaoCobranca.objects.create(
        caso=caso,
        valor=valor,
        modalidade=modalidade,
        dia_vencimento=dia_vencimento, tipo_vencimento=tipo_vencimento,
        vigente_desde=vigente_desde,
    )


@transaction.atomic
def definir_contatos_de_emergencia(paciente: Paciente, contatos: list[dict]) -> None:
    """Deixa o paciente com exatamente estes contatos de emergência (ADR-081).

    Compara antes de mexer: salvar o cadastro sem tocar nos contatos não pode encher a trilha de auditoria de
    "excluiu" e "criou" que não aconteceram.
    """
    atuais = list(paciente.contatos_de_emergencia.all())
    como_estao = [(c.nome, c.parentesco, c.telefone) for c in atuais]
    como_ficam = [(c["nome"].strip(), c.get("parentesco", "").strip(), c.get("telefone", "")) for c in contatos]
    if como_estao == como_ficam:
        return
    for contato in atuais:
        contato.delete()
    for nome, parentesco, telefone in como_ficam:
        ContatoDeEmergencia.objects.create(paciente=paciente, nome=nome, parentesco=parentesco, telefone=telefone)

