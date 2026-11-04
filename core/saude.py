"""O endereço que o Render consulta para saber se a aplicação está de pé (ADR-114, ADR-145).

Quatro cuidados, e cada um resolve uma forma de o deploy — ou a fatura — falhar por engano:

- **Não toca o banco — nem um statement.** Um banco lento ou hibernando derrubaria a verificação e o Render
  reiniciaria a aplicação, justamente quando ela está saudável e só esperando o Neon acordar. E o Neon só dorme
  depois de 5 minutos sem **nenhum** statement: a checagem do Render, a cada poucos segundos, o manteria acordado
  o mês inteiro (ADR-145). Não basta a view não consultar nada — até a ADR-145 o `EscopoDoPsicologoMiddleware`
  abria transação e fazia `SET LOCAL ROLE` em volta dela, e era isso que segurava o banco.
- **Responde antes da pilha de middlewares** (`SaudeMiddleware`, logo depois do `SecurityMiddleware`): sessão,
  autenticação, escopo e assinatura nem chegam a rodar. A exceção vale **só** para o caminho exato `/saude/`, que
  não lê dado nenhum — qualquer outra rota anônima continua descendo para `hamilton_web` (ADR-046).
- **Dispensa o escopo** (`core.escopo`), por garantia: se um dia a rota for alcançada pela pilha inteira, ela
  continua sem pedir psicólogo.
- **Fica fora do redirecionamento para HTTPS** (`SECURE_REDIRECT_EXEMPT`, em `config/settings.py`). A verificação
  do Render chega pela rede interna, em HTTP: com o redirecionamento, ela receberia 301 e concluiria que o
  serviço caiu. Por isso o `SaudeMiddleware` vem **depois** do `SecurityMiddleware`, que é quem aplica a isenção.
"""

from django.http import HttpResponse

from core.escopo import dispensa_escopo

CAMINHO = "/saude/"


@dispensa_escopo
def saude(request):
    return HttpResponse("ok", content_type="text/plain")


class SaudeMiddleware:
    """Responde `/saude/` na hora, sem passar pelos middlewares que tocam o banco (ADR-145)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Comparação exata com `path_info`: `/saude`, `/saude/x` ou `/saudeX` seguem o caminho normal, com
        # transação e papel. A brecha é do tamanho de uma URL que devolve "ok" e nada mais.
        if request.path_info == CAMINHO:
            return saude(request)
        return self.get_response(request)
