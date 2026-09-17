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
