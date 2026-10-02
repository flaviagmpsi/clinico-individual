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
from django.db import transaction
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
from indicadores import estatisticas, fichas, periodo
from pacientes import convites
from pacientes.cadastro import blocos_registrados
from pacientes.forms import GENEROS_SUGERIDOS
from pacientes.models import Caso, CondicaoCobranca, ConviteDeCadastro, Paciente, ResponsavelLegal
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
                        total_ativos=pacientes_ativos().count(), total_encerrados=pacientes_encerrados().count(),
                        cadastros_para_revisar=convites.esperando_revisao())
        # ADR-103: quem vem e quem falta fica ao lado da lista de pacientes, e não numa aba de estatísticas.
        contexto.update(periodo.contexto_do_seletor(self.request))
        presenca = estatisticas.presenca_dos_pacientes(contexto["periodo"])
        # ADR-109: a lista virou blocos, e cada bloco mostra horário, frequência, o que está em aberto e a
        # presença. Tudo em **uma** carga (`indicadores.fichas`), e não uma consulta por paciente.
        contexto["fichas"] = fichas.fichas(contexto["pacientes"], presenca.por_paciente)
        contexto.update(presenca=presenca, grafico={
            "presenca": [presenca.presenca.presentes, presenca.presenca.faltas,
                         presenca.presenca.canceladas_pelo_cliente],
        })
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

    def convite(self) -> ConviteDeCadastro | None:
        """`?convite=<id>`: o cadastro que o paciente preencheu pelo link, aberto para revisão (ADR-081).

        O formulário é o mesmo de sempre, já com as respostas dele. Nada vira paciente antes de o psicólogo
        salvar — e é nesse salvar que ele completa o que só ele sabe: cobrança, modalidade, primeira sessão.
        """
        if not hasattr(self, "_convite"):
            codigo = self.request.GET.get("convite", "")
            self._convite = (get_object_or_404(ConviteDeCadastro, pk=int(codigo), respondido_em__isnull=False,
                                               aceito_em__isnull=True) if codigo.isdigit() else None)
        return self._convite

    def get_initial(self):
        inicial = super().get_initial()
        if self.convite() is not None:
            inicial.update(convites.iniciais_do_paciente(self.convite()))
        return inicial

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.setdefault("cobranca", CondicaoCobrancaForm(
            prefix="cobranca", dia_vencimento_padrao=self.request.user.dia_vencimento_mensalidade,
            tipo_vencimento_padrao=self.request.user.tipo_vencimento_mensalidade))
        # ADR-095: o que outros apps perguntam no cadastro — hoje, o horário de atendimento.
        contexto.setdefault("blocos", [bloco(self.request) for bloco in blocos_registrados()])
        contexto.update(convite=self.convite(), generos=GENEROS_SUGERIDOS)
        return contexto

    def post(self, request, *args, **kwargs):
        self.object = None
        form = self.get_form()
        blocos = [bloco(request, request.POST) for bloco in blocos_registrados()]
        cobranca = CondicaoCobrancaForm(
            request.POST, prefix="cobranca", dia_vencimento_padrao=request.user.dia_vencimento_mensalidade,
            tipo_vencimento_padrao=request.user.tipo_vencimento_mensalidade)
        # Os dois validados sempre, sem curto-circuito: quem errou o CPF e o vencimento precisa ver
        # os dois erros de uma vez, e não um de cada vez a cada envio.
        validos = [form.is_valid(), cobranca.is_valid()] + [bloco.is_valid() for bloco in blocos]
        if all(validos) and self.cadastrar(form, cobranca, blocos):
            messages.success(self.request, f"Paciente {self.object.nome} cadastrado.")
            self._avisar_sobre_a_cobranca(cobranca)
            return redirect(self.get_success_url())
        return self.render_to_response(self.get_context_data(form=form, cobranca=cobranca, blocos=blocos))

    def cadastrar(self, form, cobranca, blocos) -> bool:
        """Tudo ou nada: se um bloco recusar — horário ocupado, por exemplo —, nem o paciente é gravado."""
        bloco = None
        try:
            with transaction.atomic():
                self.object = form.save(commit=False)
                caso = cadastrar_paciente(self.object, **cobranca.condicao())
                form.salvar_contatos_de_emergencia(self.object)
                if self.convite() is not None:
                    convites.aceitar(self.convite(), self.object)
                for bloco in blocos:
                    bloco.salvar(self.object, caso)
        except ValidationError as erro:
            if bloco is None:
                raise
            bloco.recusar(erro.messages[0])
            # O paciente não foi gravado: a instância não pode sair daqui parecendo que existe.
            self.object = None
            form.instance.pk = None
            return False
        return True

    def _avisar_sobre_a_cobranca(self, cobranca) -> None:
        """Diz na cara o que o cadastro **não** vai gerar — rodada 80.

        Paciente salvo sem valor é permitido de propósito (ADR-012): combina-se o preço depois. O que faltava era
        dizer isso. Um psicólogo real cadastrou paciente sem valor, foi ao painel e estranhou não ver cobrança
        nenhuma — e estava certo em estranhar, porque a tela tinha deixado passar em silêncio.
        """
        dados = cobranca.cleaned_data
        if dados.get("valor") is None:
            messages.warning(self.request, "Este paciente ficou sem valor combinado, então não gera cobrança "
                                           "nenhuma. Defina o valor em “Atendimento”, na ficha dele.")
        elif dados.get("modalidade") == CondicaoCobranca.Modalidade.POR_SESSAO:
            messages.info(self.request, "Cobrança por sessão: o valor entra no financeiro quando você registrar "
                                        "que a sessão aconteceu. Quem paga por mês tem a cobrança no dia 1º.")

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

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "generos": GENEROS_SUGERIDOS}

    def form_valid(self, form):
        resposta = super().form_valid(form)
        form.salvar_contatos_de_emergencia(self.object)
        messages.success(self.request, "Cadastro atualizado.")
        return resposta

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
