"""O que o psicólogo autônomo pode lançar no livro-caixa do carnê-leão (ADR-099).

**Por que existe.** Antes, a despesa era só um texto livre: o psicólogo escrevia "gasolina" e o sistema aceitava,
somava no fluxo de caixa e sugeria uma dedução que a Receita não admite. Agora cada despesa nasce com uma
**categoria** desta lista, e a lista carrega o que a Receita diz sobre ela.

**O que o sistema faz e o que não faz.** Ele separa o que a Receita aceita do que ela recusa, com a fonte à vista, e
nunca escreve nada no lugar do psicólogo. Onde a norma depende do caso concreto — supervisão, conselho, consultório
dentro de casa — a categoria existe, mas marcada como **a confirmar com a contabilidade**: fingir certeza aí seria
pior que não ter categoria nenhuma. Quem apura é sempre o psicólogo; o Hamilton organiza e mostra a regra.

**Base.** Decreto 9.580/2018 (RIR/2018), art. 68 — dedutíveis da receita do trabalho não assalariado a remuneração
paga a terceiros com vínculo e os encargos, os emolumentos pagos a terceiros e as despesas de custeio necessárias à
percepção da receita e à manutenção da fonte produtora — e as orientações da Receita Federal sobre o carnê-leão
(`gov.br/receitafederal`, "Carnê-leão · Deduções"), consultadas em 27/09/2026:

- despesa de custeio é a indispensável à atividade: aluguel de sala, água, luz, telefone, material de expediente ou
  de consumo, contratação de pessoal;
- **não** se deduz transporte, combustível, estacionamento, IPVA, seguro e manutenção de veículo (a exceção é o
  representante comercial autônomo), depreciação de bens, conserto e reforma de imóvel próprio, e arrendamento
  mercantil;
- congresso, seminário e publicação da área entram quando necessários à atividade e à especialização, guardado o
  comprovante e o certificado;
- a dedução do mês é limitada ao rendimento recebido no mês; o excedente passa para os meses seguintes, até dezembro.

Isto é regra fiscal, não regra do produto: quando a Receita mudar, muda-se **este arquivo**, e a tela toda acompanha.
"""

from dataclasses import dataclass

# Fontes citadas na tela. Ato oficial se cita e se linka (ADR-033).
FONTE_RECEITA = "https://www.gov.br/receitafederal/pt-br/assuntos/meu-imposto-de-renda/pagamento/carne-leao/deducoes"
FONTE_RIR = "https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/decreto/d9580.htm"
CONSULTADO_EM = "27/09/2026"


class Dedutibilidade:
    """O que a Receita diz sobre a categoria — e é isto que decide o que a tela mostra."""

    DEDUTIVEL = "DEDUTIVEL"        # despesa de custeio aceita
    PROPORCIONAL = "PROPORCIONAL"  # aceita em parte: o consultório dentro de casa
    CONFIRMAR = "CONFIRMAR"        # depende do caso concreto — pergunte à contabilidade
    VEDADA = "VEDADA"              # a Receita recusa; entra no caixa, fica fora da apuração

    ROTULOS = {
        DEDUTIVEL: "Entra no carnê-leão",
        PROPORCIONAL: "Entra em parte",
        CONFIRMAR: "Confirme com a contabilidade",
        VEDADA: "Não entra no carnê-leão",
    }


@dataclass(frozen=True)
class Categoria:
    codigo: str
    nome: str
    grupo: str
    dedutibilidade: str
    explicacao: str

    @property
    def deduz(self) -> bool:
        """Se o valor entra na conta que o sistema soma como dedução do livro-caixa."""
        return self.dedutibilidade in (Dedutibilidade.DEDUTIVEL, Dedutibilidade.PROPORCIONAL)

    @property
    def rotulo_da_dedutibilidade(self) -> str:
        return Dedutibilidade.ROTULOS[self.dedutibilidade]


_D, _P, _C, _V = (Dedutibilidade.DEDUTIVEL, Dedutibilidade.PROPORCIONAL,
                  Dedutibilidade.CONFIRMAR, Dedutibilidade.VEDADA)

