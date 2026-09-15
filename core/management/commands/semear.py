"""Popula o banco local com dois psicólogos e seus pacientes.

Existe por dois motivos, e o segundo é o que importa:

1. Dar o que ver nas telas sem cadastrar tudo à mão.
2. **Dois** psicólogos, e não um. Com um só, o isolamento da ADR-001 é indistinguível de um
   sistema que não isola nada. Entrando como a Ana e depois como o Bruno, a garantia deixa de
   ser afirmação em documento e vira coisa que se confere com os olhos.

Cadastra pelo serviço (`pacientes.servicos`), e não por `Paciente.objects.create`: é o serviço que
cria o caso individual em silêncio (ADR-026). Um paciente semeado sem caso seria um estado que o
produto nunca produz — e as telas mostrariam "Não combinada" onde deveria haver cobrança.

Os dados exercitam de propósito os casos de borda: uma mensalidade, um paciente sem valor
combinado, uma criança com responsável legal que também é quem paga (ADR-014, ADR-009), e um
atendimento de casal cujos participantes têm também seus casos individuais.

⚠️ Recusa rodar com `DEBUG=False`. É dado fictício com senha conhecida — em produção seriam
duas contas de porta aberta.
"""

from datetime import date, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from agenda.models import HorarioDisponivel, Recorrencia
from atendimentos.models import Consulta, Desfecho
from atendimentos.servicos import cadastrar_prevista, definir_frequencia, registrar_desfecho, sessoes_previstas
from contas.models import Psicologo
from core import contexto
from financeiro.models import Pagamento
from financeiro.servicos import cobrancas_do_mes, registrar_pagamento_mensalidade, registrar_pagamento_sessao
from prontuarios import servicos as prontuarios
from prontuarios.models import Prontuario, VersaoProntuario
from pacientes.models import Caso, CondicaoCobranca, Paciente, ResponsavelLegal
from pacientes.servicos import cadastrar_paciente, criar_caso_coletivo

SENHA = "hamilton123"

_POR_SESSAO = CondicaoCobranca.Modalidade.POR_SESSAO
_MENSAL = CondicaoCobranca.Modalidade.MENSAL
_SEMANAL = Recorrencia.Frequencia.SEMANAL
_QUINZENAL = Recorrencia.Frequencia.QUINZENAL

# A primeira versão da semente usava `@demo.com`, com os mesmos CPF e CRP de hoje. Sem limpá-las, o
# `--limpar` apagava as contas novas e esbarrava nas antigas ao recriar ("CPF já existe").
EMAILS_DA_SEMENTE_ANTIGA = ["ana@demo.com", "bruno@demo.com"]


def _frequencia_de_demonstracao(caso, *, semanas_atras: int = 0, cadastradas=(), **regra) -> None:
    """Frequência que começou semanas atrás, com as primeiras sessões cadastradas e o resto pendente.

    Grava a regra direto, e não por `definir_frequencia`: o serviço só aceita frequência de hoje em diante, e uma
    demonstração sem passado não mostraria consulta cadastrada nem pendência (ADR-060). As sessões são cadastradas
    pelo serviço, com a mesma validação da tela.
    """
    if not semanas_atras:
        definir_frequencia(caso, **regra)
        return
    hoje = timezone.localdate()
    recorrencia = Recorrencia.objects.create(
        caso=caso, inicio=hoje - timedelta(weeks=semanas_atras), duracao=caso.psicologo.duracao_sessao, **regra)
    passadas = [s for s in sessoes_previstas(recorrencia.inicio, hoje, caso=caso)
                if s.regra.pk == recorrencia.pk and s.pendente()]
    for sessao, estado in zip(passadas, cadastradas):
        cadastrar_prevista(recorrencia, sessao.data, estado=estado)


