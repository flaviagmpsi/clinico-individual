"""Catálogo fechado de abordagens e de outras áreas de atuação (ADR-107).

Por que voltar a ser lista fechada, depois de a ADR-094 ter aberto para texto livre: **contagem**. Escrito à mão,
"Psicanálise", "psicanálise" e "Psicanalise" são três respostas diferentes, e não dá para saber quantas pessoas de
cada abordagem usam o sistema. O que se guarda é o **código**, não o rótulo: se um dia o texto na tela mudar
("Sistêmica" virar "Sistêmica / familiar"), a contagem continua inteira.

Duas fronteiras que o catálogo mantém de propósito:

- **Abordagem é como a pessoa trabalha; área é o que ela faz além da clínica.** Avaliação neuropsicológica é
  área, não abordagem — se estivesse nas duas listas, a mesma pessoa seria contada duas vezes e nenhum dos dois
  números fecharia. ABA ficou nas abordagens porque quem é ABA se apresenta assim.
- **Quem não está na lista marca OUTRA e escreve.** Sem essa saída, um psicólogo de abordagem não prevista trava
  no cadastro ou marca algo errado — e aí a contagem fica pior do que era com texto livre. O que vem por OUTRA
  fica separado, para ser lido de vez em quando e promovido quando repetir.
"""

import unicodedata

# --- abordagens -------------------------------------------------------------------------------------------------
# Em ordem alfabética pelo rótulo, com OUTRA por último: a lista é lida procurando um nome conhecido.
# "Humanista-existencial", "abordagem centrada na pessoa", "fenomenologia existencial" e "daseinsanálise" são da
# mesma família, e estão separadas de propósito — quem se identifica com uma não se identifica com as outras.
OUTRA = "OUTRA"

ABORDAGENS: tuple[tuple[str, str], ...] = (
    ("ABA", "ABA (análise do comportamento aplicada)"),
    ("CENTRADA_NA_PESSOA", "Abordagem centrada na pessoa"),
    ("ACT", "ACT (terapia de aceitação e compromisso)"),
    ("ANALISE_DO_COMPORTAMENTO", "Análise do comportamento"),
    ("DASEINSANALISE", "Daseinsanálise"),
    ("FENOMENOLOGIA_EXISTENCIAL", "Fenomenologia existencial"),
    ("GESTALT", "Gestalt-terapia"),
    ("HUMANISTA_EXISTENCIAL", "Humanista-existencial"),
    ("LOGOTERAPIA", "Logoterapia"),
    ("PSICANALISE", "Psicanálise"),
    ("PSICODRAMA", "Psicodrama"),
    ("PSICOLOGIA_ANALITICA", "Psicologia analítica"),
    ("PSICOLOGIA_COGNITIVA", "Psicologia cognitiva"),
    ("PSICOLOGIA_SOCIAL_CRITICA", "Psicologia social crítica"),
    ("SISTEMICA", "Sistêmica"),
    ("TCC", "Terapia cognitivo-comportamental (TCC)"),
    ("DBT", "Terapia comportamental dialética (DBT)"),
    ("TERAPIA_DO_ESQUEMA", "Terapia do esquema"),
    (OUTRA, "Outra"),
)

# --- outras áreas de atuação ------------------------------------------------------------------------------------
# O que a pessoa faz **além** da clínica. Fechada pelo mesmo motivo das abordagens.
AREAS: tuple[tuple[str, str], ...] = (
    ("AVALIACAO_NEUROPSICOLOGICA", "Avaliação neuropsicológica"),
    ("AVALIACAO_PSICOLOGICA", "Avaliação psicológica e laudos"),
    ("DOCENCIA", "Docência e formação"),
    ("ORIENTACAO_PROFISSIONAL", "Orientação profissional e de carreira"),
    ("PSICOLOGIA_DO_ESPORTE", "Psicologia do esporte"),
    ("PSICOLOGIA_HOSPITALAR", "Psicologia hospitalar"),
    ("PSICOLOGIA_JURIDICA", "Psicologia jurídica e perícia"),
    ("PSICOLOGIA_ORGANIZACIONAL", "Psicologia organizacional"),
    ("SUPERVISAO", "Supervisão clínica"),
    (OUTRA, "Outra"),
)

ROTULO_DA_ABORDAGEM = dict(ABORDAGENS)
ROTULO_DA_AREA = dict(AREAS)


def _chave(texto: str) -> str:
    """Reduz um texto ao que importa para comparar: sem acento, sem maiúscula, sem pontuação, sem espaço sobrando."""
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    limpo = "".join(c if c.isalnum() else " " for c in sem_acento.casefold())
    return " ".join(limpo.split())


