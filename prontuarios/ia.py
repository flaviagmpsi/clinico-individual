"""A IA que ajuda a escrever o registro de sessão (ADR-111).

O caminho é: o psicólogo grava **um áudio** (ou escreve) respondendo a quatro pontos; o áudio é transcrito; a
transcrição é **anonimizada por código**; e só então ela vai para o modelo, que devolve o corpo do registro de
evolução no padrão do CFP. O texto volta como **rascunho editável** — quem assina o prontuário é o psicólogo, e
nada é confirmado sem ele ler.

Baseado no `prontuario-exyo`, de Arthur Pinho (github.com/arthurbpinho/prontuario-exyo), usado com autorização.
Três coisas mudaram em relação ao original, e cada uma por um motivo:

1. **São quatro pontos, não cinco.** O quinto do original — hipóteses e notas de supervisão — virou instrução do
   que **não** dizer. Hipótese não compartilhada e contratransferência não entram em prontuário (Res. CFP 01/2009,
   e Manual Orientativo, pág. 18): são registro privativo, que o Hamilton ainda não tem (P-84). Enquanto não
   tiver, o caminho certo é não coletá-las, e não coletá-las e guardá-las no lugar errado.
2. **A IA não escreve identificação.** O original abria o documento com um bloco de identificação gerado pelo
   modelo. Aqui ela escreve só o corpo: nome, nascimento, CPF, CRP, data e assinatura já são montados **por
   código**, a partir do banco, em `documentos/prontuario.html`. Dado de identificação não passa por modelo de
   linguagem nenhum — e o que não é enviado não pode ser vazado nem inventado.
3. **A transcrição é anonimizada antes da síntese.** O sistema sabe como o paciente se chama, então troca o nome
   por "a paciente" sem depender de o modelo lembrar de fazê-lo. A instrução no prompt continua, como segunda
   camada, para o apelido ou o nome de terceiro que o sistema não conhece.

⚠️ **O áudio cru vai para a API da OpenAI para ser transcrito.** Se o psicólogo escorregar e falar um nome, a
anonimização daqui protege a síntese e o documento final, não a transcrição. Isso é consequência de usar a API em
vez de um modelo local, foi decidido com o custo em vista, e precisa estar dito no aviso de privacidade.
"""

import re
import unicodedata
from dataclasses import dataclass

from django.conf import settings

# --- o que se pede ao psicólogo ---------------------------------------------------------------------------------
# Quatro pontos, um áudio só. O texto é o que aparece na tela, e é a mesma lista que o prompt espera encontrar na
# transcrição — se um dia mudar aqui, muda nos dois lugares de uma vez.
PONTOS: tuple[tuple[str, str], ...] = (
    ("Demanda e tema central",
     "Qual foi a queixa ativa, a situação-problema ou o tema trabalhado hoje?"),
    ("Intervenções e procedimentos técnicos",
     "Quais técnicas ou recursos da sua abordagem você aplicou? (Ex.: escuta qualificada, questionamento "
     "reflexivo, reestruturação, interpretação, psicoeducação, manejo de regulação emocional.)"),
    ("Evolução e resposta do paciente",
     "Como o paciente reagiu? Descreva o estado geral observado (humor, nível de elaboração, compreensão, "
     "adesão ou resistências)."),
    ("Encaminhamentos e próximos passos",
     "Houve alguma intercorrência ou encaminhamento externo (médico, psiquiátrico, rede)? O que ficou combinado "
     "e qual o plano para a próxima sessão?"),
)

AVISO_DE_SIGILO = (
    "Evite citar nomes do paciente e de terceiros (diga, por exemplo, “minha paciente”), evite hipóteses e "
    "opiniões próprias — essas são para a supervisão — e cite apenas o estritamente necessário para o caso."
)

