"""O endereço que o Render consulta para saber se a aplicação está de pé (ADR-114).

Três cuidados, e cada um resolve uma forma de o deploy falhar por engano:

- **Não toca o banco.** Um banco lento ou hibernando derrubaria a verificação e o Render reiniciaria a aplicação
  — justamente quando ela está saudável e só esperando o Neon acordar.
- **Dispensa o escopo** (`core.escopo`): não há psicólogo autenticado, e pedir um daria `permission denied`.
- **Fica fora do redirecionamento para HTTPS** (`SECURE_REDIRECT_EXEMPT`, em `config/settings.py`). A verificação
  do Render chega pela rede interna, em HTTP: com o redirecionamento, ela receberia 301 e concluiria que o
  serviço caiu.
"""

from django.http import HttpResponse

from core.escopo import dispensa_escopo


@dispensa_escopo
def saude(request):
    return HttpResponse("ok", content_type="text/plain")
