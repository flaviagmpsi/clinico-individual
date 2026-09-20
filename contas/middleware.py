"""Enquanto o quiz não termina, o sistema leva o psicólogo de volta a ele (C-10, ADR-071).

Sem regime, abordagem e formas de atendimento, metade do que o Hamilton propõe sai errado — do padrão de
sessão ao documento fiscal. Em vez de deixar telas meio funcionando, o cadastro incompleto tem um lugar só.

O redirecionamento vale só para quem está autenticado e não concluiu o quiz, e deixa passar o próprio quiz,
a saída e as telas de autenticação — senão a conta recém-criada ficaria presa sem conseguir nem sair.
"""

from django.shortcuts import redirect
from django.urls import resolve, reverse

LIBERADAS = {"contas:quiz", "contas:criar_conta", "contas:entrar", "contas:sair"}


class CadastroCompletoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, "user", None)
        if usuario is not None and usuario.is_authenticated and not usuario.cadastro_completo:
            rota = resolve(request.path_info)
            nome = f"{rota.namespace}:{rota.url_name}" if rota.namespace else rota.url_name
            # As telas da assinatura passam: a escolha entre assinar e testar vem **antes** do quiz (ADR-094).
            if nome not in LIBERADAS and rota.namespace != "assinaturas":
                return redirect(reverse("contas:quiz", args=[1]))
        return self.get_response(request)
