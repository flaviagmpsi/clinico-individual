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

from pacientes.models import Caso, CondicaoCobranca, Paciente, Participacao


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
    vencimento: str = "",
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
            vencimento=vencimento,
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


@transaction.atomic
def excluir_paciente(paciente: Paciente) -> None:
    """Exclusão de verdade — a regra para cadastro feito por engano.

    Decidido na rodada atual: paciente **sem atendimento** é apagado de fato; paciente **com**
    atendimento vai para a lixeira. Mas "atendimento" ainda não existe no código, então, pela
    própria regra, todo paciente de hoje é um cadastro sem atendimento. A lixeira entra junto
    com o módulo de atendimentos.

    Leva junto o caso individual dele — sem isso, o `PROTECT` do pagador impediria a exclusão de
    qualquer paciente, já que todo paciente paga o próprio caso. **Recusa** se ele participa de
    atendimento de casal ou família: apagá-lo ali alteraria em silêncio o vínculo de outra pessoa.
    """
    casos = list(Caso.objects.filter(participacoes__paciente=paciente).prefetch_related("participacoes"))
    if any(caso.participacoes.count() > 1 for caso in casos):
        raise ValidationError(
            "Este paciente participa de um atendimento de casal ou família. "
            "Exclua esse atendimento antes de excluir o paciente.")
    # Consulta realizada ou falta **é atendimento**: pela ADR-048, paciente com atendimento vai para a
    # lixeira, que chega com o registro de desfecho. Até lá, a exclusão é recusada — nunca apagada em
    # silêncio. Os estados vão como texto e pelo nome reverso `consultas`, sem importar `atendimentos`,
    # que depende deste app (regra 5 de dependência).
    if any(caso.consultas.filter(estado__in=["REALIZADA", "FALTA"]).exists() for caso in casos):
        raise ValidationError(
            "Este paciente já tem atendimento registrado e não pode ser apagado — o prontuário tem guarda "
            "obrigatória. A lixeira chega junto com o registro de alta e desistência.")
    for caso in casos:
        caso.consultas.all().delete()  # restam só agendadas e canceladas: previsão, não atendimento
        caso.delete()
    paciente.delete()


def primeiro_dia_do_mes_seguinte(hoje: date | None = None) -> date:
    hoje = hoje or date.today()
    return date(hoje.year + (1 if hoje.month == 12 else 0), hoje.month % 12 + 1, 1)


@transaction.atomic
def trocar_condicao(
    caso: Caso,
    *,
    valor: Decimal,
    modalidade: str,
    vencimento: str = "",
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
        vencimento=vencimento,
        vigente_desde=vigente_desde,
    )