# --- o prompt ----------------------------------------------------------------------------------------------------
PROMPT_DO_SISTEMA = """Você é um especialista sênior em Psicologia Clínica e em normativas documentais do Conselho \
Federal de Psicologia do Brasil (CFP), incluindo a Resolução CFP nº 01/2009, a Resolução CFP nº 06/2019 e o Manual \
Orientativo de Registro e Elaboração de Documentos Psicológicos.

Você recebe o relato que o(a) psicólogo(a) fez logo após uma sessão, em linguagem falada, e o transforma no
REGISTRO DE EVOLUÇÃO daquela sessão, que compõe o prontuário do paciente.

REGRAS ABSOLUTAS:
- NÃO escreva bloco de identificação: nada de nome, data de nascimento, CPF, RG, telefone, endereço, número de
  sessão, data, nome do profissional ou CRP. Esses dados são inseridos pelo sistema, fora deste texto.
- Se algum nome próprio aparecer no relato, NÃO o reproduza: escreva "o paciente", "a paciente" ou "um familiar".
- NÃO faça transcrição literal de falas do paciente — transcrição literal não é evolução (Res. CFP 01/2009, Art. 2º).
- NÃO inclua hipóteses diagnósticas não compartilhadas com o paciente, contratransferência nem sentimentos íntimos
  do profissional. Isso é registro privativo de supervisão e não pertence ao prontuário.
- NÃO invente NADA, em hipótese nenhuma. Se o relato não disser nada sobre um dos quatro tópicos, escreva
  exatamente esta frase e mais nada naquela seção: "Sem registro sobre este ponto nesta sessão."
  Não complete com o que seria plausível, esperado ou clinicamente coerente. Não escreva "não houve
  intercorrências" se o relato não disse isso — ausência de menção não é negação. Documento honesto e incompleto
  é melhor que documento inventado: este texto é meio de prova em processo disciplinar.
- A abordagem do profissional é informada apenas como CONTEXTO, para você escolher o vocabulário adequado. NÃO
  afirme que uma técnica "pertence a" ou é "de acordo com" a abordagem dele. Descreva as intervenções como foram
  relatadas, sem atribuí-las a nenhuma escola teórica — a menos que o próprio relato faça essa ligação.
- Linguagem formal, técnica, impessoal e respeitosa. Português do Brasil.

ESTRUTURA OBRIGATÓRIA DA RESPOSTA (exatamente estes quatro títulos, em Markdown, sem nada antes nem depois):

**Avaliação da demanda e enquadre da sessão**
[Síntese técnica da queixa ativa, do conteúdo temático ou da situação-problema trabalhada neste encontro.]

**Procedimentos técnico-científicos e intervenções adotadas**
[Intervenções clínicas, manejo técnico e recursos utilizados, exatamente como relatados, sem atribuí-los a
nenhuma escola teórica.]

**Evolução e resposta do paciente**
[Estado geral, elaboração, compreensão, adesão, recursos psíquicos mobilizados e manifestações relevantes.]

**Encaminhamentos, intercorrências e continuidade**
[Combinados intersessão, encaminhamentos ou ausência de intercorrências, e planejamento da continuidade.]"""

_CONECTIVOS = {"de", "da", "do", "das", "dos", "e", "di", "du", "del", "van", "von", "la", "le"}
_MODELO_PADRAO = "gpt-4o"
_TAMANHO_MAXIMO_DO_AUDIO = 25 * 1024 * 1024   # o limite da própria API de transcrição


class IAIndisponivel(RuntimeError):
    """Sem chave configurada, ou a OpenAI recusou a chamada. Quem chama decide o que mostrar na tela."""


@dataclass(frozen=True)
class Contexto:
    """O que a IA pode saber sobre a sessão — e note que não há nada aqui que identifique alguém."""

    abordagem: str = ""
    modalidade: str = ""
    frequencia: str = ""
    numero_da_sessao: int | None = None

    def como_texto(self) -> str:
        partes = []
        if self.abordagem:
            # "Declarada" de propósito: sem esse cuidado o modelo passa a afirmar que cada técnica relatada
            # pertence a essa abordagem — e escreveu "psicoeducação de acordo com a Gestalt-terapia" num teste.
            partes.append(f"Abordagem declarada pelo profissional (apenas contexto de vocabulário, "
                          f"não atribua técnicas a ela): {self.abordagem}.")
        if self.modalidade:
            partes.append(f"Modalidade do atendimento: {self.modalidade}.")
        if self.frequencia:
            partes.append(f"Frequência combinada: {self.frequencia}.")
        if self.numero_da_sessao:
            partes.append(f"É a {self.numero_da_sessao}ª sessão registrada deste paciente.")
        return " ".join(partes)


