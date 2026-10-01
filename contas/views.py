"""Entrada e saída do sistema, o quiz de cadastro e o perfil do psicólogo."""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, TemplateView, UpdateView

from contas.configuracoes import DespesasForm, RegimeNovoForm
from contas.forms import (ClinicaForm, ComoAtendeForm, CriarContaForm, IdentificacaoForm, LoginForm, PerfilForm,
                          RegimeForm)
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


class GravaSemRepetir:
    """CPF ou e-mail que já é de outra conta vira mensagem no campo, e não erro 500.

    O formulário não tem como conferir antes: sob o escopo do psicólogo, o RLS esconde as outras contas (ADR-046) —
    que é exatamente o que se quer dele. Então quem sabe é a coluna única, e aqui a recusa do banco é traduzida. O
    `atomic` é o ponto de retorno: sem ele, a transação da requisição ficaria inutilizada depois do erro.
    """

    REPETIDOS = {"cpf": "Já existe uma conta com este CPF.", "email": "Já existe uma conta com este e-mail."}

    def form_valid(self, form):
        try:
            with transaction.atomic():
                return super().form_valid(form)
        except IntegrityError as erro:
            for campo, mensagem in self.REPETIDOS.items():
                if campo in str(erro) and campo in form.fields:
                    form.add_error(campo, mensagem)
                    return self.form_invalid(form)
            raise


class Perfil(GravaSemRepetir, LoginRequiredMixin, UpdateView):
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
        resposta = super().form_valid(form)
        if resposta.status_code == 302:  # gravou; CPF ou e-mail repetido volta para a tela com o erro no campo
            messages.success(self.request, "Perfil atualizado.")
        return resposta


class Configuracoes(LoginRequiredMixin, TemplateView):
    """O que o psicólogo liga, desliga e troca depois do cadastro (ADR-100)."""

    template_name = "contas/configuracoes.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        psicologo = self.request.user
        contexto.setdefault("despesas", DespesasForm(instance=psicologo))
        contexto.setdefault("regime", RegimeNovoForm(psicologo=psicologo))
        contexto["mudancas"] = psicologo.mudancas_de_regime.all()
        return contexto

    def post(self, request, *args, **kwargs):
        if request.POST.get("acao") == "regime":
            return self._trocar_regime(request)
        formulario = DespesasForm(request.POST, instance=request.user)
        if formulario.is_valid():
            formulario.save()
            messages.success(request, "Preferências salvas.")
            return redirect("contas:configuracoes")
        return self.render_to_response(self.get_context_data(despesas=formulario))

    def _trocar_regime(self, request):
        formulario = RegimeNovoForm(request.POST, psicologo=request.user)
        if formulario.is_valid():
            try:
                with transaction.atomic():
                    mudanca = formulario.aplicar()
            except ValidationError as erro:
                formulario.add_error(None, erro.messages[0])
                return self.render_to_response(self.get_context_data(regime=formulario))
            messages.success(request, f"Regime alterado: {mudanca}. O financeiro anterior a essa data não muda.")
            return redirect("contas:configuracoes")
        return self.render_to_response(self.get_context_data(regime=formulario))


# O quiz de cadastro (C-10, ADR-071). Cada passo grava o que coletou: quem larga no meio volta de onde parou,
# e não recomeça. O último marca `quiz_concluido_em`, que é o que libera o resto do sistema.
# ADR-094: a conta nasce só com login e CRP, então o quiz ganhou a pergunta "quem é você" — e a do endereço só
# aparece para quem atende presencialmente.
PASSOS = [
    (IdentificacaoForm, "Quem é você"),
    (RegimeForm, "Pessoa física ou jurídica, e as suas despesas"),
    (ComoAtendeForm, "Sua abordagem e como você atende"),
    (ClinicaForm, "Onde você atende presencialmente"),
]


@method_decorator(dispensa_escopo, name="dispatch")
class CriarConta(CreateView):
    """A porta de entrada (ADR-094): login e CRP. A conta passa a existir, o psicólogo já entra logado e vai
    escolher entre assinar e testar grátis; o quiz vem depois, já dentro do sistema.

    `dispensa_escopo` porque aqui ainda não há psicólogo autenticado de quem derivar o escopo — a criação
    roda sob o papel da web, como o login (ADR-046).
    """

    form_class = CriarContaForm
    template_name = "contas/criar_conta.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("painel")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        resposta = super().form_valid(form)
        login(self.request, self.object)
        return resposta

    def get_success_url(self):
        return reverse("assinaturas:plano")


class QuizDeCadastro(GravaSemRepetir, LoginRequiredMixin, UpdateView):
    """O que o sistema precisa saber para propor as coisas certas — perguntado na primeira entrada (ADR-094)."""

    template_name = "contas/quiz.html"

    @property
    def passo(self) -> int:
        numero = self.kwargs["passo"]
        if not 1 <= numero <= len(PASSOS):
            raise Http404("Passo inexistente.")
        return numero

    def dispatch(self, request, *args, **kwargs):
        # Ninguém conclui o quiz pulando pergunta pela barra de endereço: sem nome e CPF, o documento sairia em
        # branco; sem abordagem e forma de atendimento, o sistema não sabe o que propor.
        if request.user.is_authenticated:
            pendente = self.primeira_pendente(request.user)
            if pendente is not None and self.passo > pendente:
                return redirect("contas:quiz", passo=pendente)
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def primeira_pendente(psicologo) -> int | None:
        if not (psicologo.nome_completo and psicologo.cpf and psicologo.telefone):
            return 1
        if not psicologo.abordagens:
            return 3
        return None

    def get_form_class(self):
        return PASSOS[self.passo - 1][0]

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(passo=self.passo, total=len(PASSOS), titulo=PASSOS[self.passo - 1][1],
                        ultimo=self.passo == len(PASSOS), esconder_barra=True)
        return contexto

    def terminou(self) -> bool:
        """A última pergunta é o endereço do presencial — quem atende só online termina uma antes."""
        return self.passo == len(PASSOS) or (self.passo == len(PASSOS) - 1 and not self.object.atende_presencial)

    def form_valid(self, form):
        resposta = super().form_valid(form)
        if resposta.status_code == 302 and self.terminou():
            self.object.quiz_concluido_em = timezone.now()
            self.object.save()
            messages.success(self.request, "Cadastro concluído. Bem-vindo ao Hamilton.")
        return resposta

    def get_success_url(self):
        if self.terminou():
            return reverse("painel")
        return reverse("contas:quiz", args=[self.passo + 1])
