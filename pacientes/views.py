"""Telas do cadastro de pacientes.

Nenhuma view filtra por psicólogo. Não é descuido: `Paciente.objects` é o `TenantManager`, que
filtra sozinho e **levanta exceção** se não souber de quem é o dado (ADR-001). Uma view que
esquecesse o filtro não vazaria — ela quebraria. É a diferença entre confiar no programador e
confiar na fundação.

**O `Caso` não tem tela no atendimento individual** (ADR-026). Valor, forma de cobrança e quem paga
aparecem na ficha do paciente, sem a palavra "caso". Ela só aparece em `NovoCasoColetivo` e
`DetalheCaso`, para quem atende casal ou família.

Toda busca de objeto a partir da URL acontece **depois** do `LoginRequiredMixin` — nunca no
`dispatch`. Buscar antes faria o visitante anônimo receber um erro de escopo em vez de ser mandado
para o login.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Count, ProtectedError, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, UpdateView

from core import auditoria
from core.models import RegistroAuditoria
from pacientes.forms import (
    CasoColetivoForm,
    CondicaoCobrancaForm,
    PacienteForm,
    PagadorForm,
    ResponsavelLegalForm,
)
from pacientes.models import Caso, Paciente, ResponsavelLegal
from pacientes.servicos import (
    cadastrar_paciente,
    caso_individual_de,
    criar_caso_coletivo,
    excluir_caso_coletivo,
    excluir_paciente,
    pacientes_ativos,
    pacientes_encerrados,
)


class ListaPacientes(LoginRequiredMixin, ListView):
    """Em atendimento ou encerrados (ADR-055). Encerrado não é apagado: só sai da lista padrão."""

    model = Paciente
    template_name = "pacientes/lista.html"
    context_object_name = "pacientes"
    paginate_by = 25

    def situacao(self) -> str:
        return "encerrados" if self.request.GET.get("situacao") == "encerrados" else "ativos"

    def get_queryset(self):
        pacientes = pacientes_encerrados() if self.situacao() == "encerrados" else pacientes_ativos()
        busca = self.request.GET.get("q", "").strip()
        if busca:
            pacientes = pacientes.filter(
                Q(nome__icontains=busca) | Q(cpf__contains=busca) | Q(email__icontains=busca)
            )
        return pacientes

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(busca=self.request.GET.get("q", ""), situacao=self.situacao(),
                        total_ativos=pacientes_ativos().count(), total_encerrados=pacientes_encerrados().count())
        return contexto


class DetalhePaciente(LoginRequiredMixin, DetailView):
    model = Paciente
    template_name = "pacientes/detalhe.html"
    context_object_name = "paciente"

    def get(self, request, *args, **kwargs):
        resposta = super().get(request, *args, **kwargs)
        auditoria.registrar(auditoria.Acao.VER, self.object)  # ADR-057: abrir a ficha é ver dado do paciente
        return resposta

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        paciente = self.object
        caso = caso_individual_de(paciente)
        contexto["caso"] = caso
        contexto["condicao"] = caso.condicao_vigente() if caso else None
        contexto["desfecho"] = caso.desfecho_aberto() if caso else None
        contexto["desfechos_anteriores"] = caso.desfechos_anteriores() if caso else []
        contexto["responsaveis"] = paciente.responsaveis.all()
        # `annotate` **antes** do `filter`: na ordem inversa o Django reaproveitaria o mesmo join do
        # filtro e contaria só a participação deste paciente — todo caso pareceria individual.
        contexto["casos_coletivos"] = (
            Caso.objects.annotate(participantes=Count("participacoes"))
            .filter(participantes__gt=1, participacoes__paciente=paciente)
            .prefetch_related("pacientes")
        )
        return contexto


class NovoPaciente(LoginRequiredMixin, CreateView):
    """Cadastra o paciente **com** o caso individual dele, numa transação só (`servicos`)."""

    model = Paciente
    form_class = PacienteForm
    template_name = "pacientes/formulario.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.setdefault("cobranca", CondicaoCobrancaForm(
            prefix="cobranca", dia_vencimento_padrao=self.request.user.dia_vencimento_mensalidade))
        return contexto

    def post(self, request, *args, **kwargs):
        self.object = None
        form = self.get_form()
        cobranca = CondicaoCobrancaForm(
            request.POST, prefix="cobranca", dia_vencimento_padrao=request.user.dia_vencimento_mensalidade)
        # Os dois validados sempre, sem curto-circuito: quem errou o CPF e o vencimento precisa ver
        # os dois erros de uma vez, e não um de cada vez a cada envio.
        validos = [form.is_valid(), cobranca.is_valid()]
        if all(validos):
            return self.cadastrar(form, cobranca)
        return self.render_to_response(self.get_context_data(form=form, cobranca=cobranca))

    def cadastrar(self, form, cobranca):
        self.object = form.save(commit=False)
        cadastrar_paciente(self.object, **cobranca.condicao())
        messages.success(self.request, f"Paciente {self.object.nome} cadastrado.")
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("pacientes:detalhe", args=[self.object.pk])


class EditarPaciente(LoginRequiredMixin, UpdateView):
    """Dados pessoais. A **troca** de valor e forma de cobrança não mora aqui: quando uma troca passa
    a valer — na hora ou no dia 1º do mês seguinte — ainda está em decisão, e a tela só entra
    depois dela."""

    model = Paciente
    form_class = PacienteForm
    template_name = "pacientes/formulario.html"

    def get(self, request, *args, **kwargs):
        resposta = super().get(request, *args, **kwargs)
        auditoria.registrar(auditoria.Acao.VER, self.object)  # o formulário mostra o cadastro inteiro
        return resposta

    def form_valid(self, form):
        messages.success(self.request, "Cadastro atualizado.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("pacientes:detalhe", args=[self.object.pk])


class HistoricoPaciente(LoginRequiredMixin, ListView):
    """A trilha de auditoria de um paciente: quem viu, criou, alterou e excluiu o quê, e quando (ADR-057).

    Mostra os campos alterados, nunca os valores — a trilha não os guarda.
    """

    template_name = "pacientes/historico.html"
    context_object_name = "registros"
    paginate_by = 50

    def get_queryset(self):
        self.paciente = get_object_or_404(Paciente, pk=self.kwargs["pk"])
        return RegistroAuditoria.objects.filter(titular=Paciente._meta.label_lower, titular_id=self.paciente.pk)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["paciente"] = self.paciente
        return contexto


class ExcluirPaciente(LoginRequiredMixin, DeleteView):
    """Exclusão de verdade, para cadastro feito por engano. A regra está em `servicos.excluir_paciente`."""

    model = Paciente
    template_name = "pacientes/excluir.html"
    success_url = reverse_lazy("pacientes:lista")

    def form_valid(self, form):
        nome = self.object.nome
        try:
            excluir_paciente(self.object)
        except ValidationError as erro:
            messages.error(self.request, erro.messages[0])
            return redirect("pacientes:detalhe", pk=self.object.pk)
        except ProtectedError:
            messages.error(self.request, "Não foi possível excluir: há registros ligados a este paciente.")
            return redirect("pacientes:detalhe", pk=self.object.pk)
        messages.success(self.request, f"Paciente {nome} excluído.")
        return redirect(self.success_url)


class EditarAtendimento(LoginRequiredMixin, UpdateView):
    """Quem paga o atendimento individual (ADR-009) — sem a palavra "caso" na tela."""

    form_class = PagadorForm
    template_name = "pacientes/pagador.html"

    def get_object(self, queryset=None):
        self.paciente = get_object_or_404(Paciente, pk=self.kwargs["pk"])
        caso = caso_individual_de(self.paciente)
        if caso is None:
            raise Http404("Paciente sem atendimento individual.")
        return caso

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["paciente"] = self.paciente
        return kwargs

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["paciente"] = self.paciente
        return contexto

    def form_valid(self, form):
        messages.success(self.request, "Pagador atualizado.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("pacientes:detalhe", args=[self.paciente.pk])


class _ResponsavelBase(LoginRequiredMixin):
    model = ResponsavelLegal
    form_class = ResponsavelLegalForm
    template_name = "pacientes/responsavel_form.html"

    def get_success_url(self):
        return reverse("pacientes:detalhe", args=[self.object.paciente_id])


class NovoResponsavel(_ResponsavelBase, CreateView):
    def paciente(self) -> Paciente:
        if not hasattr(self, "_paciente"):
            self._paciente = get_object_or_404(Paciente, pk=self.kwargs["pk"])
        return self._paciente

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # O paciente vem da URL, já filtrado pelo dono; não existe campo de paciente na tela.
        kwargs["instance"] = ResponsavelLegal(paciente=self.paciente())
        return kwargs

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["paciente"] = self.paciente()
        return contexto

    def form_valid(self, form):
        messages.success(self.request, "Responsável legal adicionado.")
        return super().form_valid(form)


class EditarResponsavel(_ResponsavelBase, UpdateView):
    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["paciente"] = self.object.paciente
        return contexto

    def form_valid(self, form):
        messages.success(self.request, "Responsável legal atualizado.")
        return super().form_valid(form)


class ExcluirResponsavel(LoginRequiredMixin, DeleteView):
    model = ResponsavelLegal
    template_name = "pacientes/responsavel_excluir.html"
    context_object_name = "responsavel"

    def form_valid(self, form):
        paciente_id = self.object.paciente_id
        nome = self.object.nome
        self.object.delete()
        messages.success(self.request, f"{nome} removido dos responsáveis.")
        return redirect("pacientes:detalhe", pk=paciente_id)


class NovoCasoColetivo(LoginRequiredMixin, FormView):
    """Atendimento de casal ou família a partir de pacientes já cadastrados (ADR-026)."""

    form_class = CasoColetivoForm
    template_name = "pacientes/caso_novo.html"

    def get_initial(self):
        inicial = super().get_initial()
        paciente = self.request.GET.get("paciente", "")
        if paciente.isdigit():
            # Um id alheio aqui não faz nada: ele simplesmente não está entre as opções do campo.
            inicial["pacientes"] = [int(paciente)]
        return inicial

    def form_valid(self, form):
        caso = criar_caso_coletivo(form.cleaned_data["pacientes"], descricao=form.cleaned_data["descricao"])
        messages.success(self.request, "Atendimento coletivo criado.")
        return redirect("pacientes:caso", pk=caso.pk)


class DetalheCaso(LoginRequiredMixin, DetailView):
    model = Caso
    template_name = "pacientes/caso_detalhe.html"
    context_object_name = "caso"

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.individual:
            # O caso de um não tem tela própria: quem chega aqui vai para a ficha do paciente.
            return redirect("pacientes:detalhe", pk=self.object.pacientes.first().pk)
        return self.render_to_response(self.get_context_data(object=self.object))

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["participantes"] = self.object.pacientes.all()
        contexto["condicao"] = self.object.condicao_vigente()
        contexto["desfecho"] = self.object.desfecho_aberto()
        contexto["desfechos_anteriores"] = self.object.desfechos_anteriores()
        return contexto


class ExcluirCasoColetivo(LoginRequiredMixin, DeleteView):
    """Desfaz um atendimento coletivo. A regra está em `servicos.excluir_caso_coletivo`."""

    model = Caso
    template_name = "pacientes/caso_excluir.html"
    context_object_name = "caso"
    success_url = reverse_lazy("pacientes:lista")

    def get_object(self, queryset=None):
        caso = super().get_object(queryset)
        if caso.individual:
            raise Http404("O atendimento individual acompanha o paciente e sai junto com ele.")
        return caso

    def form_valid(self, form):
        descricao = str(self.object)
        try:
            excluir_caso_coletivo(self.object)
        except ValidationError as erro:
            messages.error(self.request, erro.messages[0])
            return redirect("pacientes:caso", pk=self.object.pk)
        messages.success(self.request, f"Atendimento {descricao} excluído.")
        return redirect(self.success_url)