def _pagamento_de_demonstracao(caso, *, forma: str, meses_atras: int | None = None, sessao: int | None = None):
    """Paga a mensalidade de meses atrás, ou a N-ésima sessão cobrada, pelo valor devido e na data do vencimento."""
    if meses_atras is not None:
        hoje = timezone.localdate()
        ano, mes = hoje.year, hoje.month - meses_atras
        while mes < 1:
            ano, mes = ano - 1, mes + 12
        cobranca = next(c for c in cobrancas_do_mes(ano, mes, caso=caso) if c.tipo == "MENSALIDADE")
        registrar_pagamento_mensalidade(
            caso, ano=ano, mes=mes, valor=cobranca.devido, data=cobranca.vencimento, forma=forma)
        return
    consulta = caso.consultas.filter(estado__in=["REALIZADA", "FALTA_COBRADA"]).order_by("inicio")[sessao]
    registrar_pagamento_sessao(consulta, data=timezone.localtime(consulta.inicio).date(), forma=forma)


def _prontuario_de_demonstracao(caso, *, sessao: int, texto: str, confirmar: bool) -> None:
    """Escreve o prontuário da N-ésima sessão realizada do caso individual — confirmado ou como rascunho."""
    consulta = caso.consultas.filter(estado="REALIZADA").order_by("inicio")[sessao]
    paciente = caso.pacientes.first()
    acao = prontuarios.confirmar if confirmar else prontuarios.salvar_rascunho
    acao(consulta, paciente, texto=texto)


def _apagar_conta_de_demonstracao(psicologo) -> int:
    """Apaga uma conta fictícia inteira, na ordem que o `PROTECT` exige.

    `Psicologo.delete()` sozinho falha: consulta, desfecho e pagador protegem o atendimento contra exclusão
    em cascata (ADR-048), e a cascata a partir do psicólogo esbarra neles. Aqui se apaga de fora para dentro —
    o que registra atendimento, depois o atendimento, depois a conta. É o mesmo problema que o descarte de
    conta da ADR-038 vai ter de resolver (P-70); isto serve só a dado de demonstração.
    """
    dono = {"psicologo": psicologo}
    total = 0
    for modelo in (VersaoProntuario, Prontuario, Pagamento, Consulta, Desfecho, Recorrencia, Caso):
        total += modelo.objetos_todos.filter(**dono).delete()[0]
    return total + psicologo.delete()[0]

