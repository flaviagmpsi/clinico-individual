"""Popula o banco local com dois psicólogos e seus pacientes.

Existe por dois motivos, e o segundo é o que importa:

1. Dar o que ver nas telas sem cadastrar tudo à mão.
2. **Dois** psicólogos, e não um. Com um só, o isolamento da ADR-001 é indistinguível de um
   sistema que não isola nada. Entrando como a Ana e depois como o Bruno, a garantia deixa de
   ser afirmação em documento e vira coisa que se confere com os olhos.

⚠️ Recusa rodar com `DEBUG=False`. É dado fictício com senha conhecida — em produção seriam
duas contas de porta aberta.
"""

from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from contas.models import Psicologo
from core import contexto
from pacientes.models import Paciente

SENHA = "hamilton123"

PSICOLOGOS = [
    {
        "email": "ana@exemplo.com", "nome_completo": "Ana Ribeiro", "cpf": "11111111111",
        "crp_numero": "111111",
        "pacientes": [
            dict(nome="Marcos Vieira", cpf="52998224725", data_nascimento=date(1988, 4, 12),
                 telefone="31988112233", email="marcos@exemplo.com", cep="30140071",
                 logradouro="Rua da Bahia", numero="1200", bairro="Lourdes",
                 cidade="Belo Horizonte", uf="MG", data_primeira_sessao=date(2026, 3, 2),
                 medicamento="Sertralina 50mg, uso contínuo (relato do paciente)."),
            dict(nome="Juliana Alves", cpf="15350946056", data_nascimento=date(1995, 11, 30),
                 telefone="31977445566", email="juliana@exemplo.com", cidade="Belo Horizonte",
                 uf="MG", data_primeira_sessao=date(2026, 7, 15),
                 observacoes="Prefere horário no fim da tarde."),
            # Sem CPF de propósito: exercita o aviso da ADR-040 na ficha e o contador do painel.
            dict(nome="Rafael Pinto", data_nascimento=date(2019, 6, 8), telefone="31999887766",
                 data_primeira_sessao=date(2026, 8, 20),
                 observacoes="Atendimento infantil. Responsável legal entra no passo 2 (ADR-014)."),
            dict(nome="Beatriz Nogueira", cpf="71428793860", data_nascimento=date(1972, 1, 25),
                 telefone="31988990011", cidade="Nova Lima", uf="MG",
                 data_primeira_sessao=date(2026, 9, 1)),
        ],
    },
    {
        "email": "bruno@exemplo.com", "nome_completo": "Bruno Carvalho", "cpf": "22222222222",
        "crp_numero": "222222",
        "pacientes": [
            dict(nome="Camila Duarte", cpf="03119999708", data_nascimento=date(1990, 9, 3),
                 telefone="21988776655", cidade="Rio de Janeiro", uf="RJ",
                 data_primeira_sessao=date(2026, 5, 10)),
            dict(nome="Pedro Henrique Sá", data_nascimento=date(2001, 2, 17),
                 telefone="21977665544", data_primeira_sessao=date(2026, 8, 28)),
        ],
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
            # `objetos_todos` e não `objects`: fora de requisição não há escopo, e o manager
            # padrão levantaria `EscopoNaoDefinido` — que é o comportamento correto dele.
            apagados = Psicologo.objects.filter(email__in=emails).delete()
            self.stdout.write(f"Removidos os dados anteriores ({apagados[0]} registros).")
        elif Psicologo.objects.filter(email__in=emails).exists():
            raise CommandError(
                "Os psicólogos de demonstração já existem. Use --limpar para recriar."
            )

        for dados in PSICOLOGOS:
            pacientes = dados.pop("pacientes")
            psicologo = Psicologo.objects.create_user(
                password=SENHA, telefone="31988887777", crp_regiao="04",
                # `is_staff`/`is_superuser` só para o `/admin/` continuar servindo de conferência
                # do passo 0. Nada no produto olha para essas flags.
                is_staff=True, is_superuser=True, **dados,
            )
            with contexto.como(psicologo.pk):
                for paciente in pacientes:
                    Paciente.objects.create(**paciente)
            dados["pacientes"] = pacientes
            self.stdout.write(self.style.SUCCESS(
                f"  {psicologo.email}  senha: {SENHA}  ({len(pacientes)} pacientes)"))

        self.stdout.write(
            "\nEntre com um, depois com o outro: cada um enxerga só os próprios pacientes "
            "e só o próprio cadastro. É a ADR-001 acontecendo."
        )