def chave() -> str:
    return (getattr(settings, "OPENAI_API_KEY", "") or "").strip()


def disponivel() -> bool:
    """Sem chave, a tela não oferece o recurso — em vez de oferecer e falhar no clique."""
    return bool(chave())


def _cliente():
    from openai import OpenAI   # importado aqui: quem não usa IA não paga o custo de carregar a biblioteca

    return OpenAI(api_key=chave())


# --- anonimização, feita por código -----------------------------------------------------------------------------
def _sem_acento(texto: str) -> str:
    """Tira acento **mantendo uma posição para cada posição** do texto original.

    A versão ingênua — normalizar a string inteira e filtrar os acentos — pode mudar o tamanho, porque há
    caracteres que se decompõem em vários ("ﬁ" vira "fi", "ß" vira "ss"). Como a busca acontece no texto sem
    acento e o recorte no texto original, um caractere a mais desalinharia tudo dali em diante e cortaria a
    frase no lugar errado. Dobrando caractere a caractere, os dois textos têm sempre o mesmo comprimento.
    """
    dobrados = []
    for c in texto:
        limpo = "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
        dobrados.append(limpo[:1] or c)
    return "".join(dobrados)


def _pedacos_do_nome(nome: str) -> list[str]:
    """As partes de um nome que valem procurar no texto, da mais longa para a mais curta.

    Conectivos ("de", "da") e pedaços de até duas letras ficam de fora: sozinhos não identificam ninguém e
    estragariam o texto ao redor.
    """
    partes = [p for p in re.split(r"\s+", nome.strip()) if len(p) > 2 and p.casefold() not in _CONECTIVOS]
    return sorted(partes, key=len, reverse=True)


def anonimizar(texto: str, *, nomes: list[str], substituto: str = "[nome omitido]") -> str:
    """Tira do texto os nomes que o sistema conhece, antes de ele sair da máquina.

    Procura primeiro o nome inteiro e depois cada parte dele, da mais longa para a mais curta — assim "Maria
    Clara Souza" vira um substituto só, e não três emendados. Acento é sempre ignorado, porque a transcrição
    erra acento o tempo todo.

    **Maiúscula, porém, não é ignorada quando o alvo é uma palavra só** — e isso é uma decisão, não um descuido.
    Muito nome brasileiro também é substantivo comum: Vitória, Rosa, Campos, Leão, Pinto, Coelho. Ignorando a
    caixa, "contou uma vitória no trabalho" virava "contou uma [nome omitido] no trabalho", e o relato chegava
    corrompido ao modelo — em silêncio, porque ninguém compara o antes com o depois. Exigir inicial maiúscula
    separa o nome próprio do substantivo, que é como a escrita já os separa.
    O nome **composto** continua sendo procurado sem olhar a caixa: "vitória campos" em sequência não é frase
    de ninguém. Fica um buraco conhecido — o primeiro nome sozinho e em minúscula escapa —, e quem o fecha é a
    instrução do prompt, que manda o modelo não reproduzir nome próprio nenhum.
    """
    if not texto:
        return texto
    compostos: list[str] = []
    isolados: list[str] = []
    for nome in nomes:
        nome = " ".join((nome or "").split())
        if not nome:
            continue
        if len(nome.split()) > 1:
            compostos.append(nome)
        elif len(nome) > 2:
            isolados.append(nome)
        isolados.extend(_pedacos_do_nome(nome))

    resultado = texto
    for alvo in sorted(set(compostos), key=len, reverse=True):
        resultado = _trocar(resultado, alvo, substituto, so_com_maiuscula=False)
    for alvo in sorted(set(isolados), key=len, reverse=True):
        resultado = _trocar(resultado, alvo, substituto, so_com_maiuscula=True)
    return resultado


