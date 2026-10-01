"""Sem assinatura que libere o sistema, o psicólogo tem um lugar só para ir: a tela da assinatura (ADR-094).

Dois casos levam para lá:

- **Conta recém-criada que ainda não escolheu como começar** — sem linha de assinatura e com o quiz por responder.
  É a ordem do cadastro: criar a conta, escolher entre assinar e testar, e só então o quiz.
- **Teste grátis encerrado.** O dado continua onde está; o que se fecha é a porta.

Conta **sem** linha de assinatura e **com** o quiz respondido passa: é a conta criada por código — semente, teste,
shell —, que `create_user` já entrega completa pela mesma razão (ADR-071). A tela de criar conta nunca produz uma
conta assim, porque ela sempre nasce com o quiz em aberto.

Vem **depois** do escopo (precisa do papel e do dono para ler a assinatura) e **antes** do quiz (a escolha do
plano acontece primeiro). Deixa `request.assinatura` para o aviso de teste do `base.html`.
"""

from django.conf import settings
from django.shortcuts import redirect
from django.urls import Resolver404, resolve

from assinaturas.models import Assinatura
from core import contexto

# Além das telas da própria assinatura: entrar, sair e criar conta. O perfil fica de fora de propósito — com o
# teste encerrado, ele é tão trancado quanto o resto.
LIBERADAS = {"contas:entrar", "contas:sair", "contas:criar_conta"}


class AssinaturaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.assinatura = None
        usuario = getattr(request, "user", None)
        # Sem escopo não há o que ler: a requisição anônima e a view que dispensou o escopo (sair) correm sob o
        # papel da web, que não alcança a tabela de assinaturas.
        if usuario is None or not usuario.is_authenticated or contexto.atual() is None:
            return self.get_response(request)

        assinatura = request.assinatura = Assinatura.objects.first()
        # ADR-114: na rodada aberta de testes não há plano nem prazo — a porta fica destrancada para todo mundo.
        # A verificação vem antes de qualquer conta de dias: com ela ligada, nada aqui redireciona.
        if getattr(settings, "ACESSO_LIBERADO", False):
            return self.get_response(request)
        precisa_escolher = assinatura is None and not usuario.cadastro_completo
        trancada = assinatura is not None and not assinatura.libera_o_sistema()
        if (precisa_escolher or trancada) and not self._liberada(request):
            return redirect("assinaturas:plano")
        return self.get_response(request)

    @staticmethod
    def _liberada(request) -> bool:
        try:
            rota = resolve(request.path_info)
        except Resolver404:
            return True
        if rota.namespace == "assinaturas":
            return True
        return f"{rota.namespace}:{rota.url_name}" in LIBERADAS
