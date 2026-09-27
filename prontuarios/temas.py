"""Os temas da anamnese (ADR-101): o roteiro é do psicólogo, e ele o edita.

Até aqui a anamnese tinha doze campos fixos no banco (ADR-085) — bons temas, mas de quem escreveu o sistema. O
usuário pediu o contrário: "terão os blocos que já estão lá, mas tem como adicionar mais blocos com tipos de temas e
assuntos, para que o psicólogo possa personalizar a anamnese".

Então o tema virou dado. Esta lista é só a **sugestão inicial**: é ela que cada conta recebe ao abrir a primeira
anamnese, e é ela que a migração usa para levar o que já estava escrito nos doze campos antigos. Depois disso, quem
manda é o psicólogo: acrescenta tema, renomeia, reordena e arquiva o que não usa.
"""

# (chave do campo antigo, título, ajuda). A chave amarra o tema ao campo que existia, para a migração não perder
# nada e para a semente continuar falando a mesma língua.
TEMAS_SUGERIDOS: tuple[tuple[str, str, str], ...] = (
    ("queixa_principal", "Queixa principal",
     "O que trouxe a pessoa, nas palavras dela."),
    ("historia_da_queixa", "História da queixa",
     "Quando começou, como evoluiu, o que piora e o que alivia, o que já tentou."),
    ("tratamentos_anteriores", "Tratamentos anteriores",
     "Psicoterapia, acompanhamento psiquiátrico, internações — quando, com quem, como foi."),
    ("saude_geral", "Saúde geral",
     "Doenças, cirurgias, condições crônicas e medicamentos em uso, conforme o relato."),
    ("sono_alimentacao_substancias", "Sono, alimentação e uso de substâncias",
     "Padrão de sono e de alimentação; álcool, tabaco e outras substâncias."),
    ("historia_familiar", "História familiar",
     "Com quem mora, composição da família, clima das relações, histórico de saúde mental."),
    ("desenvolvimento", "Desenvolvimento e infância",
     "Para criança e adolescente: gestação, parto, marcos do desenvolvimento, escola. "
     "Para adulto: o que for relevante da infância e da adolescência."),
    ("escolaridade_e_trabalho", "Escolaridade e trabalho",
     "Formação, ocupação atual, satisfação e dificuldades no trabalho ou nos estudos."),
    ("relacionamentos", "Relacionamentos e rede de apoio",
     "Vida afetiva, amizades, com quem conta quando precisa."),
    ("rotina_e_lazer", "Rotina e lazer",
     "Como é um dia comum; o que faz por prazer; atividade física."),
    ("expectativas", "Expectativas com a terapia",
     "O que espera da terapia, e o que seria melhorar."),
    ("observacoes", "Observações do psicólogo",
     "Impressões suas da entrevista. Lembre que isto é registro seu — não vai para o prontuário geral."),
)

CHAVES = tuple(chave for chave, _, _ in TEMAS_SUGERIDOS)
