"""O bloco "Horário de atendimento" da tela "Novo paciente" (ADR-095).

Decisão do usuário: o psicólogo cadastra os horários livres dele na aba Horários e, ao cadastrar o paciente,
**preenche um deles** com o horário desse paciente — ou informa um horário novo, que não estava entre os livres.
Sem isso o paciente nascia sem frequência e não aparecia na agenda.

**Dia da semana e horário ficam sempre à vista** (rodada 61): a primeira versão os escondia até se marcar a
frequência, e o usuário abriu a tela e não os encontrou. Os horários livres são atalhos que preenchem os dois campos.

Nada aqui é regra nova de agenda: o que se grava é a mesma frequência de sempre (`servicos.definir_frequencia`),
com a mesma checagem de colisão. Muda só **onde** se pergunta.
"""

from datetime import timedelta

from django import forms
from django.contrib import messages
from django.utils import timezone

from agenda.grade import vagas_da_semana
from agenda.models import Recorrencia
from atendimentos import servicos

_TEXTO = {"class": "form-control"}
_SELECT = {"class": "form-select"}


class HorarioDoPacienteForm(forms.Form):
    """Dia da semana e horário são **os campos** — sempre à vista. Os horários livres da tela são atalhos que os
    preenchem; quem digita um horário que não estava entre os livres está informando "outro horário", e é só isso.
    """

    frequencia = forms.ChoiceField(
        label="Com que frequência",
        choices=[(Recorrencia.Frequencia.SEMANAL, "Toda semana"),
                 (Recorrencia.Frequencia.QUINZENAL, "A cada duas semanas"),
                 (servicos.AVULSO, "Sem horário fixo — marco cada sessão à parte")],
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
        error_messages={"required": "Escolha a frequência — ou diga que o paciente não tem horário fixo."})
    dia_semana = forms.TypedChoiceField(
        label="Dia da semana", choices=[("", "Escolha")] + list(Recorrencia.DiaSemana.choices),
        coerce=int, empty_value=None, required=False, widget=forms.Select(attrs=_SELECT))
    hora = forms.TimeField(
        label="Horário", required=False, widget=forms.TimeInput(attrs={**_TEXTO, "type": "time"}, format="%H:%M"))

    def clean(self):
        dados = super().clean()
        if dados.get("frequencia") in (None, servicos.AVULSO):
            return dados
        if dados.get("dia_semana") is None:
            self.add_error("dia_semana", "Informe o dia da semana em que o paciente será atendido.")
        if not dados.get("hora") and "hora" not in self.errors:
            self.add_error("hora", "Informe o horário do atendimento.")
        return dados


class BlocoDeHorario:
    """O encaixe pedido por `pacientes.cadastro`."""

    template = "atendimentos/_horario_no_cadastro.html"

    def __init__(self, request, dados=None):
        self.request = request
        self.duracao = request.user.duracao_sessao
        self.dias = vagas_da_semana(self.duracao)
        self.form = HorarioDoPacienteForm(dados, prefix="horario")

    def is_valid(self) -> bool:
        return self.form.is_valid()

    def recusar(self, mensagem: str) -> None:
        self.form.add_error(None, mensagem)

    def salvar(self, paciente, caso) -> None:
        dados = self.form.cleaned_data
        if dados["frequencia"] == servicos.AVULSO:
            messages.info(self.request, f"{paciente.nome} ficou sem horário fixo, então não aparece na agenda "
                                        "por frequência. Marque cada sessão dele em “Nova sessão”.")
            return
        hoje = timezone.localdate()
        # A regra vale da primeira sessão em diante; se ela já passou, de hoje — o passado não ganha previsão.
        regra = servicos.definir_frequencia(
            caso, frequencia=dados["frequencia"], dia_semana=dados["dia_semana"], hora=dados["hora"],
            a_partir_de=max(hoje, paciente.data_primeira_sessao or hoje), hoje=hoje)
        self._dizer_quando_comeca(paciente, regra)

    def _dizer_quando_comeca(self, paciente, regra) -> None:
        """Diz a data da **primeira** sessão prevista — rodada 80.

        A regra vale de hoje em diante, então o dia da semana que já passou nesta semana só volta na próxima. Era
        a origem da queixa "cadastrei e a agenda ficou vazia": a sessão existia, só não naquela janela. Dizer a
        data aqui fecha a dúvida no instante em que ela nasce, em vez de deixar o psicólogo procurar.
        """
        if regra is None:
            return
        primeira = regra.inicio + timedelta(days=(regra.dia_semana - regra.inicio.weekday()) % 7)
        messages.info(self.request, f"Primeira sessão de {paciente.nome} na agenda: "
                                    f"{primeira:%d/%m} ({Recorrencia.DiaSemana(regra.dia_semana).label}), "
                                    f"{regra.hora:%H:%M}.")
