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

from datetime import date, datetime, time, timedelta
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
from documentos import modelos as modelos_de_documento
from documentos import servicos as documentos
from documentos.models import Documento
from prontuarios import servicos as prontuarios
from prontuarios.models import FichaDoProntuario, Prontuario, VersaoProntuario
from pacientes import convites as convites_de_cadastro
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
        # A remarcada da semente já diz para quando foi (ADR-068): amanhã, no mesmo horário — um dia que a
        # frequência dela não prevê, senão o calendário mostraria dois cartões no mesmo lugar.
        remarcada_para = None
        if estado == "REMARCADA":
            destino = hoje + timedelta(days=1)
            remarcada_para = timezone.make_aware(datetime.combine(destino, recorrencia.hora))
        cadastrar_prevista(recorrencia, sessao.data, estado=estado, remarcada_para=remarcada_para)


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
    consulta = caso.consultas.filter(cobrada=True).order_by("inicio")[sessao]
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
    # `Documento` primeiro: ele protege o paciente (ADR-076), e a cascata do psicólogo esbarraria nele.
    for modelo in (Documento, FichaDoProntuario, VersaoProntuario, Prontuario, Pagamento, Consulta, Desfecho,
                   Recorrencia, Caso):
        total += modelo.objetos_todos.filter(**dono).delete()[0]
    return total + psicologo.delete()[0]

