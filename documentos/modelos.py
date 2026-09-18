"""O catálogo de modelos de documento psicológico (ADR-076).

**De onde vem cada coisa.** A estrutura de cada documento — que itens tem, em que ordem, o que é vedado — vem
da **Resolução CFP nº 06/2019**, que é ato oficial e pode ser reproduzida (Lei 9.610/98, Art. 8º, IV). O
**Manual Orientativo do CFP (2025)** confirma essa estrutura e traz modelos; ele é obra protegida, então aqui
ele é **fonte e link**, nunca cópia (ADR-033). As orientações e as ajudas de campo são escritas com palavras
nossas.

**O que o catálogo não faz.** Não gera texto clínico e não puxa nada do prontuário. Cada campo chega em branco,
com a explicação do que o CFP espera ali. O sistema só oferece o que é administrativo e repetido: nome, CPF e
nascimento do paciente escolhido, e o bloco de assinatura do perfil (ADR-034: a declaração é proibida de conter
sintoma, e a garantia é o dado clínico nem estar à mão).

Catálogo é código, e não tabela: muda quando a norma muda, junto com teste e revisão — não por edição em tela.
"""

import re
from dataclasses import dataclass
from datetime import date

from django.utils import dateformat

MANUAL_CFP = "https://site.cfp.org.br/wp-content/uploads/2025/11/Manual_Orientativo.pdf"
RESOLUCAO_06_2019 = ("https://site.cfp.org.br/wp-content/uploads/2019/09/"
                     "Resolu%C3%A7%C3%A3o-CFP-n-06-2019-comentada.pdf")
VERSAO_DA_NORMA = "Res. CFP nº 06/2019 · Manual Orientativo do CFP, 1ª ed., 2025"

LINHA, TEXTO, DATA = "linha", "texto", "data"


@dataclass(frozen=True)
class Campo:
    nome: str
    rotulo: str
    ajuda: str
    tipo: str = LINHA
    obrigatorio: bool = True
    origem: str = ""  # de onde vem a sugestão: "paciente.nome", "psicologo.crp", "hoje"… Nunca dado clínico.
    linhas: int = 5


@dataclass(frozen=True)
class Secao:
    titulo: str
    campos: tuple
    nota: str = ""


@dataclass(frozen=True)
class Orientacao:
    titulo: str
    texto: str


@dataclass(frozen=True)
class ModeloDeDocumento:
    codigo: str
    nome: str
    grupo: str  # "documento": as modalidades da Res. 06/2019 · "apoio": termos que acompanham o trabalho
    norma: str
    resumo: str
    prerequisito: str
    orientacoes: tuple
    secoes: tuple
    titulo_impresso: str
    # O texto do documento em texto corrido, com `{campo}` onde cada campo cai e `[[…]]` em volta do trecho que
    # só existe se o campo opcional dele for preenchido. É daqui que saem a folha de preencher e a impressa.
    gabarito: str = ""
    itemizado: bool = False          # relatório, laudo e parecer saem em itens; os outros, em texto corrido
    preenche_com_tracos: bool = False  # atestado: o espaço que sobra é fechado com traços (Art. 10, §5º)

    @property
    def campos(self) -> list:
        return [campo for secao in self.secoes for campo in secao.campos]

    @property
    def obrigatorios(self) -> list:
        return [campo for campo in self.campos if campo.obrigatorio]


# --- Campos que se repetem ---------------------------------------------------------------------------------------

def _encerramento(*, quem_assina: str = "Psicóloga(o) responsável") -> Secao:
    """Todo documento fecha com local, data, nome, CRP e assinatura (Res. 06/2019)."""
    return Secao("Encerramento", (
        Campo("local", "Local", "A cidade onde o documento é emitido. Vem do endereço da clínica no seu perfil.",
              origem="psicologo.cidade"),
        Campo("data", "Data de emissão", "A data em que o documento é assinado e entregue.", tipo=DATA,
              origem="hoje"),
        Campo("psicologo_nome", quem_assina,
              "Nome completo ou nome social completo, como no seu registro profissional. Vem do seu perfil.",
              origem="psicologo.nome"),
        Campo("psicologo_crp", "Inscrição no CRP", "Região e número, como em CRP 04/123456. Vem do seu perfil.",
              origem="psicologo.crp"),
    ), nota="No papel: carimbo e assinatura. Com mais de uma lauda, numere-as (1/3, 2/3…), rubrique da primeira "
            "à penúltima e assine a última. Assinatura eletrônica com certificado ICP-Brasil dispensa rubrica e "
            "carimbo (Lei 14.063/2020).")


