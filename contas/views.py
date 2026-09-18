"""Entrada e saída do sistema, o quiz de cadastro e o perfil do psicólogo."""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, UpdateView

from contas.forms import ClinicaForm, ComoAtendeForm, CriarContaForm, LoginForm, PerfilForm, RegimeForm
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


# O quiz de cadastro (C-10, ADR-071). Cada passo grava o que coletou: quem larga no meio volta de onde parou,
# e não recomeça. O último marca `quiz_concluido_em`, que é o que libera o resto do sistema.
PASSOS = [
    (RegimeForm, "Como você atende, para a nota e o imposto"),
    (ComoAtendeForm, "Sua abordagem e as formas de atendimento"),
    (ClinicaForm, "Onde você atende"),
]


@method_decorator(dispensa_escopo, name="dispatch")
class CriarConta(CreateView):
    """Passo 1: a conta passa a existir e o psicólogo já entra logado.

    `dispensa_escopo` porque aqui ainda não há psicólogo autenticado de quem derivar o escopo — a criação
    roda sob o papel da web, como o login (ADR-046).
    """

    form_class = CriarContaForm
    template_name = "contas/criar_conta.html"
    extra_context = {"total": len(PASSOS) + 1}

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("painel")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        resposta = super().form_valid(form)
        login(self.request, self.object)
        messages.success(self.request, "Conta criada. Faltam três passos rápidos.")
        return resposta

    def get_success_url(self):
        return reverse("contas:quiz", args=[1])


class QuizDeCadastro(LoginRequiredMixin, UpdateView):
    """Passos 2 a 4: o que o sistema precisa saber para propor as coisas certas."""

    template_name = "contas/quiz.html"

    @property
    def passo(self) -> int:
        numero = self.kwargs["passo"]
        if not 1 <= numero <= len(PASSOS):
            raise Http404("Passo inexistente.")
        return numero

    def get_form_class(self):
        return PASSOS[self.passo - 1][0]

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(passo=self.passo, total=len(PASSOS) + 1, titulo=PASSOS[self.passo - 1][1],
                        ultimo=self.passo == len(PASSOS), esconder_barra=True)
        return contexto

    def form_valid(self, form):
        resposta = super().form_valid(form)
        if self.passo == len(PASSOS):
            self.object.quiz_concluido_em = timezone.now()
            self.object.save()
            messages.success(self.request, "Cadastro concluído. Bem-vindo ao Hamilton.")
        return resposta

    def get_success_url(self):
        if self.passo == len(PASSOS):
            return reverse("painel")
        return reverse("contas:quiz", args=[self.passo + 1])
