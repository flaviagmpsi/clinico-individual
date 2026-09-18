"""Formulários do prontuário.

- `ProntuarioForm`: a tela de uma sessão — um campo de texto livre (ADR-064). Editar não pede motivo (ADR-075).
- `FolhaDoProntuarioForm`: a demanda e o encerramento do prontuário geral, preenchidos dentro da folha
  (ADR-077, ADR-079). Quem mostra a folha é o app `documentos` (ADR-080).
"""

from django import forms

from prontuarios import orientacoes
from prontuarios.models import Anamnese


class ProntuarioForm(forms.Form):
    texto = forms.CharField(label="Registro da sessão",
                            widget=forms.Textarea(attrs={"class": "form-control", "rows": 14}))


def _na_folha(rotulo: str, ajuda: str, dica: str) -> forms.Textarea:
    return forms.Textarea(attrs={"class": "na-folha", "rows": 2, "placeholder": dica,
                                 "data-rotulo": rotulo, "data-ajuda": ajuda})


class FolhaDoProntuarioForm(forms.Form):
    """As duas partes do prontuário geral que se escrevem nele. A evolução vem dos registros de sessão (ADR-080)."""

    demanda = forms.CharField(
        label="Avaliação da demanda e objetivos do trabalho", required=False, help_text=orientacoes.AJUDA_DEMANDA,
        widget=_na_folha("Avaliação da demanda e objetivos do trabalho", orientacoes.AJUDA_DEMANDA,
                         "O que trouxe a pessoa, como você avaliou a demanda e quais são os objetivos do trabalho"))
    encerramento = forms.CharField(
        label="Encaminhamento ou encerramento", required=False, help_text=orientacoes.AJUDA_ENCERRAMENTO,
        widget=_na_folha("Encaminhamento ou encerramento", orientacoes.AJUDA_ENCERRAMENTO,
                         "Em branco enquanto o atendimento segue"))


# O que se espera em cada tema — dito em uma linha, embaixo do campo. São sugestões de roteiro, não exigências.
AJUDA_DA_ANAMNESE = {
    "queixa_principal": "O que trouxe a pessoa, nas palavras dela.",
    "historia_da_queixa": "Quando começou, como evoluiu, o que piora e o que alivia, o que já tentou.",
    "tratamentos_anteriores": "Psicoterapia, acompanhamento psiquiátrico, internações — quando, com quem, como foi.",
    "saude_geral": "Doenças, cirurgias, condições crônicas e medicamentos em uso, conforme o relato.",
    "sono_alimentacao_substancias": "Padrão de sono e de alimentação; álcool, tabaco e outras substâncias.",
    "historia_familiar": "Com quem mora, composição da família, clima das relações, histórico de saúde mental.",
    "desenvolvimento": "Para criança e adolescente: gestação, parto, marcos do desenvolvimento, escola. "
                       "Para adulto: o que for relevante da infância e da adolescência.",
    "escolaridade_e_trabalho": "Formação, ocupação atual, satisfação e dificuldades no trabalho ou nos estudos.",
    "relacionamentos": "Vida afetiva, amizades, com quem conta quando precisa.",
    "rotina_e_lazer": "Como é um dia comum; o que faz por prazer; atividade física.",
    "expectativas": "O que espera da terapia, e o que seria melhorar.",
    "observacoes": "Impressões suas da entrevista. Lembre que isto é registro seu — não vai para o prontuário geral.",
}


class AnamneseForm(forms.ModelForm):
    """Todos os campos opcionais e em texto livre (ADR-085)."""

    class Meta:
        model = Anamnese
        fields = list(Anamnese.CAMPOS_DE_TEXTO)
        widgets = {campo: forms.Textarea(attrs={"class": "form-control", "rows": 3})
                   for campo in Anamnese.CAMPOS_DE_TEXTO}
        help_texts = AJUDA_DA_ANAMNESE

    def tem_conteudo(self) -> bool:
        return any((self.cleaned_data.get(campo) or "").strip() for campo in Anamnese.CAMPOS_DE_TEXTO)