# Nomes que a mesma abordagem recebe por aí, para converter o que já foi escrito à mão sem perder ninguém.
# Os rótulos da lista fechada anterior (ADR-071) estão aqui porque a migração 0009 os gravou como texto.
_APELIDOS_DE_ABORDAGEM = {
    "analise do comportamento aplicada": "ABA",
    "aba analise do comportamento aplicada": "ABA",
    "abordagem centrada na pessoa humanista": "CENTRADA_NA_PESSOA",
    "acp": "CENTRADA_NA_PESSOA",
    "centrada na pessoa": "CENTRADA_NA_PESSOA",
    "terapia de aceitacao e compromisso": "ACT",
    "analise comportamental": "ANALISE_DO_COMPORTAMENTO",
    "behaviorismo": "ANALISE_DO_COMPORTAMENTO",
    "dasein analise": "DASEINSANALISE",
    "analise do dasein": "DASEINSANALISE",
    "fenomenologico existencial": "FENOMENOLOGIA_EXISTENCIAL",
    "existencial fenomenologica": "FENOMENOLOGIA_EXISTENCIAL",
    "gestalt": "GESTALT",
    "humanista": "HUMANISTA_EXISTENCIAL",
    "existencial humanista": "HUMANISTA_EXISTENCIAL",
    "psicanalise lacaniana": "PSICANALISE",
    "psicanalise freudiana": "PSICANALISE",
    "psicologia analitica junguiana": "PSICOLOGIA_ANALITICA",
    "junguiana": "PSICOLOGIA_ANALITICA",
    "analitica": "PSICOLOGIA_ANALITICA",
    "psicologia social critica": "PSICOLOGIA_SOCIAL_CRITICA",
    "sistemica familiar": "SISTEMICA",
    "terapia sistemica": "SISTEMICA",
    "terapia familiar": "SISTEMICA",
    "terapia cognitivo comportamental": "TCC",
    "cognitivo comportamental": "TCC",
    "terapia comportamental dialetica": "DBT",
    "terapia do esquema": "TERAPIA_DO_ESQUEMA",
    "schema therapy": "TERAPIA_DO_ESQUEMA",
}

_APELIDOS_DE_AREA = {
    "avaliacao neuropsicologica": "AVALIACAO_NEUROPSICOLOGICA",
    "neuropsicologia": "AVALIACAO_NEUROPSICOLOGICA",
    "avaliacao psicologica": "AVALIACAO_PSICOLOGICA",
    "psicodiagnostico": "AVALIACAO_PSICOLOGICA",
    "laudos": "AVALIACAO_PSICOLOGICA",
    "docencia": "DOCENCIA",
    "orientacao profissional": "ORIENTACAO_PROFISSIONAL",
    "orientacao vocacional": "ORIENTACAO_PROFISSIONAL",
    "psicologia do esporte": "PSICOLOGIA_DO_ESPORTE",
    "psicologia hospitalar": "PSICOLOGIA_HOSPITALAR",
    "psicologia juridica": "PSICOLOGIA_JURIDICA",
    "pericia": "PSICOLOGIA_JURIDICA",
    "psicologia organizacional": "PSICOLOGIA_ORGANIZACIONAL",
    "recursos humanos": "PSICOLOGIA_ORGANIZACIONAL",
    "supervisao": "SUPERVISAO",
    "supervisao clinica": "SUPERVISAO",
}


def _de_texto(texto: str, catalogo, apelidos) -> str | None:
    """O código que corresponde a um texto escrito à mão, ou None se não for nenhum dos conhecidos."""
    chave = _chave(texto)
    if not chave:
        return None
    for codigo, rotulo in catalogo:
        if codigo != OUTRA and chave == _chave(rotulo):
            return codigo
    return apelidos.get(chave)


def codigo_da_abordagem(texto: str) -> str | None:
    return _de_texto(texto, ABORDAGENS, _APELIDOS_DE_ABORDAGEM)


def codigo_da_area(texto: str) -> str | None:
    return _de_texto(texto, AREAS, _APELIDOS_DE_AREA)


def descrever(codigos, rotulos: dict, escrito: str = "") -> str:
    """Os rótulos, na ordem do catálogo, com o que veio por OUTRA no fim. Para mostrar, nunca para contar."""
    escolhidos = set(codigos or [])
    nomes = [rotulo for codigo, rotulo in rotulos.items() if codigo in escolhidos and codigo != OUTRA]
    if OUTRA in escolhidos and escrito:
        nomes.append(escrito)
    return ", ".join(nomes)