_VALIDADE = Campo(
    "validade", "Prazo de validade do conteúdo",
    "Obrigatório neste documento, e vai no último parágrafo (Art. 17). Não existe prazo-padrão: decorre da "
    "natureza do que foi avaliado e da finalidade — um adolescente em psicoterapia muda depressa; uma avaliação "
    "para concurso vale só para aquele fim. Havendo norma específica da área, vale o prazo dela. "
    "Ex.: \"As informações deste documento têm validade de seis meses, dado o caráter dinâmico do fenômeno "
    "psicológico.\"", tipo=TEXTO, linhas=3)


def _identificacao(*, atendido: str, ajuda_atendido: str, autor_extra: tuple = ()) -> Secao:
    return Secao("Identificação", (
        Campo("subtitulo", "Subtítulo", "Opcional. Especifica o serviço ou o tipo de trabalho realizado, logo "
              "abaixo do título do documento.", obrigatorio=False),
        Campo("atendido", atendido, ajuda_atendido, origem="paciente.nome"),
        Campo("solicitante", "Nome do solicitante",
              "Quem pediu o documento: a própria pessoa atendida, o responsável legal, o Poder Judiciário, uma "
              "empresa, uma instituição pública ou privada. Diga qual é."),
        Campo("finalidade", "Finalidade",
              "A razão do pedido, de forma específica. É ela que delimita o uso do documento depois de entregue — "
              "e é por ela que você se resguarda."),
        Campo("autor", "Autora(or)", "Seu nome completo e o número de inscrição no CRP.",
              origem="psicologo.nome_e_crp"),
        *autor_extra,
        Campo("outras_informacoes", "Outras informações de identificação",
              "Opcional. Data de nascimento, idade, documento de identificação, escolaridade, nome dos "
              "responsáveis (para criança e adolescente). Só o que ajuda a identificar — nada clínico aqui.",
              tipo=TEXTO, obrigatorio=False, origem="paciente.identificacao", linhas=3),
    ))


_DEMANDA = Campo(
    "demanda", "Descrição da demanda",
    "O que motivou a busca pelo trabalho, quem forneceu as informações e que demandas levaram ao pedido deste "
    "documento. É o ponto de partida que justifica tudo o que vem depois.", tipo=TEXTO)

_PROCEDIMENTO = Campo(
    "procedimento", "Procedimento",
    "O raciocínio técnico-científico que justifica o trabalho: os recursos e técnicas utilizados, o referencial "
    "teórico-metodológico, as pessoas ouvidas, as informações objetivas, o número de encontros e a duração do "
    "processo.", tipo=TEXTO)


# --- As cinco modalidades da Res. CFP 06/2019 -------------------------------------------------------------------------

DECLARACAO = ModeloDeDocumento(
    codigo="declaracao", nome="Declaração", grupo="documento", norma="Res. CFP nº 06/2019, Art. 9º",
    titulo_impresso="DECLARAÇÃO",
    gabarito="Declara-se, para fins de {finalidade}, que {atendido}[[, CPF {cpf}]], {informacao}",
    resumo="Documento curto que informa fatos objetivos sobre o serviço: que a pessoa compareceu, que está em "
           "acompanhamento, há quanto tempo, em que dias e horários.",
    prerequisito="Nenhum além do atendimento em si. É o documento mais pedido no dia a dia da clínica.",
    orientacoes=(
        Orientacao("O que ela pode dizer",
                   "Três coisas, todas objetivas: o comparecimento da pessoa atendida ou de quem a acompanha; que "
                   "há acompanhamento psicológico realizado ou em andamento; e o tempo de acompanhamento, com dias "
                   "e horários."),
        Orientacao("O que ela não pode dizer — e por quê",
                   "É vedado registrar sintomas, situações ou estados psicológicos (Art. 9º, §1º). A declaração "
                   "costuma ir para empresa, escola ou repartição: qualquer informação clínica ali é quebra de "
                   "sigilo sem necessidade. Se o pedido exige falar de condição psicológica, o documento é "
                   "outro — atestado ou relatório."),
        Orientacao("A finalidade é obrigatória, e específica",
                   "Diga para que o documento serve e a quem se destina. Evite \"para os devidos fins\": é a "
                   "finalidade declarada que limita o uso do documento depois que ele sai da sua mão."),
        Orientacao("Forma",
                   "Pode ser em itens ou em texto corrido, em linguagem formal e impessoal, na terceira pessoa "
                   "(\"Declara-se…\"). Não tem prazo de validade. Fecha com local, data, nome, CRP, carimbo e "
                   "assinatura."),
    ),
    secoes=(
        Secao("Conteúdo", (
            Campo("finalidade", "Finalidade",
                  "Para que serve e a quem se destina. Ex.: \"apresentação à empresa Indústria de Alimentos S.A.\" "
                  "ou \"comprovação junto à Escola Municipal Crescer e Aprender\". Nunca \"para os devidos fins\"."),
            Campo("atendido", "Nome de quem a declaração identifica",
                  "A pessoa atendida — ou o acompanhante, quando é o comparecimento dele que se declara (pai ou "
                  "mãe que trouxe a criança, por exemplo).", origem="paciente.nome"),
            Campo("cpf", "CPF", "Opcional. Ajuda a identificar a pessoa diante de quem recebe o documento.",
                  obrigatorio=False, origem="paciente.cpf"),
            Campo("informacao", "O que se declara",
                  "Só fatos objetivos. Ex.: \"compareceu a atendimento psicológico no dia 30 de maio de 2025, das "
                  "16h às 17h\"; ou \"encontra-se em atendimento psicológico com frequência semanal, às "
                  "quartas-feiras, das 16h às 17h, desde março de 2025\"; ou \"acompanha o filho (nome completo), "
                  "o qual se encontra em atendimento psicológico…\". Nenhum sintoma, diagnóstico ou estado "
                  "psicológico.", tipo=TEXTO, linhas=4),
        )),
        _encerramento(),
    ),
)

