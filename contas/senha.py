"""Recuperação de senha (ADR-114).

Sem isto, um psicólogo que esquece a senha fica trancado para sempre e só sai de lá com alguém mexendo no banco à
mão. Numa rodada aberta de testes, em que cada pessoa cria a própria conta, isso é o bastante para ela desistir.

**As quatro telas rodam sob `hamilton_web`**, sem escopo de psicólogo — como o login, e pela mesma razão: quem
pede a recuperação não está autenticado, e procurar o usuário é justamente o que falta fazer. É o `dispensa_escopo`
da ADR-046. A consequência é que nenhuma delas pode tocar dado clínico, e nenhuma toca.

**O que a tela responde é sempre o mesmo**, exista a conta ou não. Dizer "não há conta com este e-mail" entrega a
quem pergunta a lista de quem usa o sistema — e, num sistema de psicólogos, saber que alguém tem conta já é
informação sobre essa pessoa.
"""

from django.contrib.auth import views as auth
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator

from core.escopo import dispensa_escopo


@method_decorator(dispensa_escopo, name="dispatch")
class Pedir(auth.PasswordResetView):
    """Pede o e-mail e manda o link. O endereço remetente e o SMTP vêm do ambiente."""

    template_name = "registration/senha_pedir.html"
    email_template_name = "registration/senha_email.txt"
    subject_template_name = "registration/senha_assunto.txt"
    success_url = reverse_lazy("contas:senha_enviada")


@method_decorator(dispensa_escopo, name="dispatch")
class Enviada(auth.PasswordResetDoneView):
    template_name = "registration/senha_enviada.html"


@method_decorator(dispensa_escopo, name="dispatch")
class Trocar(auth.PasswordResetConfirmView):
    """O link do e-mail. O Django já valida o token e o invalida depois de usado."""

    template_name = "registration/senha_trocar.html"
    success_url = reverse_lazy("contas:senha_trocada")


@method_decorator(dispensa_escopo, name="dispatch")
class Trocada(auth.PasswordResetCompleteView):
    template_name = "registration/senha_trocada.html"
