"""Cria UMA conta fictícia rica para demonstração, com e-mail e senha próprios.

Serve para dar a alguém (um amigo, um avaliador) uma conta de psicólogo de mentira, mas completa: pacientes,
agenda, frequências com todas as situações, sessões previstas e a cadastrar, prontuários (escritos e rascunho),
pagamentos pagos e vencidos, documentos, anamneses, despesas e o "hoje" do painel. É a mesma clínica rica que o
comando `semear` monta na conta principal — só que numa identidade própria e numa conta só.

Diferente do `semear`, pode rodar **no site no ar** (DEBUG=False), mas **só com `--em-producao` explícito** — é uma
decisão deliberada de quem roda, porque cria uma conta de login com senha conhecida. É puramente aditivo: cria um
novo dono e os dados dele; nunca toca em conta de outro psicólogo (ADR-001). Recusa se o e-mail já existir, a menos
que `--apagar` seja passado.

Reaproveita as peças do `semear` sem alterá-lo.
"""

from datetime import time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.utils import OperationalError
from django.utils import timezone

from agenda.models import HorarioDisponivel
from assinaturas import servicos as assinaturas
from assinaturas.models import Assinatura
from atendimentos.servicos import registrar_desfecho
from contas.models import Psicologo
from core import contexto
from core.management.commands.semear import (
    PSICOLOGOS, _ANAMNESES, _ANIVERSARIOS, _apagar_conta_de_demonstracao, _aniversario_neste_mes,
    _despesas_de_demonstracao, _dia_de_exemplo, _escrever_o_passado, _frequencia_de_demonstracao,
    _pagamento_de_demonstracao, _pagar_o_passado, _prontuario_de_demonstracao,
)
from documentos import modelos as modelos_de_documento
from documentos import servicos as documentos
from pacientes import convites as convites_de_cadastro
from pacientes.models import Paciente, ResponsavelLegal
from pacientes.servicos import cadastrar_paciente, criar_caso_coletivo
from prontuarios import anamneses
from prontuarios import servicos as prontuarios


def _criar_conta_rica(modelo: dict, senha: str) -> Psicologo:
    """Cria o psicólogo e popula a clínica inteira (mesma lógica do `semear`, com a história rica ligada)."""
    dados = dict(modelo)
    pacientes = dados.pop("pacientes")
    casais = dados.pop("casais", [])
    grade = dados.pop("grade", [])
    frequencias = dados.pop("frequencias", {})
    desfechos = dados.pop("desfechos", {})
    pagamentos = dados.pop("pagamentos", [])
    registros_de_prontuario = dados.pop("prontuarios", [])
    demandas_de_demonstracao = dados.pop("demandas", {})
    documentos_de_demonstracao = dados.pop("documentos", [])
    assinatura = dados.pop("assinatura", "ATIVA")

    psicologo = Psicologo.objects.create_user(
        password=senha, telefone="31988887777", crp_regiao="04",
        quiz_concluido_em=timezone.now(), atende_online=True, atende_presencial=True,
        # IA de prontuário ligada na conta demo (ADR-111 a deixa desligada por padrão): aqui é de propósito,
        # para quem explora a demonstração poder testar a escrita assistida.
        usa_ia_no_prontuario=True,
        nome_clinica=f"Consultório de {dados['nome_completo'].split()[-1]}",
        telefone_clinica="3133334444", cep="30140071", logradouro="Rua da Bahia", numero="1200",
        bairro="Lourdes", cidade="Belo Horizonte", uf="MG",
        **dados,
    )
    with contexto.como(psicologo.pk):
        if assinatura == "ATIVA":
            assinaturas.ativar(Assinatura.Meio.CARTAO, id_no_gateway="demonstracao",
                               agora=timezone.now() - timedelta(days=200))
        else:
            assinaturas.comecar_teste(agora=timezone.now() - timedelta(days=2))

        por_nome, casos = {}, {}
        for item in pacientes:
            campos = dict(item)
            cobranca = dict(campos.pop("cobranca", {}))
            if cobranca and campos.get("data_primeira_sessao"):
                cobranca.setdefault("vigente_desde", campos["data_primeira_sessao"])
            responsaveis = campos.pop("responsaveis", [])
            pagador = campos.pop("pagador", None)
            if campos["nome"] in _ANIVERSARIOS and campos.get("data_nascimento"):
                campos["data_nascimento"] = _aniversario_neste_mes(
                    campos["data_nascimento"], _ANIVERSARIOS[campos["nome"]])
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
        for nome_do_paciente, demanda in demandas_de_demonstracao.items():
            da_folha = por_nome[nome_do_paciente]
            prontuarios.salvar_folha(
                da_folha, encerramento="",
                demanda=f"{prontuarios.sugestao_de_demanda(da_folha)} Texto fictício de demonstração. {demanda}")

        # Links de cadastro (ADR-081): um já respondido, esperando a revisão, e um ainda com o paciente.
        respondido, _ = convites_de_cadastro.gerar_convite("Helena, indicação da Dra. Paula")
        convites_de_cadastro.responder(respondido, {
            "nome": "Helena Prado Martins", "nome_social": "Lena", "raca_cor": "PARDA",
            "cpf": "11144477735", "data_nascimento": "1991-08-14", "estado_civil": "UNIAO_ESTAVEL",
            "telefone": "31991234567", "email": "helena.prado@exemplo.com", "pais": "Brasil",
            "cep": "30130110", "logradouro": "Avenida Afonso Pena", "numero": "1500",
            "bairro": "Centro", "cidade": "Belo Horizonte", "uf": "MG",
            "genero": "Mulher cisgênero", "profissao": "Arquiteta", "medicamento": "Nenhum",
            "contatos_de_emergencia": [{"nome": "Rosa Prado", "parentesco": "mãe", "telefone": "31977776666"}],
            "pagador": {"nome": "Caio Martins", "cpf": ""},
        })
        convites_de_cadastro.gerar_convite("Rafael (primeiro contato pelo Instagram)")

        # A história rica: meses de pagamentos, registros de sessão, despesas, o dia de hoje e anamneses.
        individuais = {nome: caso for nome, caso in casos.items() if nome in por_nome}
        _pagar_o_passado(individuais, devedores=("Fernanda Lopes",))
        _escrever_o_passado(individuais)
        _despesas_de_demonstracao()
        _dia_de_exemplo(individuais)
        for nome_do_paciente, campos_da_anamnese in _ANAMNESES.items():
            temas = {t.origem: t for t in anamneses.roteiro()}
            anamneses.salvar(por_nome[nome_do_paciente],
                             {temas[chave].pk: texto for chave, texto in campos_da_anamnese.items()})

        for item in documentos_de_demonstracao:
            paciente = por_nome[item["paciente"]]
            modelo_doc = modelos_de_documento.obter(item["modelo"])
            conteudo = {**documentos.sugestoes(modelo_doc, psicologo, paciente), **item["dados"]}
            documento = documentos.salvar_rascunho(item["modelo"], conteudo, paciente=paciente)
            if item["emitir"]:
                documentos.emitir(documento)

    return psicologo