ATESTADO = ModeloDeDocumento(
    codigo="atestado", nome="Atestado psicológico", grupo="documento", norma="Res. CFP nº 06/2019, Art. 10",
    titulo_impresso="ATESTADO PSICOLÓGICO", preenche_com_tracos=True,
    # O solicitante vai entre parênteses para não depender de contração ("de a própria pessoa" → "da"). A idade é
    # campo próprio: como aposto, entra com as duas vírgulas — ou não entra.
    gabarito="Atesta-se, para fins de {finalidade} (solicitante: {solicitante}), que {atendido}[[, {idade},]] "
             "{condicoes} {validade}",
    resumo="Afirma, com fundamento em diagnóstico psicológico, uma situação, estado ou funcionamento psicológico "
           "— para justificar falta ou impedimento, atestar aptidão para uma atividade ou pedir afastamento.",
    prerequisito="Só se emite atestado a partir de uma avaliação psicológica (Res. CFP nº 31/2022), registrada no "
                 "seu registro documental. A avaliação pode acontecer dentro do acompanhamento psicoterápico, "
                 "mas precisa existir e estar documentada.",
    orientacoes=(
        Orientacao("Por que exige avaliação",
                   "O atestado comunica uma conclusão técnica sobre as condições psicológicas da pessoa. O Conselho "
                   "Regional pode pedir, em até cinco anos, a fundamentação técnico-científica que a sustenta "
                   "(Art. 10, §4º). Sem avaliação registrada, não há o que apresentar."),
        Orientacao("Diagnóstico psicológico não é diagnóstico nosológico",
                   "O que se atesta é o estado psicológico relativo ao que foi avaliado. O uso de CID ou de outra "
                   "classificação é facultado quando justificadamente necessário — e a divulgação do código no "
                   "documento pede autorização por escrito da pessoa atendida."),
        Orientacao("Texto corrido, sem parágrafos",
                   "Para impedir acréscimo posterior, o atestado é escrito em um bloco só; o espaço que sobra na "
                   "linha é fechado com traços (Art. 10, §5º). O sistema faz isso na impressão."),
        Orientacao("Validade e limites",
                   "O prazo de validade do conteúdo vai no fim do texto (Art. 17). No trabalho, a CLT menciona "
                   "atestado médico para abono de falta: o atestado psicológico justifica, e cabe à organização "
                   "aceitar. Afastamento acima de 15 dias passa por perícia do INSS. Em avaliação compulsória "
                   "(trânsito, porte de arma, concurso) valem as resoluções específicas."),
    ),
    secoes=(
        Secao("Conteúdo", (
            Campo("atendido", "Nome completo da pessoa atendida", "Nome completo ou nome social.",
                  origem="paciente.nome"),
            Campo("idade", "Idade", "Opcional. Como em \"35 anos\" — entra logo depois do nome.",
                  obrigatorio=False),
            Campo("solicitante", "Nome do solicitante", "Quem pediu o atestado — em geral a própria pessoa atendida."),
            Campo("finalidade", "Finalidade",
                  "Específica. Ex.: \"comprovação junto ao trabalho\", \"justificativa de ausência em prova\"."),
            Campo("condicoes", "Descrição das condições psicológicas e o que delas decorre",
                  "Continue a frase \"Atesta-se… que (nome)\" começando pelo verbo: \"encontra-se…\", "
                  "\"apresenta…\". O estado ou funcionamento psicológico verificado na avaliação e a consequência prática: dias "
                  "de afastamento, aptidão ou inaptidão para a atividade, dispensa. Só o necessário para a "
                  "finalidade. Se citar CID, tenha a autorização escrita da pessoa.", tipo=TEXTO, linhas=5),
            _VALIDADE,
        )),
        _encerramento(),
    ),
)

