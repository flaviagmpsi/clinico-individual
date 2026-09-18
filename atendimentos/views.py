"""Telas da agenda e do fim do atendimento.

Moram em `atendimentos`, e não em `agenda`, porque mostram consultas — e `agenda` não conhece
consulta (regra 5 de dependência). Dono do dado e lugar na tela são coisas diferentes.

Desde a ADR-060 a agenda mostra duas coisas, e não as confunde: **consulta cadastrada** (registro, no banco) e
**sessão prevista** pela frequência (cálculo). A sessão prevista vira consulta quando o psicólogo a cadastra.

Toda busca de objeto pela URL acontece depois do `LoginRequiredMixin`, nunca no `dispatch`: buscar antes
faria o visitante anônimo receber um erro de escopo em vez de ser mandado ao login.
"""

from datetime import date, time, timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import FormView, TemplateView

from agenda.grade import fora_da_grade
from agenda.models import Recorrencia
from atendimentos import servicos
from atendimentos.forms import (
    CadastroAvulsaForm,
    CadastroPrevistaForm,
    DesfechoForm,
    FrequenciaForm,
    SituacaoForm,
)
from atendimentos.models import Consulta, Desfecho
from pacientes.models import Caso, Paciente


def _segunda(dia: date) -> date:
    return dia - timedelta(days=dia.weekday())


def _data(valor: str | None) -> date | None:
    try:
        return date.fromisoformat(valor or "")
    except ValueError:
        return None


def _semana_de(dia: date) -> str:
    return f"{reverse('atendimentos:agenda')}?semana={_segunda(dia):%Y-%m-%d}"


def _ficha_do_caso(caso: Caso):
    """O atendimento individual não tem tela própria (ADR-026): volta para a ficha do paciente."""
    if caso.individual:
        return redirect("pacientes:detalhe", pk=caso.pacientes.first().pk)
    return redirect("pacientes:caso", pk=caso.pk)


def _avisar_se_fora_da_grade(request, dia_semana: int, hora: time, duracao: int) -> None:
    """ADR-056: a grade avisa, nunca bloqueia — o que foi pedido já está gravado quando o aviso aparece."""
    if fora_da_grade(dia_semana, hora, duracao):
        messages.warning(request, "Este horário fica fora da sua grade de horários. Gravado mesmo assim.")


PREVISTA = "PREVISTA"


class Agenda(LoginRequiredMixin, TemplateView):
    """A agenda de um período, com filtro de situação e o percentual de online e presencial (ADR-065)."""

    template_name = "atendimentos/agenda.html"

    def periodo(self) -> tuple[date, date]:
        """De uma data a outra. Sem período informado, a semana pedida — ou a de hoje."""
        de, ate = _data(self.request.GET.get("de")), _data(self.request.GET.get("ate"))
        if de and ate and ate >= de:
            return de, ate
        segunda = _segunda(_data(self.request.GET.get("semana")) or timezone.localdate())
        return segunda, segunda + timedelta(days=6)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        hoje = timezone.localdate()
        de, ate = self.periodo()
        tamanho = (ate - de).days + 1
        situacao = self.request.GET.get("situacao", "")

        consultas = []
        if situacao != PREVISTA:
            achadas = (
                Consulta.objects.filter(inicio__gte=servicos.momento(de, time.min),
                                        inicio__lt=servicos.momento(ate + timedelta(days=1), time.min))
                .select_related("caso", "recorrencia").prefetch_related("caso__pacientes")
            )
            consultas = list(achadas.filter(estado=situacao) if situacao else achadas)
        esperando_cadastro = situacao in ("", PREVISTA)
        previstas = servicos.sessoes_previstas(de, ate) if esperando_cadastro else []
        remarcadas = servicos.sessoes_remarcadas(de, ate) if esperando_cadastro else []

        itens = sorted([("consulta", c) for c in consultas] + [("prevista", s) for s in previstas]
                       + [("remarcada", s) for s in remarcadas],
                       key=lambda item: item[1].inicio)
        dias = []
        for n in range(tamanho):
            dia = de + timedelta(days=n)
            dias.append((dia, [item for item in itens if timezone.localtime(item[1].inicio).date() == dia]))

        online = sum(1 for _, item in itens if item.modalidade == Paciente.Modalidade.ONLINE)
        pendentes = servicos.sessoes_pendentes()
        contexto.update(
            dias=dias, de=de, ate=ate, hoje=hoje, situacao=situacao, tamanho=tamanho,
            situacoes=[(PREVISTA, "Previstas")] + list(Consulta.Estado.choices),
            anterior_de=de - timedelta(days=tamanho), anterior_ate=ate - timedelta(days=tamanho),
            proxima_de=de + timedelta(days=tamanho), proxima_ate=ate + timedelta(days=tamanho),
            esta_semana=_segunda(hoje),
            total_sessoes=len(itens), online=online, presenciais=len(itens) - online,
            percentual_online=round(100 * online / len(itens)) if itens else None,
            pendentes=pendentes[:10], total_pendentes=len(pendentes),
        )
        return contexto


