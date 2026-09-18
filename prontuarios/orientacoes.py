"""O que o CFP espera do prontuário — e por quê (ADR-079).

Mesma regra da aba de documentos (ADR-033, ADR-076): a Res. CFP nº 001/2009 é ato oficial e pode ser citada; o
Manual Orientativo do CFP (2025) é obra protegida, e por isso aqui ele é **fonte e link** — os textos abaixo são
redação nossa, não trecho dele. Norma exibida leva a versão em que se apoia.
"""

from dataclasses import dataclass

RESOLUCAO_01_2009 = "https://site.cfp.org.br/wp-content/uploads/2009/04/resolucao2009_01.pdf"
MANUAL_CFP = "https://site.cfp.org.br/wp-content/uploads/2025/11/Manual_Orientativo.pdf"
VERSAO_DA_NORMA = "Res. CFP nº 001/2009 · Manual Orientativo do CFP, 1ª ed., 2025"

TITULO = "PRONTUÁRIO PSICOLÓGICO"
RESUMO = ("O prontuário reúne, por pessoa atendida, o que permite conhecer e acompanhar o trabalho: quem é atendido, "
          "por que e para quê, como o trabalho evoluiu e como terminou. Registrar é obrigatório em todo serviço "
          "psicológico.")
ANTES = ("O prontuário é também da pessoa atendida: ela, ou o responsável legal, pode pedir acesso e cópia. Escreva "
         "sabendo que ela pode ler.")


@dataclass(frozen=True)
class Orientacao:
    titulo: str
    texto: str


ORIENTACOES = (
    Orientacao(
        "Quatro partes, e nenhuma é opcional",
        "A Res. CFP nº 001/2009 (Art. 2º) pede: identificação; avaliação da demanda e definição dos objetivos do "
        "trabalho; evolução do trabalho, com os procedimentos técnico-científicos adotados; e registro de "
        "encaminhamento ou encerramento. O Manual de 2025 avisa que prontuário sem essa estrutura precisa de "
        "adequação numa fiscalização — por isso a folha ao lado já vem com as quatro."),
    Orientacao(
        "Evolução é síntese, não transcrição",
        "Cada atendimento ganha um registro datado, breve, com o que foi trabalhado e o procedimento usado. Não se "
        "transcreve a sessão nem se acumula detalhe íntimo que não serve ao acompanhamento: o registro existe para "
        "que o trabalho possa ser conhecido e continuado, e o sigilo pede o mínimo necessário."),
    Orientacao(
        "O que não vai no prontuário",
        "Hipótese diagnóstica ainda não compartilhada, impressão pessoal e interpretação em elaboração pertencem ao "
        "registro documental de uso exclusivo da psicóloga, e não ao prontuário — porque o prontuário pode ser "
        "entregue à pessoa atendida. Protocolos e folhas de teste também ficam em pasta de acesso exclusivo "
        "(Art. 2º, V). O Hamilton ainda não tem esse registro restrito: guarde-o à parte."),
    Orientacao(
        "Linguagem",
        "Escrita formal, técnica e compreensível por quem não é da área. Escolha a forma pessoal ou a impessoal e "
        "mantenha a mesma do começo ao fim. Afirmação sobre a pessoa se apoia no que foi observado ou relatado, "
        "dizendo de quem veio a informação."),
    Orientacao(
        "Quando registrar, e por quanto tempo guardar",
        "Registre logo depois do atendimento: registro tardio perde valor de prova. A guarda é de no mínimo cinco "
        "anos a contar do último registro (Art. 4º); de criança e adolescente, até a maioridade e então os prazos "
        "gerais; em serviço de saúde, a Lei nº 13.787/2018 fala em vinte anos."),
    Orientacao(
        "Integridade",
        "O prontuário é prova em processo ético e judicial. Não se deixam espaços em branco nem se apaga o que foi "
        "escrito. Aqui, editar qualquer parte guarda a redação anterior, com data — é isso que sustenta a "
        "autenticidade do registro eletrônico."),
)

AJUDA_DEMANDA = ("O que trouxe a pessoa ao atendimento, como você avaliou essa demanda e o que ficou definido como "
                 "objetivo do trabalho. Escreva-se uma vez e atualiza-se quando o objetivo mudar. Hipótese ainda não "
                 "compartilhada com a pessoa não entra aqui.")
AJUDA_EVOLUCAO = ("Síntese deste atendimento: o que foi trabalhado e os procedimentos técnico-científicos adotados. "
                  "Não é transcrição — registre o essencial para que o trabalho possa ser acompanhado, de preferência "
                  "logo depois da sessão.")
AJUDA_ENCERRAMENTO = ("Preencha quando houver encaminhamento a outro profissional ou serviço, ou quando o atendimento "
                      "terminar: data, motivo, de quem partiu a decisão e as orientações dadas. Enquanto o trabalho "
                      "segue, fica em branco.")