RELATORIO = ModeloDeDocumento(
    codigo="relatorio", nome="Relatório psicológico", grupo="documento", norma="Res. CFP nº 06/2019, Art. 11",
    titulo_impresso="RELATÓRIO PSICOLÓGICO", itemizado=True,
    resumo="Comunica a atuação profissional — concluída ou em andamento — de forma detalhada e didática. É "
           "informativo, não diagnóstico, e pode trazer orientações, recomendações e encaminhamentos.",
    prerequisito="O relatório se constrói a partir do seu registro documental e do prontuário. Toda pessoa em "
                 "acompanhamento tem direito de pedi-lo; fornecê-lo é dever ético.",
    orientacoes=(
        Orientacao("Cinco itens, nesta ordem",
                   "Identificação, descrição da demanda, procedimento, análise e conclusão. A estrutura existe "
                   "para que o leitor acompanhe o raciocínio: de onde veio o pedido, o que foi feito, o que se "
                   "observou e a que se chegou."),
        Orientacao("Não é a transcrição das sessões",
                   "É uma comunicação sistematizada do trabalho. Descrição literal de atendimento só quando se "
                   "justifica tecnicamente. Você escolhe o que entra, conforme a finalidade e o sigilo."),
        Orientacao("Fale só de quem você atendeu",
                   "Não emita conclusão, julgamento ou hipótese diagnóstica sobre terceiros que não foram ouvidos "
                   "— o suposto autor de uma violência, por exemplo. O relatório clínico não tem finalidade "
                   "pericial: subsidia decisões, não elucida fatos controversos."),
        Orientacao("Entrega, validade e referências",
                   "A entrega pede ao menos uma entrevista devolutiva; se não for possível, registre o motivo no "
                   "prontuário. O prazo de validade vai no último parágrafo (Art. 17). Referências não são "
                   "obrigatórias; havendo, de preferência em nota de rodapé. Escreva na terceira pessoa."),
    ),
    secoes=(
        _identificacao(atendido="Nome da pessoa ou instituição atendida",
                       ajuda_atendido="Nome completo ou nome social completo de quem foi atendido."),
        Secao("Descrição da demanda", (_DEMANDA,)),
        Secao("Procedimento", (_PROCEDIMENTO,)),
        Secao("Análise", (
            Campo("analise", "Análise",
                  "Exposição descritiva, narrativa e sobretudo analítica do trabalho e da sua evolução, com "
                  "fundamentação teórica e técnica. Relate o que for necessário para responder à demanda, "
                  "respeitando o sigilo — nem tudo o que está no prontuário cabe aqui.", tipo=TEXTO, linhas=8),
        )),
        Secao("Conclusão", (
            Campo("conclusao", "Conclusão",
                  "Decorre da análise. Pode trazer encaminhamento, orientação e sugestão de continuidade. Convém "
                  "retomar a finalidade do documento e registrar a entrevista devolutiva. Você pode destacar que "
                  "o documento não serve a fim diferente do indicado, que é sigiloso e extrajudicial.",
                  tipo=TEXTO, linhas=6),
            _VALIDADE,
        )),
        _encerramento(),
    ),
)