PSICOLOGOS = [
    {
        "email": "ana@exemplo.com", "nome_completo": "Ana Ribeiro", "cpf": "11111111111",
        "crp_numero": "111111",
        "pacientes": [
            dict(nome="Marcos Vieira", cpf="52998224725", data_nascimento=date(1988, 4, 12),
                 telefone="31988112233", email="marcos@exemplo.com", cep="30140071",
                 logradouro="Rua da Bahia", numero="1200", bairro="Lourdes",
                 cidade="Belo Horizonte", uf="MG", data_primeira_sessao=date(2026, 3, 2),
                 medicamento="Sertralina 50mg, uso contínuo (relato do paciente).",
                 cobranca=dict(valor=Decimal("200"), modalidade=_POR_SESSAO)),
            dict(nome="Juliana Alves", cpf="15350946056", data_nascimento=date(1995, 11, 30),
                 telefone="31977445566", email="juliana@exemplo.com", cidade="Belo Horizonte",
                 uf="MG", data_primeira_sessao=date(2026, 7, 15),
                 observacoes="Prefere horário no fim da tarde.",
                 cobranca=dict(valor=Decimal("700"), modalidade=_MENSAL,
                               tipo_vencimento="DIA_UTIL", dia_vencimento=5)),
            # Sem CPF de propósito: exercita o aviso da ADR-040. Criança: responsável legal, que
            # também é quem paga — os três eixos da ADR-014 em pessoas diferentes.
            dict(nome="Rafael Pinto", data_nascimento=date(2019, 6, 8), telefone="31999887766",
                 data_primeira_sessao=date(2026, 8, 20),
                 observacoes="Atendimento infantil.",
                 cobranca=dict(valor=Decimal("180"), modalidade=_POR_SESSAO),
                 responsaveis=[dict(nome="Luciana Pinto", parentesco="mãe", cpf="39053344705",
                                    telefone="31999887766",
                                    guarda=ResponsavelLegal.Guarda.COMPARTILHADA)],
                 pagador=dict(nome="Luciana Pinto", cpf="39053344705")),
            # Sem valor combinado: exercita o "Não combinada" da ficha (ADR-012).
            dict(nome="Beatriz Nogueira", cpf="71428793860", data_nascimento=date(1972, 1, 25),
                 telefone="31988990011", cidade="Nova Lima", uf="MG",
                 data_primeira_sessao=date(2026, 9, 1)),
        ],
        "casais": [],
        # Grade de segunda a quinta, manhã e fim de tarde (ADR-029). A quinzenal da Juliana ocupa metade
        # da faixa dela; o Rafael no sábado aparece como "fora da grade" (ADR-056).
        "grade": [(dia, 8, 12) for dia in range(4)] + [(dia, 14, 19) for dia in range(4)],
        # Frequências que começaram semanas atrás, com parte das sessões já cadastradas e o resto pendente — sem
        # passado, a agenda não teria nem consulta cadastrada nem pendência para mostrar (ADR-060).
        "frequencias": {
            "Marcos Vieira": dict(frequencia=_SEMANAL, dia_semana=1, hora=time(14), semanas_atras=4,
                                  cadastradas=["REALIZADA", "REALIZADA", "FALTA_COBRADA"]),
            "Juliana Alves": dict(frequencia=_QUINZENAL, dia_semana=3, hora=time(18), semanas_atras=4,
                                  cadastradas=["REALIZADA"]),
            "Rafael Pinto": dict(frequencia=_SEMANAL, dia_semana=5, hora=time(9), semanas_atras=3,
                                 cadastradas=["REALIZADA", "FALTA_REMARCADA"]),
        },
        # Beatriz desistiu antes de começar: exercita a aba "Encerrados" e o botão de retomar (ADR-055).
        "desfechos": {
            "Beatriz Nogueira": dict(tipo="DESISTENCIA", motivo="Não respondeu depois do primeiro contato."),
        },
        # Os dois meses anteriores da Juliana pagos e o atual pendente, para o lembrete aparecer (ADR-063).
        # Do Marcos, só a primeira sessão paga.
        "pagamentos": [
            dict(paciente="Juliana Alves", meses_atras=2, forma="PIX"),
            dict(paciente="Juliana Alves", meses_atras=1, forma="TRANSFERENCIA"),
            dict(paciente="Marcos Vieira", sessao=0, forma="DINHEIRO"),
        ],
        # Da primeira sessão do Marcos, um prontuário confirmado; as outras ficam para escrever (ADR-064).
        "prontuarios": [
            dict(paciente="Marcos Vieira", sessao=0, confirmar=True,
                 texto="Registro fictício de demonstração. Sessão centrada nas dificuldades de sono relatadas na "
                       "semana; exploradas estratégias de higiene do sono. Paciente participativo. Combinado retomar "
                       "o tema na próxima sessão."),
        ],
    },
    {
        "email": "bruno@exemplo.com", "nome_completo": "Bruno Carvalho", "cpf": "22222222222",
        "crp_numero": "222222",
        "pacientes": [
            dict(nome="Camila Duarte", cpf="03119999708", data_nascimento=date(1990, 9, 3),
                 telefone="21988776655", cidade="Rio de Janeiro", uf="RJ",
                 data_primeira_sessao=date(2026, 5, 10),
                 cobranca=dict(valor=Decimal("250"), modalidade=_POR_SESSAO)),
            dict(nome="Pedro Henrique Sá", data_nascimento=date(2001, 2, 17),
                 telefone="21977665544", data_primeira_sessao=date(2026, 8, 28),
                 cobranca=dict(valor=Decimal("250"), modalidade=_POR_SESSAO)),
        ],
        # Camila e Pedro têm cada um o seu caso individual **e** este, juntos (ADR-026).
        "casais": [dict(descricao="Camila e Pedro — casal",
                        pacientes=["Camila Duarte", "Pedro Henrique Sá"])],
        # Sem grade declarada: nenhum aviso de "fora da grade" aparece para o Bruno (ADR-056).
        "frequencias": {
            "Camila e Pedro — casal": dict(frequencia=_SEMANAL, dia_semana=0, hora=time(19), semanas_atras=2,
                                           cadastradas=["REALIZADA"]),
        },
    },
]