PSICOLOGOS = [
    {
        "email": "ana@exemplo.com", "nome_completo": "Ana Ribeiro", "cpf": "11111111111",
        "crp_numero": "111111", "abordagem": "TCC",
        "pacientes": [
            dict(nome="Marcos Vieira", cpf="52998224725", data_nascimento=date(1988, 4, 12),
                 telefone="31988112233", email="marcos@exemplo.com", cep="30140071",
                 logradouro="Rua da Bahia", numero="1200", bairro="Lourdes",
                 cidade="Belo Horizonte", uf="MG", data_primeira_sessao=date(2026, 3, 2),
                 medicamento="Sertralina 50mg, uso contínuo (relato do paciente).",
                 cobranca=dict(valor=Decimal("200"), modalidade=_POR_SESSAO)),
            # Atende online: com ela a agenda mostra o percentual de online × presencial (ADR-065).
            dict(nome="Juliana Alves", cpf="15350946056", data_nascimento=date(1995, 11, 30),
                 telefone="31977445566", email="juliana@exemplo.com", cidade="Belo Horizonte",
                 uf="MG", data_primeira_sessao=date(2026, 7, 15), modalidade="ONLINE",
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
            # Daqui para baixo, pacientes para a agenda ficar parecida com uma semana de verdade (ADR-073):
            # um ou dois por dia, online e presencial, mensalidade e por sessão.
            dict(nome="Carolina Mendes", cpf="10203040506", data_nascimento=date(1991, 3, 14),
                 telefone="31981010101", cidade="Belo Horizonte", uf="MG", data_primeira_sessao=date(2026, 6, 1),
                 cobranca=dict(valor=Decimal("220"), modalidade=_POR_SESSAO)),
            dict(nome="Diego Ferreira", cpf="20304050607", data_nascimento=date(1985, 8, 2),
                 telefone="31982020202", cidade="Contagem", uf="MG", data_primeira_sessao=date(2026, 6, 1),
                 modalidade="ONLINE",
                 cobranca=dict(valor=Decimal("600"), modalidade=_MENSAL, tipo_vencimento="DIA_FIXO",
                               dia_vencimento=5)),
            dict(nome="Fernanda Lopes", cpf="30405060708", data_nascimento=date(1998, 12, 9),
                 telefone="31983030303", cidade="Belo Horizonte", uf="MG", data_primeira_sessao=date(2026, 6, 1),
                 modalidade="ONLINE", cobranca=dict(valor=Decimal("200"), modalidade=_POR_SESSAO)),
            dict(nome="Gustavo Rocha", cpf="40506070809", data_nascimento=date(1979, 5, 21),
                 telefone="31984040404", cidade="Belo Horizonte", uf="MG", data_primeira_sessao=date(2026, 6, 1),
                 cobranca=dict(valor=Decimal("250"), modalidade=_POR_SESSAO)),
            dict(nome="Helena Castro", cpf="50607080910", data_nascimento=date(2003, 10, 30),
                 telefone="31985050505", cidade="Betim", uf="MG", data_primeira_sessao=date(2026, 6, 1),
                 cobranca=dict(valor=Decimal("180"), modalidade=_POR_SESSAO)),
            dict(nome="Igor Santana", cpf="60708091011", data_nascimento=date(1994, 1, 7),
                 telefone="31986060606", cidade="Belo Horizonte", uf="MG", data_primeira_sessao=date(2026, 8, 1),
                 modalidade="ONLINE",
                 cobranca=dict(valor=Decimal("720"), modalidade=_MENSAL, tipo_vencimento="DIA_FIXO",
                               dia_vencimento=10)),
            dict(nome="Larissa Duarte", cpf="70809101112", data_nascimento=date(1989, 7, 18),
                 telefone="31987070707", cidade="Belo Horizonte", uf="MG", data_primeira_sessao=date(2026, 6, 1),
                 cobranca=dict(valor=Decimal("200"), modalidade=_POR_SESSAO)),
            dict(nome="Otávio Nunes", cpf="80910111213", data_nascimento=date(1982, 11, 25),
                 telefone="31988080808", cidade="Nova Lima", uf="MG", data_primeira_sessao=date(2026, 6, 1),
                 modalidade="ONLINE", cobranca=dict(valor=Decimal("200"), modalidade=_POR_SESSAO)),
        ],
        "casais": [],
        # A grade é o que a Ana cadastrou como disponível (ADR-029), e é só dela que sai o "LIVRE" do
        # calendário (ADR-073). Blocos curtos em volta das sessões: sobra pouca coisa livre, como numa
        # semana de verdade. O Rafael no sábado, sem grade, aparece como "fora da grade" (ADR-056).
        "grade": [(0, 8, 11), (1, 9, 12), (1, 14, 16), (2, 14, 18), (3, 8, 11), (3, 17, 19), (4, 9, 13)],
        # Frequências que começaram semanas atrás, com parte das sessões já cadastradas e o resto pendente — sem
        # passado, a agenda não teria nem consulta cadastrada nem pendência para mostrar (ADR-060). As situações
        # cobrem as cinco da ADR-065: presente, falta sem aviso, cancelamento dos dois lados e remarcada.
        "frequencias": {
            "Marcos Vieira": dict(frequencia=_SEMANAL, dia_semana=1, hora=time(14), semanas_atras=5,
                                  cadastradas=["REALIZADA", "REALIZADA", "FALTOU", "CANCELADA_PROFISSIONAL"]),
            "Juliana Alves": dict(frequencia=_QUINZENAL, dia_semana=3, hora=time(18), semanas_atras=6,
                                  cadastradas=["REALIZADA", "CANCELADA_CLIENTE"]),
            "Rafael Pinto": dict(frequencia=_SEMANAL, dia_semana=5, hora=time(9), semanas_atras=3,
                                 cadastradas=["REALIZADA", "REMARCADA"]),
            "Carolina Mendes": dict(frequencia=_SEMANAL, dia_semana=0, hora=time(8), semanas_atras=4,
                                    cadastradas=["REALIZADA", "REALIZADA", "REALIZADA"]),
            "Diego Ferreira": dict(frequencia=_QUINZENAL, dia_semana=0, hora=time(9), semanas_atras=6,
                                   cadastradas=["REALIZADA", "CANCELADA_CLIENTE"]),
            "Fernanda Lopes": dict(frequencia=_SEMANAL, dia_semana=1, hora=time(10), semanas_atras=3,
                                   cadastradas=["REALIZADA", "FALTOU"]),
            "Gustavo Rocha": dict(frequencia=_SEMANAL, dia_semana=2, hora=time(15), semanas_atras=5,
                                  cadastradas=["REALIZADA", "REALIZADA", "REALIZADA", "REALIZADA"]),
            "Helena Castro": dict(frequencia=_QUINZENAL, dia_semana=2, hora=time(16), semanas_atras=4,
                                  cadastradas=["REALIZADA"]),
            "Igor Santana": dict(frequencia=_SEMANAL, dia_semana=3, hora=time(9), semanas_atras=2,
                                 cadastradas=["REALIZADA"]),
            "Larissa Duarte": dict(frequencia=_SEMANAL, dia_semana=4, hora=time(10), semanas_atras=3,
                                   cadastradas=["REALIZADA", "REALIZADA"]),
            "Otávio Nunes": dict(frequencia=_SEMANAL, dia_semana=4, hora=time(11), semanas_atras=3,
                                 cadastradas=["REALIZADA", "REALIZADA"]),
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
            dict(paciente="Carolina Mendes", sessao=0, forma="PIX"),
            dict(paciente="Carolina Mendes", sessao=1, forma="PIX"),
            dict(paciente="Gustavo Rocha", sessao=0, forma="CARTAO"),
            dict(paciente="Gustavo Rocha", sessao=1, forma="CARTAO"),
            dict(paciente="Larissa Duarte", sessao=0, forma="DINHEIRO"),
        ],
        # Da primeira sessão do Marcos, um prontuário confirmado; as outras ficam para escrever (ADR-064).
        # Uma declaração emitida — a cópia guardada no registro documental — e um relatório pela metade, para
        # a aba de documentos mostrar os dois estados (ADR-076). Texto fictício, e nada clínico na declaração.
        "documentos": [
            dict(paciente="Marcos Vieira", modelo="declaracao", emitir=True, dados=dict(
                finalidade="apresentação ao setor de recursos humanos da empresa em que trabalha",
                informacao="encontra-se em atendimento psicológico com frequência semanal, às terças-feiras, "
                           "das 14h às 14h50, desde março de 2026.")),
            dict(paciente="Juliana Alves", modelo="relatorio", emitir=False, dados=dict(
                solicitante="a própria pessoa atendida",
                finalidade="apresentação ao médico psiquiatra que a acompanha")),
        ],
        "demandas": {
            "Marcos Vieira": "Procurou atendimento por dificuldades de sono associadas a sobrecarga no trabalho. "
                             "Objetivos combinados: identificar os fatores que mantêm a insônia e construir uma rotina "
                             "de sono compatível com a jornada.",
            "Gustavo Rocha": "Procurou atendimento por dificuldade de organizar a rotina após mudança de emprego. "
                             "Objetivos combinados: mapear as situações de sobrecarga e construir estratégias de manejo.",
        },
        "prontuarios": [
            dict(paciente="Marcos Vieira", sessao=0, confirmar=True,
                 texto="Registro fictício de demonstração. Sessão centrada nas dificuldades de sono relatadas na "
                       "semana; exploradas estratégias de higiene do sono. Paciente participativo. Combinado retomar "
                       "o tema na próxima sessão."),
            # Vários registros do mesmo paciente: é o que o prontuário geral, em Documentos, reúne na evolução (ADR-080).
            dict(paciente="Gustavo Rocha", sessao=0, confirmar=True,
                 texto="Registro fictício de demonstração. Entrevista inicial: levantamento da queixa de sobrecarga após "
                       "mudança de emprego e da rotina semanal. Apresentado o contrato de trabalho e combinada a "
                       "frequência semanal."),
            dict(paciente="Gustavo Rocha", sessao=1, confirmar=True,
                 texto="Registro fictício de demonstração. Retomado o registro de situações de sobrecarga feito na "
                       "semana. Identificadas duas situações recorrentes ligadas a prazos. Utilizada entrevista "
                       "semiestruturada."),
            dict(paciente="Gustavo Rocha", sessao=2, confirmar=True,
                 texto="Registro fictício de demonstração. Trabalhadas estratégias de organização de prioridades. "
                       "Paciente relata melhora na qualidade do descanso. Combinado acompanhar a aplicação das "
                       "estratégias até o próximo encontro."),
            dict(paciente="Gustavo Rocha", sessao=3, confirmar=False,
                 texto="Rascunho fictício de demonstração — ainda não confirmado, por isso não entra no prontuário geral."),
        ],
    },
    {
        "email": "bruno@exemplo.com", "nome_completo": "Bruno Carvalho", "cpf": "22222222222",
        "crp_numero": "222222", "abordagem": "PSICANALISE",
        "pacientes": [
            dict(nome="Camila Duarte", cpf="03119999708", data_nascimento=date(1990, 9, 3),
                 telefone="21988776655", cidade="Rio de Janeiro", uf="RJ",
                 data_primeira_sessao=date(2026, 5, 10), modalidade="ONLINE",
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
            demandas_de_demonstracao = dados.pop("demandas", {})
            documentos_de_demonstracao = dados.pop("documentos", [])
            psicologo = Psicologo.objects.create_user(
                password=SENHA, telefone="31988887777", crp_regiao="04",
                # `is_staff`/`is_superuser` só para o `/admin/` continuar servindo de conferência
                # do passo 0. Nada no produto olha para essas flags.
                is_staff=True, is_superuser=True,
                # Contas de demonstração entram direto: o quiz de cadastro (ADR-071) já está respondido.
                quiz_concluido_em=timezone.now(), atende_online=True, atende_presencial=True,
                nome_clinica=f"Consultório de {modelo['nome_completo'].split()[0]}",
                telefone_clinica="3133334444", cep="30140071", logradouro="Rua da Bahia", numero="1200",
                bairro="Lourdes", cidade="Belo Horizonte", uf="MG",
                **dados,
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
                # O prontuário geral (ADR-079, ADR-080): quem tem registro de sessão ganha a avaliação da demanda.
                for nome_do_paciente, demanda in demandas_de_demonstracao.items():
                    da_folha = por_nome[nome_do_paciente]
                    prontuarios.salvar_folha(
                        da_folha, encerramento="",
                        demanda=f"{prontuarios.sugestao_de_demanda(da_folha)} Texto fictício de demonstração. {demanda}")
                # Links de cadastro (ADR-081): um já respondido, esperando a revisão, e um ainda com o paciente.
                if modelo["email"] == "ana@exemplo.com":
                    respondido, _ = convites_de_cadastro.gerar_convite("Helena, indicação da Dra. Paula")
                    convites_de_cadastro.responder(respondido, {
                        "nome": "Helena Prado Martins", "nome_social": "Lena", "raca_cor": "PARDA",
                        "cpf": "11144477735", "data_nascimento": "1991-08-14", "estado_civil": "UNIAO_ESTAVEL",
                        "telefone": "31991234567", "email": "helena.prado@exemplo.com", "pais": "Brasil",
                        "cep": "30130110", "logradouro": "Avenida Afonso Pena", "numero": "1500",
                        "bairro": "Centro", "cidade": "Belo Horizonte", "uf": "MG",
                        "genero": "Mulher cisgênero", "profissao": "Arquiteta", "medicamento": "Nenhum",
                        "contatos_de_emergencia": [
                            {"nome": "Rosa Prado", "parentesco": "mãe", "telefone": "31977776666"}],
                        "pagador": {"nome": "Caio Martins", "cpf": ""},
                    })
                    convites_de_cadastro.gerar_convite("Rafael (primeiro contato pelo Instagram)")
                for item in documentos_de_demonstracao:
                    # Como na tela: o sistema sugere identificação e assinatura; o resto é de quem escreve.
                    paciente = por_nome[item["paciente"]]
                    modelo = modelos_de_documento.obter(item["modelo"])
                    conteudo = {**documentos.sugestoes(modelo, psicologo, paciente), **item["dados"]}
                    documento = documentos.salvar_rascunho(item["modelo"], conteudo, paciente=paciente)
                    if item["emitir"]:
                        documentos.emitir(documento)

            self.stdout.write(self.style.SUCCESS(
                f"  {psicologo.email}  senha: {SENHA}  ({len(pacientes)} pacientes, "
                f"{len(casais)} atendimento(s) de casal)"))

        self.stdout.write(
            "\nEntre com um, depois com o outro: cada um enxerga só os próprios pacientes "
            "e só o próprio cadastro. É a ADR-001 acontecendo."
        )