CATEGORIAS: tuple[Categoria, ...] = (
    # --- o consultório ---------------------------------------------------------------------------------------
    Categoria("ALUGUEL", "Aluguel do consultório", "O consultório", _D,
              "Aluguel do espaço onde você atende. Se você divide uma sala ou paga por hora, é aqui também."),
    Categoria("CONDOMINIO_IPTU", "Condomínio e IPTU do consultório", "O consultório", _D,
              "Do espaço profissional. Do imóvel onde você mora, só na proporção do atendimento em casa."),
    Categoria("CONTAS_DO_CONSULTORIO", "Água, luz e gás do consultório", "O consultório", _D,
              "As contas do espaço onde você atende."),
    Categoria("INTERNET_TELEFONE", "Internet e telefone", "O consultório", _D,
              "A linha e a conexão que você usa para trabalhar — inclusive no atendimento online."),
    Categoria("LIMPEZA_MANUTENCAO", "Limpeza e manutenção do consultório", "O consultório", _D,
              "Faxina, pequenos reparos e conservação do espaço alugado. Reforma de imóvel **seu** não entra."),
    Categoria("BENFEITORIA_ALUGADO", "Benfeitoria em imóvel alugado", "O consultório", _D,
              "Melhoria no imóvel que você aluga, quando o gasto é seu e não do dono."),
    Categoria("CASA_PROPORCIONAL", "Parte da casa usada para atender", "O consultório", _P,
              "Quem atende de casa pode levar uma fração das contas do imóvel — aluguel, água, luz, telefone, "
              "condomínio, IPTU. A Receita admite a quinta parte quando não dá para separar o que é do trabalho. "
              "Lance aqui **só a parte** que você vai deduzir, e combine a fração com a sua contabilidade."),

    # --- o trabalho ------------------------------------------------------------------------------------------
    Categoria("MATERIAL", "Material de trabalho e de escritório", "O trabalho", _D,
              "Material de expediente e de consumo: papel, impressão, itens da sala, testes e protocolos de uso."),
    Categoria("SISTEMAS", "Sistemas e ferramentas de trabalho", "O trabalho", _D,
              "Assinaturas que você usa para atender e para gerir a clínica — inclusive a do Hamilton e a "
              "plataforma de videochamada."),
    Categoria("PESSOAL", "Salário e encargos de funcionário", "O trabalho", _D,
              "Quem trabalha para você **com vínculo**: secretária, recepção, limpeza contratada. Entram o "
              "salário, o FGTS e a contribuição previdenciária patronal."),
    Categoria("SERVICOS_DE_TERCEIROS", "Serviços contratados para a atividade", "O trabalho", _D,
              "O que você paga a terceiros por causa do trabalho: contabilidade, informática, manutenção "
              "do equipamento que você usa para atender."),
    Categoria("DIVULGACAO", "Divulgação profissional", "O trabalho", _D,
              "Propaganda da sua atuação: site, anúncio, cartão. A Receita aceita quando é da atividade."),
    Categoria("FORMACAO", "Congresso, curso e publicação da área", "O trabalho", _D,
              "Encontro científico, curso de especialização, livro e periódico necessários à sua atuação. "
              "Guarde a nota e o certificado de participação — é o que a Receita pede."),
    Categoria("SUPERVISAO", "Supervisão clínica", "O trabalho", _C,
              "A supervisão é exigência ética da profissão e, para muita gente, despesa necessária ao trabalho. "
              "A Receita não a nomeia: confirme com a sua contabilidade antes de deduzir."),
    Categoria("CRP", "Anuidade do CRP", "O trabalho", _C,
              "Sem registro ativo não se atende, o que sustenta tratá-la como despesa da atividade. Mas a Receita "
              "recusa a contribuição mensal a entidade de classe, e a fronteira entre as duas é discutida: "
              "confirme com a sua contabilidade."),

    # --- fora do livro-caixa ---------------------------------------------------------------------------------
    Categoria("TRANSPORTE", "Transporte e veículo", "Fora do carnê-leão", _V,
              "Combustível, estacionamento, aplicativo, IPVA, seguro e manutenção do carro. A Receita só admite "
              "para representante comercial autônomo — não para o psicólogo, mesmo indo até o paciente."),
    Categoria("EQUIPAMENTO", "Compra de equipamento e móveis", "Fora do carnê-leão", _V,
              "Computador, poltrona, ar-condicionado. A compra de bem e a depreciação dele não entram no "
              "livro-caixa. O que entra é o conserto e a manutenção do que você usa para atender."),
    Categoria("IMOVEL_PROPRIO", "Reforma de imóvel próprio", "Fora do carnê-leão", _V,
              "Conserto, reforma e melhoria do imóvel que é seu — inclusive a sala onde você atende."),
    Categoria("PESSOAL_DO_PSICOLOGO", "Despesa pessoal", "Fora do carnê-leão", _V,
              "Plano de saúde, previdência privada, escola, terapia sua. Algumas dessas são dedução da "
              "**declaração anual**, em outro lugar; nenhuma delas é despesa do livro-caixa."),
    Categoria("OUTRA", "Outra despesa", "Fora do carnê-leão", _C,
              "O que não coube em nenhuma categoria. Fica registrada no seu caixa; para a apuração, confirme "
              "com a sua contabilidade se ela pode ser deduzida."),
)

POR_CODIGO = {c.codigo: c for c in CATEGORIAS}
ESCOLHAS = [(c.codigo, c.nome) for c in CATEGORIAS]
PADRAO = "OUTRA"


def categoria(codigo: str) -> Categoria:
    return POR_CODIGO.get(codigo) or POR_CODIGO[PADRAO]


def por_grupo() -> list[tuple[str, list[Categoria]]]:
    """As categorias na ordem em que a tela as mostra, agrupadas — a ordem de `CATEGORIAS` é deliberada."""
    grupos: list[tuple[str, list[Categoria]]] = []
    for c in CATEGORIAS:
        if not grupos or grupos[-1][0] != c.grupo:
            grupos.append((c.grupo, []))
        grupos[-1][1].append(c)
    return grupos