class Command(BaseCommand):
    help = "Cria UMA conta fictícia rica para demonstração, com e-mail e senha próprios."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="E-mail de login da conta demo.")
        parser.add_argument("--senha", required=True, help="Senha da conta demo.")
        parser.add_argument("--nome", default="Marina Souza", help="Nome completo do psicólogo fictício.")
        parser.add_argument("--crp", default="999999", help="Número do CRP (a região é 04).")
        parser.add_argument("--cpf", default="32132132100", help="CPF fictício do psicólogo.")
        parser.add_argument("--em-producao", action="store_true",
                            help="Autoriza rodar com DEBUG=False (site no ar). Decisão deliberada de quem roda.")
        parser.add_argument("--apagar", action="store_true",
                            help="Apaga a conta demo deste e-mail antes de recriar.")
        parser.add_argument("--historia-max", type=int, default=8,
                            help="Semanas de histórico por paciente (menos = transação mais curta, menos sujeita a "
                                 "queda de conexão do Neon). Padrão 8.")

    def handle(self, *args, **o):
        if not settings.DEBUG and not o["em_producao"]:
            raise CommandError(
                "Recusado com DEBUG=False. Para criar no site no ar, de propósito, use --em-producao.")

        # A clínica rica é a da conta principal do `semear` (PSICOLOGOS[0]), vestida com a identidade escolhida.
        # O histórico é limitado para a transação não ficar longa demais: o compute do Neon derruba a conexão numa
        # transação única muito grande (foi onde o seed caía, sempre no primeiro pagamento, depois de meses de sessões).
        base = dict(PSICOLOGOS[0])
        base["email"] = o["email"]
        base["nome_completo"] = o["nome"]
        base["cpf"] = o["cpf"]
        base["crp_numero"] = o["crp"]
        teto = max(o["historia_max"], 0)
        base["frequencias"] = {nome: {**regra, "historia": min(regra.get("historia", 0), teto)}
                               for nome, regra in base.get("frequencias", {}).items()}

        # Resiliência: se a conexão do Neon cair no meio (ruído conhecido), a transação faz rollback e tentamos de
        # novo, com uma conexão nova. Cada tentativa é atômica — ou cria a conta inteira, ou nada.
        ultimo_erro = None
        for tentativa in range(1, 4):
            try:
                with transaction.atomic():
                    existente = Psicologo.objects.filter(email=o["email"]).first()
                    if existente:
                        if o["apagar"]:
                            self.stdout.write(f"Apagando conta anterior de {o['email']} "
                                              f"({_apagar_conta_de_demonstracao(existente)} registros).")
                        else:
                            raise CommandError(
                                f"Já existe conta com {o['email']}. Use --apagar para recriar, ou outro e-mail.")
                    psicologo = _criar_conta_rica(base, o["senha"])
                break
            except OperationalError as erro:
                ultimo_erro = erro
                connection.close()
                self.stderr.write(self.style.WARNING(
                    f"Tentativa {tentativa}/3 caiu (conexão do Neon). Tentando de novo com conexão nova..."))
        else:
            raise CommandError(
                f"Não consegui após 3 tentativas (conexão do Neon instável). Rode de novo. Último erro: {ultimo_erro}")

        self.stdout.write(self.style.SUCCESS(
            f"Conta de demonstração criada: {psicologo.email}  |  CRP 04/{o['crp']}  |  "
            f"{len(base['pacientes'])} pacientes + dia de hoje montado."))
        self.stdout.write("Entre com o e-mail e a senha definidos e explore todas as telas.")