def _trocar(texto: str, alvo: str, substituto: str, *, so_com_maiuscula: bool) -> str:
    """Troca `alvo` por `substituto` em `texto`, comparando sem acento e recortando o texto original."""
    # `\b` em volta para não comer pedaço de palavra maior — "Ana" não casa dentro de "ananás".
    padrao = re.compile(rf"\b{re.escape(_sem_acento(alvo))}\b", re.IGNORECASE)
    sem_acento = _sem_acento(texto)   # mesmo comprimento do original, por construção
    pedacos, fim = [], 0
    for achado in padrao.finditer(sem_acento):
        if so_com_maiuscula and not texto[achado.start()].isupper():
            continue
        pedacos.append(texto[fim:achado.start()])
        pedacos.append(substituto)
        fim = achado.end()
    if not pedacos:
        return texto
    pedacos.append(texto[fim:])
    return "".join(pedacos)


# --- transcrição -------------------------------------------------------------------------------------------------
def transcrever(arquivo, *, nome: str = "sessao.webm") -> str:
    """Transcreve o áudio pela API da OpenAI e devolve o texto. O arquivo **não** é guardado por nós."""
    if not disponivel():
        raise IAIndisponivel("A transcrição precisa de uma chave da OpenAI configurada.")
    dados = arquivo.read() if hasattr(arquivo, "read") else arquivo
    if not dados:
        raise IAIndisponivel("O áudio chegou vazio.")
    if len(dados) > _TAMANHO_MAXIMO_DO_AUDIO:
        raise IAIndisponivel("O áudio passou de 25 MB. Grave um relato mais curto — bastam alguns minutos.")
    try:
        resposta = _cliente().audio.transcriptions.create(
            model=getattr(settings, "OPENAI_MODELO_DE_AUDIO", "whisper-1"),
            file=(nome, dados),
            language="pt",
        )
    except Exception as erro:                       # a biblioteca tem uma árvore de erros grande; a tela só precisa
        raise IAIndisponivel(_recado(erro)) from erro   # saber que não deu e por quê, em português
    return (getattr(resposta, "text", "") or "").strip()


# --- síntese -----------------------------------------------------------------------------------------------------
def sintetizar(relato: str, *, contexto: Contexto | None = None) -> str:
    """O corpo do registro de evolução, a partir do relato **já anonimizado**."""
    relato = (relato or "").strip()
    if not relato:
        raise IAIndisponivel("Não há relato para transformar em registro.")
    if not disponivel():
        raise IAIndisponivel("A escrita assistida precisa de uma chave da OpenAI configurada.")

    pedido = [(contexto or Contexto()).como_texto(),
              "",
              "Relato do profissional sobre a sessão (transcrito da fala, já sem nomes):",
              relato]
    try:
        resposta = _cliente().chat.completions.create(
            model=getattr(settings, "OPENAI_MODELO", _MODELO_PADRAO),
            messages=[{"role": "system", "content": PROMPT_DO_SISTEMA},
                      {"role": "user", "content": "\n".join(p for p in pedido if p is not None)}],
            temperature=0.2,   # documento técnico não quer criatividade
        )
    except Exception as erro:
        raise IAIndisponivel(_recado(erro)) from erro
    return (resposta.choices[0].message.content or "").strip()


def _recado(erro: Exception) -> str:
    """Traduz a falha da OpenAI para algo que o psicólogo entenda e possa resolver."""
    texto = str(erro).lower()
    if "insufficient_quota" in texto or "exceeded your current quota" in texto:
        return "A conta da OpenAI está sem crédito. O registro escrito à mão continua funcionando."
    if "invalid_api_key" in texto or "incorrect api key" in texto:
        return "A chave da OpenAI foi recusada. Confira a configuração do sistema."
    if "rate limit" in texto or "429" in texto:
        return "A OpenAI está limitando as chamadas agora. Tente de novo em um minuto."
    return "Não consegui falar com a OpenAI agora. O registro escrito à mão continua funcionando."
