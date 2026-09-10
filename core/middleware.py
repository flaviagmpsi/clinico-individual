"""Middleware que amarra a requisição a um psicólogo, do começo ao fim.

Ele faz três coisas, nesta ordem, e a ordem importa:

1. **Abre uma transação** em volta da requisição inteira. Sem transação, o
   `set_config(is_local => true)` de `core/db.py` não teria a que se prender, e o
   impeditivo I-01 voltaria.
2. Define o escopo em Python (para o `TenantManager`) e no Postgres (para o RLS).
3. Limpa os dois no `finally`, mesmo se a view explodir.

O `ATOMIC_REQUESTS` do Django não serve aqui: ele envolve apenas a *view*, e o middleware
roda fora dele. Precisamos da transação começando antes de definirmos o escopo.
"""

from django.db import transaction

from core import contexto, db


class EscopoDoPsicologoMiddleware:
    """Deriva o psicólogo do usuário autenticado e o aplica às três camadas."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        psicologo_id = self._psicologo_de(request)

        if psicologo_id is None:
            # Requisição anônima (login, healthcheck, estáticos). Sem escopo, e é o
            # comportamento correto: qualquer consulta a dado de domínio aqui deve explodir.
            return self.get_response(request)

        with transaction.atomic():
            # A ordem importa: primeiro perder o privilégio de ignorar o RLS, depois dizer
            # de quem é o dado. O contrário deixaria uma janela rodando como dono do banco.
            db.assumir_papel_da_aplicacao()
            contexto.definir(psicologo_id)
            db.aplicar_escopo(psicologo_id)
            try:
                return self.get_response(request)
            finally:
                # Rede de segurança. O Postgres já descarta a variável no fim desta
                # transação; o contexto Python é quem realmente precisa ser zerado, porque
                # a thread pode ser reaproveitada pelo servidor.
                contexto.definir(None)

    @staticmethod
    def _psicologo_de(request) -> int | None:
        usuario = getattr(request, "user", None)
        if usuario is None or not usuario.is_authenticated:
            return None
        # O psicólogo **é** o usuário (ver `contas.models`), então o id do tenant é a própria
        # chave do usuário. Se um dia essa relação deixar de ser 1-para-1, é aqui que muda —
        # e só aqui.
        return usuario.pk
