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
from pacientes.models import Caso, CondicaoCobranca, Paciente


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


def _mes_seguinte(dia: date) -> date:
    return date(dia.year + (dia.month == 12), dia.month % 12 + 1, 1)


def _mes_anterior(dia: date) -> date:
    return date(dia.year - (dia.month == 1), (dia.month - 2) % 12 + 1, 1)


class Agenda(LoginRequiredMixin, TemplateView):
    """A agenda no desenho da planilha do psicólogo (ADR-073).

    Colunas por dia, cartões em ordem de horário, e os horários livres visíveis onde há grade cadastrada. A
    semana é o padrão; dia e mês ficam a um clique. `de`/`ate` e `semana` continuam valendo como período
    (ADR-065), e o filtro de situação vale para a visão aberta.
    """

    template_name = "atendimentos/agenda.html"

    def periodo(self) -> tuple[str, date, date, date]:
        """(visão, data-âncora, de, até)."""
        pedido = self.request.GET
        hoje = timezone.localdate()
        de, ate = _data(pedido.get("de")), _data(pedido.get("ate"))
        if de and ate and ate >= de:
            return "periodo", de, de, ate
        semana = _data(pedido.get("semana"))
        if semana:
            segunda = _segunda(semana)
            return "semana", segunda, segunda, segunda + timedelta(days=6)
        visao = pedido.get("visao", "semana")
        data = _data(pedido.get("data")) or hoje
        if visao == "dia":
            return "dia", data, data, data
        if visao == "mes":
            primeiro = data.replace(day=1)
            return "mes", primeiro, primeiro, _mes_seguinte(primeiro) - timedelta(days=1)
        segunda = _segunda(data)
        return "semana", segunda, segunda, segunda + timedelta(days=6)

    @staticmethod
    def _rota(visao: str, data: date, situacao: str) -> str:
        return f"{reverse('atendimentos:agenda')}?visao={visao}&data={data:%Y-%m-%d}&situacao={situacao}"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        hoje = timezone.localdate()
        visao, ancora, de, ate = self.periodo()
        situacao = self.request.GET.get("situacao", "")
        dias = servicos.calendario(de, ate, situacao=situacao, duracao=self.request.user.duracao_sessao)

        # ADR-073: segunda a sexta; sábado e domingo só quando tiverem alguma coisa.
        fim_de_semana = any(not dia.vazio for dia in dias if dia.dia.weekday() >= 5)
        colunas = [dia for dia in dias if dia.dia.weekday() < 5 or not dia.vazio]

        semanas = []
        if visao == "mes":
            por_data = {dia.dia: dia for dia in dias}
            cursor = _segunda(de)
            while cursor <= ate:
                linha = [por_data.get(cursor + timedelta(days=n)) for n in range(7)]
                semanas.append(linha if fim_de_semana else linha[:5])
                cursor += timedelta(days=7)

        if visao == "mes":
            anterior, proxima = _mes_anterior(ancora), _mes_seguinte(ancora)
        else:
            passo = timedelta(days=(ate - de).days + 1)
            anterior, proxima = ancora - passo, ancora + passo
        visao_nav = "semana" if visao == "periodo" else visao

        sessoes = [item for dia in dias for item in dia.sessoes]
        online = sum(1 for item in sessoes if item.modalidade == Paciente.Modalidade.ONLINE)
        contexto.update(
            visao=visao, de=de, ate=ate, hoje=hoje, situacao=situacao,
            situacoes=[(servicos.PREVISTA, "Previstas")] + list(Consulta.Estado.choices),
            colunas=colunas, semanas=semanas, fim_de_semana=fim_de_semana,
            rota_anterior=self._rota(visao_nav, anterior, situacao),
            rota_proxima=self._rota(visao_nav, proxima, situacao),
            rota_hoje=self._rota(visao_nav, hoje, situacao),
            rota_dia=self._rota("dia", ancora if visao != "mes" else hoje, situacao),
            rota_semana=self._rota("semana", ancora, situacao),
            rota_mes=self._rota("mes", ancora, situacao),
            total_sessoes=len(sessoes), online=online, presenciais=len(sessoes) - online,
            percentual_online=round(100 * online / len(sessoes)) if sessoes else None,
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
                modalidade=dados["modalidade"] or None, cobrada=dados["cobrar"], valor=dados.get("valor"),
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

    def get_form(self, form_class=None):
        return _sem_valor(super().get_form(form_class))  # ADR-093: a remarcada já estava combinada

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        origem = self.origem()
        contexto.update(titulo="Cadastrar sessão remarcada", origem=origem,
                        cobranca_combinada=_cobranca_combinada(origem.caso, timezone.localtime(origem.remarcada_para).date()))
        return contexto

    def form_valid(self, form):
        dados = form.cleaned_data
        try:
            consulta = servicos.cadastrar_avulsa(
                dados["caso"], estado=dados["estado"], inicio=form.inicio(), duracao=dados["duracao"],
                modalidade=dados["modalidade"] or None, cobrada=dados["cobrar"], valor=dados.get("valor"),
                remarcada_para=form.remarcada_para())
        except ValidationError as erro:
            form.add_error(None, erro.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, f"Sessão remarcada cadastrada: {consulta.get_estado_display().lower()}.")
        return redirect(_semana_de(timezone.localtime(consulta.inicio).date()))


def _sem_valor(form):
    """Tira o campo de valor do formulário (ADR-074). `cleaned_data.get("valor")` continua funcionando."""
    form.fields.pop("valor", None)
    return form


def _cobranca_combinada(caso: Caso, dia: date) -> str:
    """O que a tela diz no lugar do campo de valor, na sessão que já estava combinada (ADR-093).

    Sessão da frequência — ou a remarcação de uma — tem valor conhecido: o da condição de cobrança. A tela não
    pergunta; **diz o que vai acontecer no financeiro**, que é o que o psicólogo quer saber ao cadastrar.
    """
    condicao = caso.condicao_vigente(dia)
    if condicao is None:
        return ("Ainda não há valor combinado com este paciente, então esta sessão não gera cobrança. "
                "Combine o valor na ficha dele para o financeiro acompanhar.")
    valor = f"R$ {condicao.valor:.2f}".replace(".", ",")
    if condicao.modalidade == CondicaoCobranca.Modalidade.MENSAL:
        return f"Mensalidade de {valor}: esta sessão já está na mensalidade do mês e não gera cobrança nova."
    return f"Valor combinado: {valor} por sessão. Sendo cobrada, ela entra no financeiro como pagamento pendente."


def _nasceu_de_remarcacao(consulta: Consulta) -> bool:
    """A sessão avulsa que é a data nova de uma remarcada (ADR-068): já estava combinada, só mudou de dia."""
    return Consulta.objects.filter(caso=consulta.caso_id, estado=Consulta.Estado.REMARCADA,
                                   remarcada_para=consulta.inicio).exists()


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

    def get_form(self, form_class=None):
        # ADR-093: sessão da frequência tem valor conhecido, por mensalidade ou por sessão. O campo é só da avulsa.
        return _sem_valor(super().get_form(form_class))

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        prevista = self.prevista()
        contexto.update(titulo="Cadastrar sessão", prevista=prevista,
                        cobranca_combinada=_cobranca_combinada(prevista.caso, prevista.data))
        return contexto

    def form_valid(self, form):
        prevista = self.prevista()
        dados = form.cleaned_data
        try:
            consulta = servicos.cadastrar_prevista(
                prevista.regra, prevista.data, estado=dados["estado"], hora=dados["hora"], duracao=dados["duracao"],
                modalidade=dados["modalidade"] or None, cobrada=dados["cobrar"], valor=dados.get("valor"),
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

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        return _sem_valor(form) if self.combinada() else form

    def combinada(self) -> bool:
        """Sessão da frequência, ou a data nova de uma remarcação: o valor já era conhecido (ADR-093)."""
        if not hasattr(self, "_combinada"):
            consulta = self.consulta()
            self._combinada = not consulta.avulsa or _nasceu_de_remarcacao(consulta)
        return self._combinada

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        consulta = self.consulta()
        contexto["consulta"] = consulta
        if self.combinada():
            contexto["cobranca_combinada"] = _cobranca_combinada(consulta.caso, timezone.localtime(consulta.inicio).date())
        return contexto

    def form_valid(self, form):
        consulta = self.consulta()
        dados = form.cleaned_data
        try:
            servicos.alterar_situacao(consulta, dados["estado"], cobrada=dados["cobrar"],
                                      modalidade=dados["modalidade"] or None, valor=dados.get("valor"),
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
