"""O paciente — a pessoa atendida.

⚠️ Escopo desta versão: o **cadastro**. O vínculo terapêutico (`Caso`), o responsável legal e o
pagador vêm no passo 2 (ADR-026, ADR-014, ADR-009). A pessoa é única entre atendimentos: Maria
em terapia individual e Maria no casal serão o mesmo registro, e é por isso que os dados
pessoais moram aqui e não no `Caso`.

Os campos são os declarados no escopo ("Cadastro de paciente ampliado", `perguntas.md`). Quase
todos são opcionais de propósito — ADR-012, degradar com honestidade: quem cadastra um paciente
no meio do dia não tem o CEP à mão, e exigir tudo transforma cadastro em barreira.
"""

from django.core.validators import RegexValidator
from django.db import models

from core.models import TenantOwnedModel

# Formato exato, e não só "dígitos": `^\d*$` aceitava CPF "1". Todos admitem vazio porque os
# campos são opcionais (ADR-012) — o que se recusa é o preenchido errado.
cpf_valido = RegexValidator(r"^(\d{11})?$", "CPF tem 11 números, sem pontos ou traços.")
telefone_valido = RegexValidator(r"^(\d{10,11})?$", "Telefone com DDD: 10 ou 11 números, sem espaços ou traços.")
cep_valido = RegexValidator(r"^(\d{8})?$", "CEP tem 8 números, sem traço.")


class Paciente(TenantOwnedModel):
    class UF(models.TextChoices):
        AC = "AC", "Acre"; AL = "AL", "Alagoas"; AP = "AP", "Amapá"; AM = "AM", "Amazonas"
        BA = "BA", "Bahia"; CE = "CE", "Ceará"; DF = "DF", "Distrito Federal"
        ES = "ES", "Espírito Santo"; GO = "GO", "Goiás"; MA = "MA", "Maranhão"
        MT = "MT", "Mato Grosso"; MS = "MS", "Mato Grosso do Sul"; MG = "MG", "Minas Gerais"
        PA = "PA", "Pará"; PB = "PB", "Paraíba"; PR = "PR", "Paraná"; PE = "PE", "Pernambuco"
        PI = "PI", "Piauí"; RJ = "RJ", "Rio de Janeiro"; RN = "RN", "Rio Grande do Norte"
        RS = "RS", "Rio Grande do Sul"; RO = "RO", "Rondônia"; RR = "RR", "Roraima"
        SC = "SC", "Santa Catarina"; SP = "SP", "São Paulo"; SE = "SE", "Sergipe"
        TO = "TO", "Tocantins"

    nome = models.CharField("Nome completo", max_length=255)

    # Sem CPF é aceitável: quem nasceu antes de 2018 pode não ter (ADR-040 / P-34). A tela avisa,
    # não bloqueia — o CPF só vira obrigatório quando houver saída fiscal, que está fora do MVP.
    cpf = models.CharField("CPF", max_length=11, blank=True, validators=[cpf_valido])
    data_nascimento = models.DateField("Data de nascimento", null=True, blank=True)

    telefone = models.CharField("Telefone", max_length=20, blank=True, validators=[telefone_valido])
    email = models.EmailField("E-mail", blank=True)

    cep = models.CharField("CEP", max_length=8, blank=True, validators=[cep_valido])
    logradouro = models.CharField("Logradouro", max_length=255, blank=True)
    numero = models.CharField("Número", max_length=20, blank=True)
    complemento = models.CharField("Complemento", max_length=100, blank=True)
    bairro = models.CharField("Bairro", max_length=100, blank=True)
    cidade = models.CharField("Cidade", max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, choices=UF.choices, blank=True)

    # Texto livre, e não um catálogo de medicamentos: o psicólogo não prescreve, ele **registra
    # o que o paciente relata usar**. Estruturar isso sugeriria uma precisão clínica que o dado
    # não tem, e puxaria o produto para perto de prontuário médico, que não é o que ele é.
    medicamento = models.TextField("Medicamento em uso", blank=True)

    data_primeira_sessao = models.DateField("Data da primeira sessão", null=True, blank=True)
    observacoes = models.TextField("Observações", blank=True)

    class Meta:
        verbose_name = "Paciente"
        verbose_name_plural = "Pacientes"
        ordering = ["nome"]
        constraints = [
            # Por psicólogo, e não global: dois psicólogos podem atender a mesma pessoa sem
            # saber um do outro, e o sistema não pode deixar isso transparecer (ADR-001).
            # `condition` exclui o branco, senão o segundo paciente sem CPF seria recusado.
            models.UniqueConstraint(
                fields=["psicologo", "cpf"],
                condition=models.Q(cpf__gt=""),
                name="cpf_unico_por_psicologo",
            ),
        ]

    def __str__(self) -> str:
        return self.nome

    @property
    def endereco(self) -> str:
        """Endereço em uma linha, pulando o que estiver vazio."""
        rua = " ".join(p for p in [self.logradouro, self.numero] if p)
        partes = [rua, self.complemento, self.bairro, self.cidade, self.uf]
        return " · ".join(p for p in partes if p)

    @property
    def idade(self) -> int | None:
        if not self.data_nascimento:
            return None
        from datetime import date

        hoje = date.today()
        faz_anos = (hoje.month, hoje.day) >= (self.data_nascimento.month, self.data_nascimento.day)
        return hoje.year - self.data_nascimento.year - (0 if faz_anos else 1)