LAUDO = ModeloDeDocumento(
    codigo="laudo", nome="Laudo psicológico", grupo="documento", norma="Res. CFP nº 06/2019, Art. 13",
    titulo_impresso="LAUDO PSICOLÓGICO", itemizado=True,
    resumo="Resultado de um processo de avaliação psicológica, para subsidiar decisões no contexto em que a "
           "demanda surgiu. Tem valor técnico-científico e narrativa detalhada e didática.",
    prerequisito="Só existe laudo onde houve avaliação psicológica, com métodos, técnicas e instrumentos "
                 "reconhecidos (Res. CFP nº 31/2022; testes com parecer favorável no SATEPSI). Sem avaliação, o "
                 "documento cabível é o relatório.",
    orientacoes=(
        Orientacao("Seis itens — e as referências são obrigatórias",
                   "Identificação, descrição da demanda, procedimento, análise, conclusão e referências. É o que "
                   "o distingue do relatório: o laudo responde a uma demanda de avaliação e precisa mostrar em "
                   "que ciência se apoia."),
        Orientacao("A análise interpreta, não lista resultados",
                   "Não basta descrever escores e respostas: a análise explica o que os dados significam, de forma "
                   "metódica e coerente, lembrando que o fenômeno psicológico é dinâmico, não definitivo e não "
                   "cristalizado."),
        Orientacao("A conclusão",
                   "Indica diagnóstico, prognóstico e hipótese diagnóstica, a evolução do caso, e orientação ou "
                   "sugestão de projeto terapêutico — sempre a partir do que a análise sustentou."),
        Orientacao("Entrega e validade",
                   "Pede entrevista devolutiva e protocolo de entrega. O prazo de validade vai no último parágrafo "
                   "(Art. 17). Quando o que se precisa comunicar é só a conclusão, o documento é o atestado — o "
                   "sigilo é o principal critério para escolher entre os dois."),
    ),
    secoes=(
        _identificacao(atendido="Nome da pessoa ou instituição atendida",
                       ajuda_atendido="Nome completo ou nome social completo de quem foi avaliado."),
        Secao("Descrição da demanda", (_DEMANDA,)),
        Secao("Procedimento", (
            Campo("procedimento", "Procedimento",
                  "Os métodos, técnicas e instrumentos da avaliação e o referencial que os fundamenta; as pessoas "
                  "ouvidas, o número de encontros e a duração do processo. Os procedimentos precisam ser "
                  "compatíveis com a complexidade da demanda e atender à Res. CFP nº 31/2022.", tipo=TEXTO),
        )),
        Secao("Análise", (
            Campo("analise", "Análise",
                  "Exposição descritiva, metódica, objetiva e coerente com os dados colhidos. Interprete os "
                  "dados — não se limite a apresentá-los —, com fundamentação teórica e técnica, e relate só o "
                  "necessário para responder à demanda.", tipo=TEXTO, linhas=8),
        )),
        Secao("Conclusão", (
            Campo("conclusao", "Conclusão",
                  "Diagnóstico, prognóstico e hipótese diagnóstica; evolução do caso; orientação ou sugestão de "
                  "projeto terapêutico. Retome a finalidade e registre a entrevista devolutiva.",
                  tipo=TEXTO, linhas=6),
            _VALIDADE,
        )),
        Secao("Referências", (
            Campo("referencias", "Referências",
                  "Obrigatórias no laudo. De preferência em nota de rodapé; aqui, liste-as uma por linha.",
                  tipo=TEXTO, linhas=4),
        )),
        _encerramento(),
    ),
)

PARECER = ModeloDeDocumento(
    codigo="parecer", nome="Parecer psicológico", grupo="documento", norma="Res. CFP nº 06/2019, Art. 14",
    titulo_impresso="PARECER PSICOLÓGICO", itemizado=True,
    resumo="Análise técnica que responde a uma consulta: esclarece uma questão-problema do campo psicológico ou "
           "aprecia um documento psicológico questionado. O resultado pode ser indicativo ou conclusivo.",
    prerequisito="O parecer NÃO decorre de avaliação nem de intervenção feita por quem o assina — é resposta a uma "
                 "consulta. Exige conhecimento específico e competência no assunto, comprovados por titulação.",
    orientacoes=(
        Orientacao("Quando cabe",
                   "Quando alguém pergunta algo do âmbito da Psicologia — \"este instrumento é válido para este "
                   "uso?\" — ou pede a apreciação de um documento feito por outra(o) psicóloga(o), como o "
                   "assistente técnico diante do laudo da perita. Pode ser inteiramente teórico."),
        Orientacao("Por que pede titulação",
                   "Quem emite parecer fala como especialista. A identificação traz, além do nome e do CRP, a "
                   "titulação que comprova o conhecimento no assunto."),
        Orientacao("Estrutura",
                   "Identificação, descrição da demanda, análise, conclusão e referências — obrigatórias. Não "
                   "tem item de procedimento, porque não houve atendimento, nem prazo de validade."),
        Orientacao("Contestar ou ratificar exige fundamento",
                   "Ao analisar o documento de colega, avalie se ele atende aos preceitos científicos, técnicos e "
                   "éticos da Psicologia. Toda objeção e toda concordância se apoiam na ciência, na técnica e nas "
                   "normativas — nunca em opinião."),
    ),
    secoes=(
        _identificacao(
            atendido="Nome da pessoa ou instituição objeto do parecer",
            ajuda_atendido="De quem ou do que trata a consulta: a pessoa, a instituição ou o documento questionado.",
            autor_extra=(Campo("titulacao", "Titulação",
                               "A formação que comprova conhecimento específico e competência no assunto: "
                               "especialização, mestrado, título de especialista do CFP.", tipo=TEXTO, linhas=2),)),
        Secao("Descrição da demanda", (
            Campo("demanda", "Descrição da demanda",
                  "As informações da consulta, a questão que se quer respondida e a finalidade do parecer, com a "
                  "justificativa da análise que será feita.", tipo=TEXTO),
        )),
        Secao("Análise", (
            Campo("analise", "Análise",
                  "Discussão minuciosa da questão, argumentada nos fundamentos éticos, técnicos e conceituais da "
                  "Psicologia e nas normativas que regulam o exercício profissional.", tipo=TEXTO, linhas=8),
        )),
        Secao("Conclusão", (
            Campo("conclusao", "Conclusão",
                  "O seu posicionamento sobre a questão-problema ou sobre o documento analisado. Você pode "
                  "destacar que o parecer não serve a fim diferente do indicado, que é sigiloso e extrajudicial.",
                  tipo=TEXTO, linhas=6),
        )),
        Secao("Referências", (
            Campo("referencias", "Referências",
                  "Obrigatórias no parecer. De preferência em nota de rodapé; aqui, liste-as uma por linha.",
                  tipo=TEXTO, linhas=4),
        )),
        _encerramento(),
    ),
)


