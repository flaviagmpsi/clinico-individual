"""Formulários da agenda. Nenhum tem campo de dono: ele vem do contexto da requisição (ADR-001)."""

from datetime import datetime

from django import forms
from django.utils import timezone

from agenda.models import Recorrencia
from atendimentos.models import DURACAO_MAXIMA, Consulta, Desfecho
from atendimentos.servicos import AVULSO
from core.formularios import LimpaMascara
from pacientes.models import Caso, Paciente

_TEXTO = {"class": "form-control"}
_SELECT = {"class": "form-select"}
_RADIO = {"class": "form-check-input"}


def _campo_situacao() -> forms.ChoiceField:
    return forms.ChoiceField(
        label="O que aconteceu", choices=Consulta.Estado.choices, widget=forms.RadioSelect(attrs=_RADIO),
        help_text="Presente e falta sem aviso cobram; cancelamento pelo profissional e remarcação não. Na "
                  "remarcada, cadastre a sessão nova quando ela acontecer (ADR-065).")


def _campo_cobrar() -> forms.BooleanField:
    return forms.BooleanField(
        label="Cobrar esta sessão", required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Só tem efeito quando o cliente cancelou — nas outras situações a cobrança vem da situação.")


def _campo_valor() -> forms.DecimalField:
    return forms.DecimalField(
        label="Valor desta sessão", required=False, min_value=0, max_digits=10, decimal_places=2,
        widget=forms.TextInput(attrs={"class": "form-control", "inputmode": "numeric",
                                      "data-mascara": "valor", "placeholder": "0,00"}),
        help_text="Vazio: vale o combinado com o paciente. Preencha para cobrar esta sessão à parte — a extra "
                  "de quem paga mensalidade, ou a de quem ainda não tem valor combinado (ADR-070).")


def _campo_modalidade() -> forms.ChoiceField:
    return forms.ChoiceField(
        label="Modalidade", choices=Paciente.Modalidade.choices, required=False,
        widget=forms.Select(attrs=_SELECT),
        help_text="Vem do padrão do paciente; mude se esta sessão foi diferente.")


class _Remarcacao(LimpaMascara, forms.Form):
    CAMPOS_DECIMAIS = ("valor",)

    """Para quando a sessão foi remarcada (ADR-068).

    Os dois campos são opcionais no dado — remarcação sem data combinada existe —, mas andam juntos: dia sem
    horário não coloca nada na agenda. A data nova **não** cria consulta: cria a espera que o psicólogo
    confirma quando a sessão acontecer (ADR-060).
    """

    nova_data = forms.DateField(
        label="Remarcada para o dia", required=False,
        widget=forms.DateInput(attrs={**_TEXTO, "type": "date"}, format="%Y-%m-%d"),
        help_text="Só para remarcada. A sessão nova entra na agenda para você cadastrar quando acontecer.")
    nova_hora = forms.TimeField(
        label="às", required=False,
        widget=forms.TimeInput(attrs={**_TEXTO, "type": "time"}, format="%H:%M"))

    def clean(self):
        dados = super().clean()
        if dados.get("estado") != Consulta.Estado.REMARCADA:
            dados["nova_data"] = dados["nova_hora"] = None
        elif bool(dados.get("nova_data")) != bool(dados.get("nova_hora")):
            self.add_error("nova_hora" if dados.get("nova_data") else "nova_data",
                           "Informe o dia e o horário da sessão remarcada, ou deixe os dois vazios.")
        return dados

    def remarcada_para(self) -> datetime | None:
        dados = self.cleaned_data
        if not (dados.get("nova_data") and dados.get("nova_hora")):
            return None
        return timezone.make_aware(datetime.combine(dados["nova_data"], dados["nova_hora"]))


class _HoraEDuracao(forms.Form):
    hora = forms.TimeField(label="Horário", widget=forms.TimeInput(attrs={**_TEXTO, "type": "time"}, format="%H:%M"))
    duracao = forms.IntegerField(
        label="Duração (minutos)", min_value=10, max_value=DURACAO_MAXIMA,
        widget=forms.NumberInput(attrs={**_TEXTO, "step": 5}))


class CadastroPrevistaForm(_Remarcacao, _HoraEDuracao):
    """Cadastrar uma sessão da frequência. A data é a da sessão prevista e não se escolhe aqui."""

    estado = _campo_situacao()
    cobrar = _campo_cobrar()
    modalidade = _campo_modalidade()
    valor = _campo_valor()

    field_order = ["estado", "cobrar", "modalidade", "hora", "duracao", "valor", "nova_data", "nova_hora"]


class CadastroAvulsaForm(_Remarcacao, _HoraEDuracao):
    # `objetos_todos.none()` na declaração: o atributo de classe é avaliado na importação, fora de
    # requisição, e o `TenantManager` levantaria `EscopoNaoDefinido`. O queryset real vem no `__init__`.
    caso = forms.ModelChoiceField(
        label="Paciente ou atendimento", queryset=Caso.objetos_todos.none(), widget=forms.Select(attrs=_SELECT))
    estado = _campo_situacao()
    cobrar = _campo_cobrar()
    modalidade = _campo_modalidade()
    valor = _campo_valor()
    data = forms.DateField(label="Data", widget=forms.DateInput(attrs={**_TEXTO, "type": "date"}, format="%Y-%m-%d"))

    field_order = ["caso", "estado", "cobrar", "modalidade", "data", "hora", "duracao", "valor",
                   "nova_data", "nova_hora"]

    def __init__(self, *args, duracao_padrao: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["caso"].queryset = Caso.objects.prefetch_related("pacientes")
        self.fields["caso"].label_from_instance = str
        self.fields["duracao"].initial = duracao_padrao
        self.fields["duracao"].help_text = f"Padrão do seu perfil: {duracao_padrao} minutos."

    def inicio(self) -> datetime:
        return timezone.make_aware(datetime.combine(self.cleaned_data["data"], self.cleaned_data["hora"]))


class SituacaoForm(_Remarcacao):
    """Corrigir a situação, a cobrança, a modalidade e o destino da remarcação de uma consulta cadastrada."""

    estado = _campo_situacao()
    cobrar = _campo_cobrar()
    modalidade = _campo_modalidade()
    valor = _campo_valor()

    field_order = ["estado", "cobrar", "modalidade", "valor", "nova_data", "nova_hora"]


class FrequenciaForm(forms.Form):
    frequencia = forms.ChoiceField(
        label="Frequência",
        choices=[(Recorrencia.Frequencia.SEMANAL, "Semanal"),
                 (Recorrencia.Frequencia.QUINZENAL, "Quinzenal — semana sim, semana não"),
                 (AVULSO, "Avulso — sem sessão prevista")],
        widget=forms.RadioSelect(attrs=_RADIO))
    dia_semana = forms.TypedChoiceField(
        label="Dia da semana", choices=[("", "—")] + list(Recorrencia.DiaSemana.choices),
        coerce=int, empty_value=None, required=False, widget=forms.Select(attrs=_SELECT))
    hora = forms.TimeField(
        label="Horário", required=False, widget=forms.TimeInput(attrs={**_TEXTO, "type": "time"}, format="%H:%M"))
    duracao = forms.IntegerField(
        label="Duração (minutos)", required=False, min_value=10, max_value=DURACAO_MAXIMA,
        widget=forms.NumberInput(attrs={**_TEXTO, "step": 5}))
    a_partir_de = forms.DateField(
        label="Vale a partir de", widget=forms.DateInput(attrs={**_TEXTO, "type": "date"}, format="%Y-%m-%d"),
        help_text="Sessões anteriores a esta data não mudam (ADR-022).")

    def __init__(self, *args, duracao_padrao: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["duracao"].help_text = f"Vazio: padrão do seu perfil, {duracao_padrao} minutos."

    def clean(self):
        dados = super().clean()
        if dados.get("frequencia") in (Recorrencia.Frequencia.SEMANAL, Recorrencia.Frequencia.QUINZENAL):
            if dados.get("dia_semana") is None:
                self.add_error("dia_semana", "Informe o dia da semana.")
            if not dados.get("hora"):
                self.add_error("hora", "Informe o horário.")
        return dados


class DesfechoForm(forms.Form):
    tipo = forms.ChoiceField(label="Desfecho", choices=Desfecho.Tipo.choices, widget=forms.RadioSelect(attrs=_RADIO))
    iniciativa = forms.ChoiceField(
        label="De quem partiu", choices=Desfecho.Iniciativa.choices, required=False,
        widget=forms.RadioSelect(attrs=_RADIO),
        help_text="Só para alta e encaminhamento. Desistência parte sempre do paciente; interrupção, sempre de você.")
    data = forms.DateField(label="Data", widget=forms.DateInput(attrs={**_TEXTO, "type": "date"}, format="%Y-%m-%d"))
    motivo = forms.CharField(
        label="Motivo", required=False, widget=forms.Textarea(attrs={**_TEXTO, "rows": 3}),
        help_text="Texto livre. Se o paciente simplesmente parou de responder, vale registrar isso aqui.")

    def clean(self):
        dados = super().clean()
        tipo = dados.get("tipo")
        if tipo in Desfecho.INICIATIVA_DO_TIPO:
            dados["iniciativa"] = Desfecho.INICIATIVA_DO_TIPO[tipo]
        elif tipo and not dados.get("iniciativa"):
            self.add_error("iniciativa", "Informe de quem partiu o encerramento.")
        return dados