class CadastrarAvulsa(LoginRequiredMixin, FormView):
    """Consulta fora da frequência: paciente avulso, sessão extra ou a remarcada que aconteceu (ADR-060)."""

    form_class = CadastroAvulsaForm
    template_name = "atendimentos/cadastrar.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["duracao_padrao"] = self.request.user.duracao_sessao
        return kwargs

    def get_initial(self):
        inicial = {"estado": Consulta.Estado.REALIZADA, "data": timezone.localdate(),
                   "modalidade": Paciente.Modalidade.PRESENCIAL}
        codigo = self.request.GET.get("caso", "")
        if codigo.isdigit():
            inicial["caso"] = int(codigo)  # id alheio não faz nada: não está entre as opções
            caso = Caso.objects.filter(pk=int(codigo)).first()
            if caso is not None:
                inicial["modalidade"] = servicos.modalidade_do_caso(caso)
        return inicial

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["titulo"] = "Cadastrar consulta avulsa"
        return contexto

    def form_valid(self, form):
        dados = form.cleaned_data
        try:
            consulta = servicos.cadastrar_avulsa(
                dados["caso"], estado=dados["estado"], inicio=form.inicio(), duracao=dados["duracao"],
                modalidade=dados["modalidade"] or None, cobrada=dados["cobrar"], valor=dados["valor"],
                remarcada_para=form.remarcada_para())
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, f"Consulta cadastrada: {consulta.get_estado_display().lower()}.")
        local = timezone.localtime(consulta.inicio)
        _avisar_se_fora_da_grade(self.request, local.weekday(), local.time(), consulta.duracao)
        return redirect(_semana_de(local.date()))


class CadastrarRemarcada(LoginRequiredMixin, FormView):
    """A sessão nova de uma remarcação (ADR-068).

    É uma consulta avulsa como qualquer outra — não pertence à frequência. O que esta tela faz é chegar com
    tudo preenchido a partir da sessão remarcada: atendimento, data, horário, duração e modalidade.
    """

    form_class = CadastroAvulsaForm
    template_name = "atendimentos/cadastrar.html"

    def origem(self) -> Consulta:
        if not hasattr(self, "_origem"):
            consulta = get_object_or_404(
                Consulta.objects.select_related("caso"), pk=self.kwargs["pk"], estado=Consulta.Estado.REMARCADA)
            if consulta.remarcada_para is None:
                raise Http404("Esta sessão remarcada não tem data nova.")
            self._origem = consulta
        return self._origem

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["duracao_padrao"] = self.request.user.duracao_sessao
        return kwargs

    def get_initial(self):
        origem = self.origem()
        local = timezone.localtime(origem.remarcada_para)
        return {"caso": origem.caso_id, "estado": Consulta.Estado.REALIZADA, "data": local.date(),
                "hora": local.time(), "duracao": origem.duracao, "modalidade": origem.modalidade}

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(titulo="Cadastrar sessão remarcada", origem=self.origem())
        return contexto

    def form_valid(self, form):
        dados = form.cleaned_data
        try:
            consulta = servicos.cadastrar_avulsa(
                dados["caso"], estado=dados["estado"], inicio=form.inicio(), duracao=dados["duracao"],
                modalidade=dados["modalidade"] or None, cobrada=dados["cobrar"], valor=dados["valor"],
                remarcada_para=form.remarcada_para())
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, f"Sessão remarcada cadastrada: {consulta.get_estado_display().lower()}.")
        return redirect(_semana_de(timezone.localtime(consulta.inicio).date()))


