"""O tour de boas-vindas (ADR-138): aparece uma vez, no primeiro painel depois do cadastro.

Os passos moram aqui, e não no template, para serem fáceis de reordenar e testar. Cada um tem um ícone (ilustração
por enquanto; o espaço para um screenshot real fica marcado no template) e um texto curto. Nada de dado sensível —
é só explicação do produto.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Passo:
    chave: str        # identifica o passo; também o nome do arquivo de imagem quando houver (img/tour/<chave>.png)
    icone: str        # classe do Bootstrap Icons, usada enquanto não há screenshot
    titulo: str
    texto: str


PASSOS: tuple[Passo, ...] = (
    Passo("bem_vindo", "bi-stars", "Bem-vindo ao Polaris",
          "Este é um tour rápido pelo que você pode fazer aqui. São poucos passos — no fim, é só começar a usar. "
          "Ele aparece só desta vez."),
    Passo("painel", "bi-speedometer2", "O painel responde “o que eu faço agora”",
          "Ao entrar, você vê a agenda de hoje e um bloco de pendências. É o seu ponto de partida todo dia."),
    Passo("pendencias", "bi-list-check", "Pendências: nada escapa",
          "O painel junta num lugar só o que espera por você: sessão que passou sem registro, pagamento vencido ou "
          "a receber, recibo a emitir, prontuário por escrever e ganho de fora a receber. Cada linha abre e leva "
          "direto para resolver."),
    Passo("agenda", "bi-calendar-week", "Agenda",
          "Suas sessões em formato de calendário. Você registra o que aconteceu em cada uma — presente, falta, "
          "cancelamento ou remarcação — e pode cadastrar a remarcação antes mesmo do horário."),
    Passo("horarios", "bi-clock", "Meus horários",
          "Você declara os horários em que atende, e a agenda mostra sozinha onde há vaga livre. Também é aqui que "
          "entram os compromissos fora da clínica, como supervisão e trabalho em ONG."),
    Passo("pacientes", "bi-people", "Pacientes e convite",
          "A ficha de cada paciente reúne cadastro, frequência, presença e situação financeira. E você pode mandar "
          "um link de convite para o próprio paciente preencher o cadastro."),
    Passo("prontuario", "bi-mic", "Prontuário por IA",
          "Grave um áudio contando como foi a sessão: o sistema transcreve e monta o registro de evolução no padrão "
          "do CFP, para você revisar e assinar. Escrever à mão continua valendo. (Ligue a escrita assistida em "
          "Configurações.)"),
    Passo("financeiro", "bi-cash-stack", "Financeiro",
          "As mensalidades e sessões viram cobranças automáticas a partir do combinado com cada paciente. Você "
          "registra os pagamentos, e o sistema mostra o que foi pago, o que falta e o que está vencido."),
    Passo("recibos", "bi-receipt", "Recibos e carnê-leão",
          "Ao registrar um pagamento, diga se já emitiu o recibo — se não, vira um lembrete. E as despesas da "
          "clínica já saem separadas pelo que entra no carnê-leão."),
    Passo("outros_ganhos", "bi-briefcase", "Outros ganhos",
          "Recebe por fora da clínica — supervisão, ONG, emprego CLT, um bico? Lance aqui. Conta como pendência até "
          "você marcar que recebeu, e entra na sua receita total do mês."),
    Passo("documentos", "bi-file-earmark-text", "Documentos",
          "Declarações, atestados e o prontuário geral que pode ser entregue ao paciente — com os seus dados e o "
          "timbre, prontos para imprimir."),
    Passo("aniversario", "bi-cake2", "Aniversário do paciente",
          "No dia do aniversário de um paciente em atendimento, ao abrir o sistema aparece um aviso para você não "
          "deixar passar. É rápido e some depois de fechado."),
    Passo("comecar", "bi-check2-circle", "Pronto!",
          "É isso. Você pode voltar a qualquer parte pelo menu à esquerda. Bom trabalho — e qualquer dúvida, cada "
          "tela tem textos de ajuda ao lado dos campos."),
)
