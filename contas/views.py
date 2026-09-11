"""Entrada e saída do sistema, e o perfil do psicólogo."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import UpdateView

from contas.forms import LoginForm, PerfilForm
from core.escopo import dispensa_escopo


class Entrar(LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@method_decorator(dispensa_escopo, name="dispatch")
class Sair(LogoutView):
    """Sair apaga a linha da sessão, e `hamilton_app` não alcança `django_session` (ADR-046).

    É a única operação de um usuário autenticado que não toca dado de domínio, então ela
    dispensa o escopo e roda sob `hamilton_web`. O raciocínio completo está em `core/escopo.py`.
    """

    next_page = reverse_lazy("contas:entrar")


class Perfil(LoginRequiredMixin, UpdateView):
    """O psicólogo edita a si mesmo — e só a si mesmo.

    Não há `get_object` filtrando por dono: `request.user` **é** o tenant (ADR-001), e a policy
    de `contas_psicologo` recusaria qualquer outra linha de todo jeito.
    """

    form_class = PerfilForm
    template_name = "contas/perfil.html"
    success_url = reverse_lazy("contas:perfil")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Perfil atualizado.")
        return super().form_valid(form)