class CadastrarPrevista(LoginRequiredMixin, FormView):
    """Cadastrar uma sessão prevista pela frequência — é o que a tira da pendência."""

    form_class = CadastroPrevistaForm
    template_name = "atendimentos/cadastrar.html"

    def prevista(self) -> servicos.SessaoPrevista:
        if not hasattr(self, "_prevista"):
            regra = get_object_or_404(Recorrencia.objects.select_related("caso"), pk=self.kwargs["regra_pk"])
            try:
                data = date.fromisoformat(self.kwargs["data"])
            except ValueError:
                raise Http404("Data inválida.")
            if not regra.ocorre_em(data):
                raise Http404("Esta data não é uma sessão prevista pela frequência.")
            self._prevista = servicos.SessaoPrevista(regra, data)
        return self._prevista

    def get(self, request, *args, **kwargs):
        prevista = self.prevista()
        ja_cadastrada = prevista.regra.consultas.filter(data_prevista=prevista.data).first()
        if ja_cadastrada is not None:
            messages.info(request, "Esta sessão já foi cadastrada. Aqui você pode corrigir a situação.")
            return redirect("atendimentos:editar", pk=ja_cadastrada.pk)
        return super().get(request, *args, **kwargs)

    def get_initial(self):
        regra = self.prevista().regra
        return {"estado": Consulta.Estado.REALIZADA, "hora": regra.hora, "duracao": regra.duracao,
                "modalidade": servicos.modalidade_do_caso(regra.caso)}

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(titulo="Cadastrar sessão", prevista=self.prevista())
        return contexto

    def form_valid(self, form):
        prevista = self.prevista()
        dados = form.cleaned_data
        try:
            consulta = servicos.cadastrar_prevista(
                prevista.regra, prevista.data, estado=dados["estado"], hora=dados["hora"], duracao=dados["duracao"],
                modalidade=dados["modalidade"] or None, cobrada=dados["cobrar"], valor=dados["valor"],
                remarcada_para=form.remarcada_para())
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, f"Sessão cadastrada: {consulta.get_estado_display().lower()}.")
        return redirect(_semana_de(prevista.data))


class _ComConsulta:
    def consulta(self) -> Consulta:
        if not hasattr(self, "_consulta"):
            self._consulta = get_object_or_404(
                Consulta.objects.select_related("caso", "recorrencia"), pk=self.kwargs["pk"])
        return self._consulta


class EditarConsulta(LoginRequiredMixin, _ComConsulta, FormView):
    """Corrigir a situação de uma consulta cadastrada."""

    form_class = SituacaoForm
    template_name = "atendimentos/editar.html"

    def get_initial(self):
        consulta = self.consulta()
        inicial = {"estado": consulta.estado, "cobrar": consulta.cobrada, "modalidade": consulta.modalidade,
                   "valor": consulta.valor}
        if consulta.remarcada_para:
            local = timezone.localtime(consulta.remarcada_para)
            inicial.update(nova_data=local.date(), nova_hora=local.time())
        return inicial

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["consulta"] = self.consulta()
        return contexto

    def form_valid(self, form):
        consulta = self.consulta()
        dados = form.cleaned_data
        try:
            servicos.alterar_situacao(consulta, dados["estado"], cobrada=dados["cobrar"],
                                      modalidade=dados["modalidade"] or None, valor=dados["valor"],
                                      remarcada_para=form.remarcada_para())
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, f"Situação corrigida: {consulta.get_estado_display().lower()}.")
        return redirect(_semana_de(timezone.localtime(consulta.inicio).date()))


