"""O bloco "Horário de atendimento" da tela "Novo paciente" (ADR-095).

Decisão do usuário: o psicólogo cadastra os horários livres dele na aba Horários e, ao cadastrar o paciente,
**preenche um deles** com o horário desse paciente — ou informa um horário novo, que não estava entre os livres.
Sem isso o paciente nascia sem frequência e não aparecia na agenda.

Nada aqui é regra nova de agenda: o que se grava é a mesma frequência de sempre (`servicos.definir_frequencia`),
com a mesma checagem de colisão. Muda só **onde** se pergunta.
"""

from django import forms
from django.utils import timezone

from agenda.grade import vagas_da_semana
from agenda.models import Recorrencia
from atendimentos import servicos

OUTRO = "OUTRO"
_TEXTO = {"class": "form-control"}
_SELECT = {"class": "form-select"}


class HorarioDoPacienteForm(forms.Form):
    frequencia = forms.ChoiceField(
        label="Com que frequência",
        choices=[(Recorrencia.Frequencia.SEMANAL, "Toda semana"),
                 (Recorrencia.Frequencia.QUINZENAL, "A cada duas semanas"),
                 (servicos.AVULSO, "Sem horário fixo — marco cada sessão à parte")],
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
        error_messages={"required": "Escolha a frequência — ou diga que o paciente não tem horário fixo."})
    vaga = forms.ChoiceField(label="Horário", required=False, widget=forms.RadioSelect)
    dia_semana = forms.TypedChoiceField(
        label="Dia da semana", choices=[("", "—")] + list(Recorrencia.DiaSemana.choices),
        coerce=int, empty_value=None, required=False, widget=forms.Select(attrs=_SELECT))
    hora = forms.TimeField(
        label="Horário", required=False, widget=forms.TimeInput(attrs={**_TEXTO, "type": "time"}, format="%H:%M"))

    def __init__(self, *args, dias, **kwargs):
        super().__init__(*args, **kwargs)
        self.dias = dias
        self.vagas = {vaga.codigo: vaga for dia in dias for vaga in dia.vagas}
        self.fields["vaga"].choices = [(codigo, codigo) for codigo in self.vagas] + [(OUTRO, "Outro horário")]

    def clean(self):
        dados = super().clean()
        if dados.get("frequencia") in (None, servicos.AVULSO):
            return dados
        vaga = dados.get("vaga")
        if not vaga:
            self.add_error("vaga", "Escolha um dos seus horários livres, ou informe outro horário.")
        elif vaga == OUTRO:
            if dados.get("dia_semana") is None:
                self.add_error("dia_semana", "Informe o dia da semana.")
            if not dados.get("hora"):
                self.add_error("hora", "Informe o horário.")
        else:
            dados["dia_semana"], dados["hora"] = self.vagas[vaga].dia_semana, self.vagas[vaga].hora
        return dados


class BlocoDeHorario:
    """O encaixe pedido por `pacientes.cadastro`."""

    template = "atendimentos/_horario_no_cadastro.html"

    def __init__(self, request, dados=None):
        self.duracao = request.user.duracao_sessao
        self.dias = vagas_da_semana(self.duracao)
        self.form = HorarioDoPacienteForm(dados, prefix="horario", dias=self.dias)
        self.outro = OUTRO

    @property
    def vaga_escolhida(self) -> str:
        return self.form["vaga"].value() or ""

    def is_valid(self) -> bool:
        return self.form.is_valid()

    def recusar(self, mensagem: str) -> None:
        self.form.add_error(None, mensagem)

    def salvar(self, paciente, caso) -> None:
        dados = self.form.cleaned_data
        if dados["frequencia"] == servicos.AVULSO:
            return
        hoje = timezone.localdate()
        # A regra vale da primeira sessão em diante; se ela já passou, de hoje — o passado não ganha previsão.
        servicos.definir_frequencia(
            caso, frequencia=dados["frequencia"], dia_semana=dados["dia_semana"], hora=dados["hora"],
            a_partir_de=max(hoje, paciente.data_primeira_sessao or hoje), hoje=hoje)