# --- Documentos de apoio: acompanham o trabalho, não são modalidade da Res. 06/2019 -----------------------------------

TERMO_DE_ENTREGA = ModeloDeDocumento(
    codigo="termo-de-entrega", nome="Termo de entrega de documento", grupo="apoio",
    norma="Res. CFP nº 06/2019 — entrega de documentos", titulo_impresso="TERMO DE ENTREGA",
    gabarito="Eu, {recebedor}, confirmo que o documento {documento_entregue} me foi entregue pela(o) psicóloga(o) "
             "abaixo assinada(o)[[, {devolutiva}]], que me explicou o seu conteúdo e me entregou uma via. De acordo "
             "com a Resolução CFP nº 06/2019, o documento psicológico tem caráter sigiloso e extrajudicial, não "
             "cabendo à(ao) psicóloga(o) responsabilizar-se pelo uso dado a ele por parte da pessoa, grupo ou "
             "instituição após a sua entrega.",
    resumo="Protocolo assinado por quem recebe o documento: comprova a entrega e transfere a responsabilidade pelo "
           "uso e pelo sigilo do que foi entregue.",
    prerequisito="Use sempre que entregar relatório, laudo, atestado ou parecer. Guarde uma via no registro "
                 "documental do paciente.",
    orientacoes=(
        Orientacao("Por que protocolar",
                   "O documento psicológico é sigiloso e extrajudicial, e você não responde pelo uso que fazem "
                   "dele depois de entregue — desde que consiga provar a quem entregou, quando, e que explicou o "
                   "conteúdo."),
        Orientacao("A quem se entrega",
                   "Diretamente à pessoa atendida, ao responsável legal ou ao solicitante. Por meio digital, vale "
                   "o e-mail oficial do destinatário com resposta confirmando o recebimento."),
        Orientacao("Relatório e laudo pedem devolutiva",
                   "A entrega acontece numa entrevista devolutiva, em que você explica o documento. O termo "
                   "registra que ela aconteceu."),
    ),
    secoes=(
        Secao("Conteúdo", (
            Campo("recebedor", "Nome de quem recebe",
                  "A pessoa atendida, o responsável legal ou o solicitante — quem vai assinar o termo.",
                  origem="paciente.nome"),
            Campo("documento_entregue", "Documento entregue",
                  "A modalidade e, se houver, o subtítulo. Ex.: \"Laudo Psicológico de Avaliação "
                  "Neuropsicológica\", \"Relatório Psicológico\"."),
            Campo("devolutiva", "Entrevista devolutiva",
                  "Opcional. Quando aconteceu a entrevista em que o documento foi explicado. Ex.: \"em sessão "
                  "devolutiva realizada em 12 de junho de 2025\".", obrigatorio=False),
        )),
        _encerramento(),
    ),
)