class Command(BaseCommand):
    help = "Cria dois psicólogos de demonstração, com pacientes. Só em desenvolvimento."

    def add_arguments(self, parser):
        parser.add_argument("--limpar", action="store_true",
                            help="Apaga os dados de demonstração antes de recriar.")

    @transaction.atomic
    def handle(self, *args, **opcoes):
        if not settings.DEBUG:
            raise CommandError(
                "Recusado com DEBUG=False. Este comando cria contas com senha conhecida."
            )

        emails = [p["email"] for p in PSICOLOGOS]
        if opcoes["limpar"]:
            removidos = 0
            for psicologo in Psicologo.objects.filter(email__in=emails + EMAILS_DA_SEMENTE_ANTIGA):
                removidos += _apagar_conta_de_demonstracao(psicologo)
            self.stdout.write(f"Removidos os dados anteriores ({removidos} registros).")
        elif Psicologo.objects.filter(email__in=emails).exists():
            raise CommandError(
                "Os psicólogos de demonstração já existem. Use --limpar para recriar."
            )

        for modelo in PSICOLOGOS:
            # Cópia rasa: `pop` no dicionário do módulo quebraria uma segunda execução no mesmo processo.
            dados = dict(modelo)
            pacientes = dados.pop("pacientes")
            casais = dados.pop("casais")
            grade = dados.pop("grade", [])
            frequencias = dados.pop("frequencias", {})
            desfechos = dados.pop("desfechos", {})
            pagamentos = dados.pop("pagamentos", [])
            registros_de_prontuario = dados.pop("prontuarios", [])
            psicologo = Psicologo.objects.create_user(
                password=SENHA, telefone="31988887777", crp_regiao="04",
                # `is_staff`/`is_superuser` só para o `/admin/` continuar servindo de conferência
                # do passo 0. Nada no produto olha para essas flags.
                is_staff=True, is_superuser=True, **dados,
            )
            with contexto.como(psicologo.pk):
                por_nome = {}
                casos = {}  # por nome do paciente, ou pela descrição do casal
                for item in pacientes:
                    campos = dict(item)
                    cobranca = dict(campos.pop("cobranca", {}))
                    # A cobrança vale desde a primeira sessão: sem isso, as sessões semeadas no passado
                    # ficariam antes da condição e não gerariam pagamento nenhum (ADR-063).
                    if cobranca and campos.get("data_primeira_sessao"):
                        cobranca.setdefault("vigente_desde", campos["data_primeira_sessao"])
                    responsaveis = campos.pop("responsaveis", [])
                    pagador = campos.pop("pagador", None)

                    paciente = Paciente(**campos)
                    caso = cadastrar_paciente(paciente, **cobranca)
                    for responsavel in responsaveis:
                        ResponsavelLegal.objects.create(paciente=paciente, **responsavel)
                    if pagador:
                        caso.pagador_paciente = None
                        caso.pagador_nome = pagador["nome"]
                        caso.pagador_cpf = pagador.get("cpf", "")
                        caso.save()
                    por_nome[paciente.nome] = paciente
                    casos[paciente.nome] = caso

                for casal in casais:
                    casos[casal["descricao"]] = criar_caso_coletivo(
                        [por_nome[nome] for nome in casal["pacientes"]], descricao=casal["descricao"])

                for dia, de, ate in grade:
                    HorarioDisponivel.objects.create(dia_semana=dia, inicio=time(de), fim=time(ate))
                for nome, regra in frequencias.items():
                    _frequencia_de_demonstracao(casos[nome], **regra)
                for nome, desfecho in desfechos.items():
                    registrar_desfecho(casos[nome], **desfecho)
                for pagamento in pagamentos:
                    campos_do_pagamento = dict(pagamento)
                    _pagamento_de_demonstracao(casos[campos_do_pagamento.pop("paciente")], **campos_do_pagamento)
                for registro in registros_de_prontuario:
                    campos_do_registro = dict(registro)
                    _prontuario_de_demonstracao(casos[campos_do_registro.pop("paciente")], **campos_do_registro)

            self.stdout.write(self.style.SUCCESS(
                f"  {psicologo.email}  senha: {SENHA}  ({len(pacientes)} pacientes, "
                f"{len(casais)} atendimento(s) de casal)"))

        self.stdout.write(
            "\nEntre com um, depois com o outro: cada um enxerga só os próprios pacientes "
            "e só o próprio cadastro. É a ADR-001 acontecendo."
        )