class ExcluirConsulta(LoginRequiredMixin, _ComConsulta, View):
    """Cadastro feito por engano. Só por POST."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        consulta = self.consulta()
        dia = timezone.localtime(consulta.inicio).date()
        da_frequencia = not consulta.avulsa
        try:
            servicos.excluir_consulta(consulta)
        except ValidationError as erro:
            messages.error(request, erro.messages[0])
            return redirect("atendimentos:editar", pk=consulta.pk)
        aviso = " A sessão volta a aparecer como pendente." if da_frequencia else ""
        messages.success(request, f"Cadastro excluído.{aviso}")
        return redirect(_semana_de(dia))


class _ComCaso:
    def caso(self) -> Caso:
        if not hasattr(self, "_caso"):
            self._caso = get_object_or_404(Caso.objects.prefetch_related("pacientes"), pk=self.kwargs["caso_pk"])
        return self._caso

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        caso = self.caso()
        contexto.update(caso=caso, regra=caso.regra_aberta(), individual=caso.individual,
                        paciente=caso.pacientes.first())
        return contexto


class FrequenciaDoCaso(LoginRequiredMixin, _ComCaso, FormView):
    """Semanal, quinzenal ou avulso (ADR-053) — do paciente individual ou do atendimento de casal."""

    form_class = FrequenciaForm
    template_name = "atendimentos/frequencia.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["duracao_padrao"] = self.request.user.duracao_sessao
        return kwargs

    def get_initial(self):
        regra = self.caso().regra_aberta()
        inicial = {"a_partir_de": timezone.localdate()}
        if regra is None:
            inicial["frequencia"] = servicos.AVULSO
        else:
            inicial.update(frequencia=regra.frequencia, dia_semana=regra.dia_semana, hora=regra.hora,
                           duracao=regra.duracao)
        return inicial

    def form_valid(self, form):
        dados = form.cleaned_data
        caso = self.caso()
        try:
            regra = servicos.definir_frequencia(
                caso, frequencia=dados["frequencia"], dia_semana=dados.get("dia_semana"), hora=dados.get("hora"),
                duracao=dados.get("duracao"), a_partir_de=dados["a_partir_de"])
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, "Frequência atualizada.")
        if regra is not None:
            _avisar_se_fora_da_grade(self.request, regra.dia_semana, regra.hora, regra.duracao)
        return _ficha_do_caso(caso)


class RegistrarDesfecho(LoginRequiredMixin, _ComCaso, FormView):
    """Alta, desistência, encaminhamento ou interrupção (ADR-049). A tela diz o que muda **antes** de gravar."""

    form_class = DesfechoForm
    template_name = "atendimentos/desfecho.html"

    def get(self, request, *args, **kwargs):
        if self.caso().desfecho_aberto() is not None:
            messages.info(request, "Este atendimento já está encerrado.")
            return _ficha_do_caso(self.caso())
        return super().get(request, *args, **kwargs)

    def get_initial(self):
        return {"data": timezone.localdate()}

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        caso = self.caso()
        contexto.update(
            pendentes=len(servicos.sessoes_pendentes(caso=caso)),
            sessoes=Desfecho(caso=caso, data=timezone.localdate()).sessoes_realizadas,
        )
        return contexto

    def form_valid(self, form):
        dados = form.cleaned_data
        caso = self.caso()
        try:
            desfecho = servicos.registrar_desfecho(
                caso, tipo=dados["tipo"], iniciativa=dados["iniciativa"], motivo=dados["motivo"], data=dados["data"])
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, f"Atendimento encerrado: {desfecho.get_tipo_display().lower()}.")
        return _ficha_do_caso(caso)


class RetomarAtendimento(LoginRequiredMixin, _ComCaso, View):
    """O paciente voltou (ADR-055). Só por POST: reabrir atendimento não é coisa que um link faça."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        caso = self.caso()
        try:
            servicos.retomar(caso)
        except ValidationError as erro:
            messages.error(request, erro.messages[0])
            return _ficha_do_caso(caso)
        messages.success(request, "Atendimento retomado. Defina a frequência — até lá, ele fica como avulso.")
        return redirect("atendimentos:frequencia", caso_pk=caso.pk)
