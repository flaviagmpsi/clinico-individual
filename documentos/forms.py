"""O formulário de um documento é montado a partir do modelo do catálogo (ADR-076) — e é preenchido **dentro da
folha** (ADR-077): cada campo é um espaço do próprio documento, no lugar onde o valor vai cair.

Nenhum campo é obrigatório **no formulário**: rascunho se salva pela metade. Quem exige é a emissão
(`servicos.emitir`). O que o catálogo sabe de cada campo — rótulo, ajuda, se é exigido — viaja nos atributos do
widget, para a tela mostrar a explicação do campo em foco.
"""

from django import forms

from documentos import modelos

_FORA_DO_CORPO = ("Identificação", "Encerramento")


def _widget(campo: modelos.Campo) -> forms.Widget:
    atributos = {
        "class": "na-folha", "placeholder": campo.rotulo + (" *" if campo.obrigatorio else ""),
        "data-rotulo": campo.rotulo, "data-ajuda": campo.ajuda, "autocomplete": "off",
    }
    if campo.obrigatorio:
        atributos["data-obrigatorio"] = "1"
    if campo.tipo == modelos.TEXTO:
        return forms.Textarea(attrs={**atributos, "rows": max(2, campo.linhas - 2)})
    if campo.tipo == modelos.DATA:
        return forms.DateInput(attrs={**atributos, "type": "date"}, format="%Y-%m-%d")
    return forms.TextInput(attrs=atributos)


class DocumentoForm(forms.Form):
    def __init__(self, *args, modelo: modelos.ModeloDeDocumento, **kwargs):
        super().__init__(*args, **kwargs)
        self.modelo = modelo
        for campo in modelo.campos:
            self.fields[campo.nome] = forms.CharField(
                label=campo.rotulo, help_text=campo.ajuda, required=False, widget=_widget(campo))
            self.fields[campo.nome].obrigatorio = campo.obrigatorio

    # --- O que a folha percorre. Método, e não atributo: `form.data` é o dicionário do Django, e o campo "data"
    # --- de um documento só se alcança por `form["data"]`.

    def corpo(self) -> list:
        """Documento em texto corrido: o gabarito em pedaços — texto, e o campo no lugar onde cai."""
        return [(tipo, self[valor] if tipo == "campo" else valor)
                for tipo, valor in modelos.segmentos(self.modelo.gabarito)]

    def subtitulo(self):
        return self["subtitulo"] if "subtitulo" in self.fields else None

    def identificacao(self) -> list:
        """Documento em itens: as linhas da identificação, cada uma com o seu rótulo."""
        secao = next((s for s in self.modelo.secoes if s.titulo == "Identificação"), None)
        return [self[campo.nome] for campo in secao.campos if campo.nome != "subtitulo"] if secao else []

    def itens(self) -> list:
        """Documento em itens: cada item da resolução — demanda, procedimento, análise… — com os seus campos."""
        return [(secao.titulo, [self[campo.nome] for campo in secao.campos])
                for secao in self.modelo.secoes if secao.titulo not in _FORA_DO_CORPO]

    def encerramento(self) -> dict:
        return {"local": self["local"], "data": self["data"],
                "nome": self["psicologo_nome"], "crp": self["psicologo_crp"]}