AUTORIZACAO_MENOR = ModeloDeDocumento(
    codigo="autorizacao-crianca-adolescente", nome="Autorização para atender criança ou adolescente",
    grupo="apoio", norma="Res. CFP nº 13/2022, Anexo I",
    titulo_impresso="AUTORIZAÇÃO PARA ACOMPANHAMENTO PSICOTERAPÊUTICO DE CRIANÇAS E ADOLESCENTES "
                    "(MENORES DE 18 ANOS)",
    gabarito="Eu, {responsavel}, data de nascimento {responsavel_nascimento}, portador(a) do documento de identidade "
             "nº {responsavel_documento}, domiciliado(a) à {responsavel_endereco}, responsável legal pela(o) "
             "criança/adolescente {atendido}, data de nascimento {atendido_nascimento}[[, portador(a) do documento de "
             "identidade nº {atendido_documento}]], autorizo o acompanhamento psicoterapêutico e os encaminhamentos "
             "cabíveis.\n\nTodas as intervenções e documentos produzidos serão regidos pelos dispositivos legais "
             "vigentes, em especial pelo disposto na Resolução CFP nº 10, de 2005 (Código de Ética Profissional do "
             "Psicólogo), bem como pelas demais Resoluções da Psicologia relacionadas ao exercício da profissão."
             "\n\nEm especial, serão garantidos à(s) criança(s) ou adolescente(s) o sigilo das informações e a "
             "preservação da dignidade e da intimidade durante a prestação dos serviços de que trata esta "
             "autorização.",
    resumo="O responsável legal autoriza, por escrito, o acompanhamento psicoterapêutico do menor de 18 anos e os "
           "encaminhamentos cabíveis.",
    prerequisito="Colha antes de iniciar o acompanhamento e guarde no registro documental, protocolada.",
    orientacoes=(
        Orientacao("Por que é exigida",
                   "A Res. CFP nº 13/2022 traz o modelo de autorização como anexo. O atendimento de criança e "
                   "adolescente envolve dois direitos ao mesmo tempo: o sigilo de quem é atendido e o direito à "
                   "informação de quem responde legalmente por ele."),
        Orientacao("O que o termo garante",
                   "Que as intervenções e os documentos seguem o Código de Ética (Res. CFP nº 10/2005) e as "
                   "demais resoluções, com sigilo das informações e preservação da dignidade e da intimidade da "
                   "criança ou adolescente."),
        Orientacao("Quem assina",
                   "O responsável legal e a(o) psicóloga(o). Havendo guarda compartilhada ou disputa, confira "
                   "quem detém a guarda — o sistema guarda isso na ficha do paciente."),
    ),
    secoes=(
        Secao("Responsável legal", (
            Campo("responsavel", "Nome completo do responsável legal", "Quem autoriza o atendimento."),
            Campo("responsavel_nascimento", "Data de nascimento do responsável", "Como no documento de identidade.",
                  tipo=DATA),
            Campo("responsavel_documento", "Documento de identidade do responsável", "Número e órgão emissor."),
            Campo("responsavel_endereco", "Endereço do responsável", "Onde o responsável é domiciliado."),
        )),
        Secao("Criança ou adolescente", (
            Campo("atendido", "Nome completo da criança ou adolescente", "Quem será atendido.",
                  origem="paciente.nome"),
            Campo("atendido_nascimento", "Data de nascimento", "Da criança ou adolescente.", tipo=DATA,
                  origem="paciente.data_nascimento"),
            Campo("atendido_documento", "Documento de identidade", "Opcional, se houver.", obrigatorio=False,
                  origem="paciente.cpf"),
        )),
        _encerramento(),
    ),
)

ENCAMINHAMENTO = ModeloDeDocumento(
    codigo="encaminhamento", nome="Encaminhamento", grupo="apoio",
    norma="Res. CFP nº 01/2009 — registro de encaminhamento", titulo_impresso="ENCAMINHAMENTO",
    gabarito="Encaminha-se para atendimento em {destino}[[ ({destino_contato})]], em razão de {motivo}.\n\n"
             "Pessoa encaminhada: {atendido}[[\nData de nascimento: {atendido_nascimento}]]"
             "[[\nResponsável: {responsavel}]]\n\nEm caso de dúvidas e necessidade de esclarecimentos, entrar em "
             "contato por {contato}.",
    resumo="Encaminha a pessoa atendida a outro serviço ou profissional, com os dados para contato.",
    prerequisito="O encaminhamento também é registrado no prontuário, com a justificativa — faz parte da "
                 "estrutura mínima do registro.",
    orientacoes=(
        Orientacao("O que vai e o que não vai",
                   "Identificação da pessoa, o serviço de destino e o motivo do encaminhamento em termos gerais. "
                   "Informação clínica detalhada vai por relatório, a pedido e com as cautelas de sigilo."),
        Orientacao("Por que registrar",
                   "O registro de encaminhamento ou encerramento é um dos quatro itens da estrutura mínima do "
                   "prontuário (Res. CFP nº 01/2009). Guarde a via entregue, de preferência com protocolo."),
    ),
    secoes=(
        Secao("Conteúdo", (
            Campo("destino", "Serviço ou profissional de destino", "Para onde a pessoa está sendo encaminhada."),
            Campo("destino_contato", "Endereço e telefone do destino", "Opcional, para facilitar o acesso.",
                  obrigatorio=False),
            Campo("motivo", "Motivo do encaminhamento",
                  "Em termos gerais. Ex.: \"necessidade de avaliação psiquiátrica\", \"indisponibilidade de "
                  "vaga\", \"demanda de serviço especializado\". Sem detalhe clínico."),
            Campo("atendido", "Nome da pessoa encaminhada", "Nome completo ou nome social.", origem="paciente.nome"),
            Campo("atendido_nascimento", "Data de nascimento",
                  "Ajuda o serviço de destino a identificar a pessoa encaminhada; pode ficar em branco.",
                  tipo=DATA, obrigatorio=False,
                  origem="paciente.data_nascimento"),
            Campo("responsavel", "Responsável", "Opcional. Para criança, adolescente ou pessoa interditada.",
                  obrigatorio=False),
            Campo("contato", "Contato para dúvidas", "O seu telefone ou e-mail profissional, para o serviço de "
                  "destino falar com você.", origem="psicologo.contato"),
        )),
        _encerramento(),
    ),
)


