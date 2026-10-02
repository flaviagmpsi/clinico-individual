"""Middleware que amarra a requisição a um papel de banco, do começo ao fim.

Ele faz quatro coisas, nesta ordem, e a ordem importa:

1. **Abre uma transação** em volta da requisição inteira. Sem transação, o
   `set_config(is_local => true)` de `core/db.py` não teria a que se prender, e o
   impeditivo I-01 voltaria.
2. **Desce de papel — sempre**, inclusive na requisição anônima. A versão anterior devolvia
   cedo quando não havia usuário, e com isso login, cadastro e healthcheck rodavam como dono
   do banco, que tem `BYPASSRLS`: a superfície pública inteira ficava sem a terceira camada
   (ADR-046). Anônimo agora corre sob `hamilton_web`, que não tem permissão em tabela clínica.
3. Define o escopo em Python (para o `TenantManager`) e no Postgres (para o RLS).
4. Limpa o contexto Python no `finally`, mesmo se a view explodir.

Uma view pode **abrir mão** do escopo com `@core.escopo.dispensa_escopo` e correr sob
`hamilton_web`. Existe por causa do logout, e o raciocínio está em `core/escopo.py`.

O `ATOMIC_REQUESTS` do Django não serve aqui: ele envolve apenas a *view*, e o middleware
roda fora dele. Precisamos da transação começando antes de definirmos o papel.

⚠️ O que roda **fora** desta transação — `SessionMiddleware.process_response`, por exemplo —
corre sob o papel com que a aplicação *conectou*. Em produção esse papel é `hamilton_web`
(ver `.env.example`), e é por isso que ele tem grant em `django_session`. Em desenvolvimento,
conectando como dono, esse trecho roda privilegiado: `core.checks` recusa esse arranjo quando
`DEBUG=False`.
"""

from django.db import transaction
from django.urls import Resolver404, resolve

from core import contexto, db


class EscopoDoPsicologoMiddleware:
    """Deriva o psicólogo do usuário autenticado e o aplica às três camadas."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Resolvido **antes** da transação: `request.user` é preguiçoso e a consulta que o
        # carrega precisa da tabela de login, que só `hamilton_web` enxerga sem escopo.
        psicologo_id = self._psicologo_de(request)
        if self._dispensa_escopo(request):
            # A view declarou que não toca dado de domínio (`core.escopo.dispensa_escopo`).
            # É o caso do logout, que precisa apagar a sessão — tabela que `hamilton_app` não
            # alcança desde a ADR-046.
            psicologo_id = None

        with transaction.atomic():
            if psicologo_id is None:
                # Sem escopo, e é o comportamento correto: qualquer consulta a dado de
                # domínio aqui deve explodir — por falta de permissão, não por sorte.
                db.assumir_papel_da_web()
                return self.get_response(request)

            # A ordem importa: primeiro perder o privilégio de ignorar o RLS, depois dizer
            # de quem é o dado. O contrário deixaria uma janela rodando privilegiada.
            db.assumir_papel_da_aplicacao()
            contexto.definir(psicologo_id)
            # ADR-115: a conta marcada como superusuária atravessa o isolamento. Quem decide é o Django, aqui;
            # o banco só obedece ao que esta transação declarou.
            db.aplicar_escopo(psicologo_id, administradora=bool(getattr(request.user, "is_superuser", False)))
            try:
                return self.get_response(request)
            finally:
                # O Postgres já descarta a variável no fim desta transação; o contexto Python
                # é quem realmente precisa ser zerado, porque a thread pode ser reaproveitada.
                contexto.definir(None)

    @staticmethod
    def _dispensa_escopo(request) -> bool:
        try:
            return getattr(resolve(request.path_info).func, "dispensa_escopo", False)
        except Resolver404:
            # URL inexistente: sem escopo mesmo. O 404 não precisa ver dado de ninguém.
            return True

    @staticmethod
    def _psicologo_de(request) -> int | None:
        usuario = getattr(request, "user", None)
        if usuario is None or not usuario.is_authenticated:
            return None
        # O psicólogo **é** o usuário (ver `contas.models`), então o id do tenant é a própria
        # chave do usuário. Se um dia essa relação deixar de ser 1-para-1, é aqui que muda —
        # e só aqui.
        return usuario.pk
