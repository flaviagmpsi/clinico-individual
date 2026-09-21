"""Blocos que outros apps acrescentam à tela "Novo paciente" (ADR-095).

O horário fixo do paciente é assunto de `agenda` e `atendimentos`, e esses apps dependem de `pacientes` — nunca o
contrário. Para o bloco de horário morar **dentro** do cadastro sem inverter essa seta, `pacientes` só define o
encaixe: quem tem algo a perguntar no cadastro se registra aqui, no `ready()` do próprio app.

Um bloco é uma classe com:

- `template` — o pedaço de tela, incluído dentro do formulário do paciente (recebe o bloco como `bloco`);
- `__init__(request, dados=None)` — `dados` é o `POST`, ou `None` na primeira abertura;
- `is_valid()` — validado junto com o resto, sem curto-circuito, para os erros aparecerem todos de uma vez;
- `salvar(paciente, caso)` — roda **dentro** da transação do cadastro. Pode levantar `ValidationError`: aí nada é
  gravado, nem o paciente, e a mensagem volta para a tela por `recusar()`;
- `recusar(mensagem)` — põe o erro no bloco.
"""

_BLOCOS: list[type] = []


def registrar_bloco(bloco: type) -> None:
    if bloco not in _BLOCOS:
        _BLOCOS.append(bloco)


def blocos_registrados() -> list[type]:
    return list(_BLOCOS)