CATALOGO = (DECLARACAO, ATESTADO, RELATORIO, LAUDO, PARECER, TERMO_DE_ENTREGA, AUTORIZACAO_MENOR, ENCAMINHAMENTO)
_POR_CODIGO = {modelo.codigo: modelo for modelo in CATALOGO}


def obter(codigo: str) -> ModeloDeDocumento | None:
    return _POR_CODIGO.get(codigo)


# --- Composição: dos campos preenchidos ao documento impresso ---------------------------------------------------------

def _data_por_extenso(valor: str) -> str:
    """`2025-05-31` → `31 de maio de 2025`. O que não for data ISO volta como veio.

    Minúsculo de propósito: em português o mês não leva maiúscula, e o Django o devolve capitalizado.
    """
    try:
        return dateformat.format(date.fromisoformat(valor), r"j \d\e F \d\e Y").lower()
    except (TypeError, ValueError):
        return valor or ""


def _v(dados: dict, nome: str) -> str:
    return (dados.get(nome) or "").strip()


_CAMPO = re.compile(r"\{(\w+)\}")
_TRECHO_OPCIONAL = re.compile(r"\[\[(.*?)\]\]", re.S)


def segmentos(gabarito: str) -> list:
    """O gabarito em pedaços, para a folha de preencher: `("texto", "Declara-se…")` e `("campo", "finalidade")`.

    Na folha de preencher o trecho opcional aparece inteiro — é ali que o campo dele é preenchido; só na impressão
    ele some quando fica vazio.
    """
    plano = _TRECHO_OPCIONAL.sub(lambda trecho: trecho.group(1), gabarito)
    pedacos, posicao = [], 0
    for achado in _CAMPO.finditer(plano):
        if achado.start() > posicao:
            pedacos.append(("texto", plano[posicao:achado.start()]))
        pedacos.append(("campo", achado.group(1)))
        posicao = achado.end()
    if posicao < len(plano):
        pedacos.append(("texto", plano[posicao:]))
    return pedacos


def _corpo_corrido(modelo: ModeloDeDocumento, d: dict) -> str:
    """O gabarito com os valores no lugar. Data sai por extenso; trecho opcional sem valor não sai."""
    tipos = {campo.nome: campo.tipo for campo in modelo.campos}

    def valor(nome: str) -> str:
        return _data_por_extenso(_v(d, nome)) if tipos.get(nome) == DATA else _v(d, nome)

    def trecho_opcional(achado) -> str:
        trecho = achado.group(1)
        if not all(valor(nome) for nome in _CAMPO.findall(trecho)):
            return ""
        return _CAMPO.sub(lambda campo: valor(campo.group(1)), trecho)

    texto = _TRECHO_OPCIONAL.sub(trecho_opcional, modelo.gabarito)
    return _CAMPO.sub(lambda campo: valor(campo.group(1)), texto)


_ROTULOS_DA_IDENTIFICACAO = [
    ("atendido", "Pessoa ou instituição atendida"), ("solicitante", "Solicitante"), ("finalidade", "Finalidade"),
    ("autor", "Autora(or)"), ("titulacao", "Titulação"), ("outras_informacoes", "Outras informações"),
]


def compor(modelo: ModeloDeDocumento, dados: dict) -> dict:
    """O documento pronto para imprimir: título, subtítulo, blocos e o encerramento."""
    blocos = []
    if modelo.itemizado:
        linhas = [f"{rotulo}: {_v(dados, nome)}" for nome, rotulo in _ROTULOS_DA_IDENTIFICACAO if _v(dados, nome)]
        blocos.append(("Identificação", "\n".join(linhas)))
        for secao in modelo.secoes:
            if secao.titulo in ("Identificação", "Encerramento"):
                continue
            texto = "\n\n".join(_v(dados, campo.nome) for campo in secao.campos if _v(dados, campo.nome))
            blocos.append((secao.titulo, texto))
    else:
        blocos.append(("", _corpo_corrido(modelo, dados)))
    return {
        "titulo": modelo.titulo_impresso, "subtitulo": _v(dados, "subtitulo"), "blocos": blocos,
        "local_e_data": ", ".join(parte for parte in [_v(dados, "local"), _data_por_extenso(_v(dados, "data"))]
                                  if parte),
        "assinatura_nome": _v(dados, "psicologo_nome"), "assinatura_crp": _v(dados, "psicologo_crp"),
        "segunda_assinatura": {"termo-de-entrega": "Assinatura de quem recebeu o documento",
                               "autorizacao-crianca-adolescente": "Responsável legal pela criança ou adolescente",
                               }.get(modelo.codigo, ""),
        "tracos": modelo.preenche_com_tracos,
    }
