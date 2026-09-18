"""Endereço: o que é igual para paciente e para clínica mora aqui.

As unidades da federação e os validadores de CEP e telefone estavam duplicados em `pacientes` e
`contas`. Duplicação de lista de UF é inofensiva até alguém corrigir um acento num lugar só; a partir
daí o filtro de uma tela não casa com o da outra. `core` não depende de ninguém, então é onde cabe.
"""

from django.core.validators import RegexValidator
from django.db import models

cep_valido = RegexValidator(r"^(\d{8})?$", "CEP tem 8 números, sem traço.")
telefone_opcional = RegexValidator(
    r"^(\d{10,11})?$", "Telefone com DDD: 10 ou 11 números, sem espaços ou traços.")

# Fora do Brasil não há formato a exigir: o código postal pode ter letra e espaço, e o telefone vai de 6 a 15
# números (o teto do padrão E.164). O que se recusa é só o absurdo.
telefone_de_qualquer_pais = RegexValidator(r"^(\d{6,15})?$", "Telefone: de 6 a 15 números, com o código do país.")
codigo_postal_de_fora = RegexValidator(r"^[A-Za-z0-9 \-]{0,12}$", "Código postal: até 12 letras e números.")


def no_brasil(pais: str | None) -> bool:
    """País em branco conta como Brasil: é o padrão do cadastro, e o que todo cadastro antigo tem."""
    return (pais or "").strip().lower() in ("", "brasil", "brazil", "br")


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
