"""O formulário que o **paciente** preenche pelo link de cadastro (ADR-081).

`Form`, e não `ModelForm`: nada aqui grava paciente. O resultado é um dicionário que fica guardado no convite até o
psicólogo revisar. As validações de formato são as mesmas do cadastro feito pelo psicólogo — o que entra pela porta
pública não pode ser mais frouxo do que o que entra pela de dentro.

Princípio da LGPD que guia a tela: **pedir o mínimo**. Obrigatório é só o que o psicólogo precisa para atender com
segurança — nome, nascimento, um telefone, um contato de emergência. Raça/cor, gênero e medicamento são dado
sensível, e por isso sempre opcionais.
"""

from django import forms
from django.utils import timezone

from core.formularios import LimpaMascara
from pacientes import convites
from pacientes.models import Paciente, cep_valido, cpf_valido, telefone_valido

_TEXTO = {"class": "form-control"}
_NUM = {"class": "form-control", "inputmode": "numeric"}
_CPF = {**_NUM, "data-mascara": "cpf", "placeholder": "000.000.000-00"}
_TELEFONE = {**_NUM, "data-mascara": "telefone", "placeholder": "(31) 98888-7777"}
_CEP = {**_NUM, "data-mascara": "cep", "data-busca-cep": "1", "placeholder": "00000-000"}
_SELECT = {"class": "form-select"}
_CHECK = {"class": "form-check-input"}

GENEROS_SUGERIDOS = ["Mulher cisgênero", "Homem cisgênero", "Mulher transgênero", "Homem transgênero",
                     "Pessoa não binária", "Prefiro não informar"]

_VAZIO = [("", "Selecione…")]


def _texto(rotulo, *, obrigatorio=False, tamanho=255, dica="", **atributos):
    return forms.CharField(label=rotulo, required=obrigatorio, max_length=tamanho,
                           widget=forms.TextInput(attrs={**_TEXTO, "placeholder": dica, **atributos}))


def _cpf(rotulo="CPF"):
    return forms.CharField(label=rotulo, required=False, max_length=14, validators=[cpf_valido],
                           widget=forms.TextInput(attrs=_CPF))


def _telefone(rotulo="Telefone", *, obrigatorio=False):
    return forms.CharField(label=rotulo, required=obrigatorio, max_length=20, validators=[telefone_valido],
                           widget=forms.TextInput(attrs=_TELEFONE))


class CadastroPeloPacienteForm(LimpaMascara, forms.Form):
    CAMPOS_NUMERICOS = ("cpf", "telefone", "cep", "resp_cpf", "resp_telefone", "pagador_cpf",
                        "emergencia1_telefone", "emergencia2_telefone")

    # --- Sobre você ---
    menor = forms.BooleanField(label="Este cadastro é de criança ou adolescente", required=False,
                               widget=forms.CheckboxInput(attrs=_CHECK),
                               help_text="Quem preenche é o responsável. Abre os campos de quem responde pela criança.")
    nome = _texto("Nome completo", obrigatorio=True, autofocus=True)
    nome_social = _texto("Nome social", dica="Como prefere ser chamado(a), se for diferente")
    raca_cor = forms.ChoiceField(label="Raça/cor", required=False, choices=_VAZIO + list(Paciente.RacaCor.choices),
                                 widget=forms.Select(attrs=_SELECT))
    documento_tipo = forms.ChoiceField(
        label="Documento de identificação", required=False, initial="CPF",
        choices=[("CPF", "Brasileiro (CPF)"), ("ESTRANGEIRO", "Estrangeiro (passaporte ou RNM)")],
        widget=forms.Select(attrs=_SELECT))
    cpf = _cpf()
    documento_estrangeiro = _texto("Passaporte ou RNM", tamanho=40)
    data_nascimento = forms.DateField(label="Data de nascimento",
                                      widget=forms.DateInput(attrs={**_TEXTO, "type": "date"}, format="%Y-%m-%d"))
    estado_civil = forms.ChoiceField(label="Estado civil", required=False,
                                     choices=_VAZIO + list(Paciente.EstadoCivil.choices),
                                     widget=forms.Select(attrs=_SELECT))

    # --- Contato ---
    telefone = _telefone("Telefone do paciente")
    email = forms.EmailField(label="E-mail", required=False, widget=forms.EmailInput(attrs=_TEXTO))

    # --- Responsável legal (só para criança e adolescente) ---
    resp_nome = _texto("Nome do responsável")
    resp_parentesco = _texto("Parentesco", tamanho=60, dica="mãe, pai, avó, tutor")
    resp_cpf = _cpf("CPF do responsável")
    resp_telefone = _telefone("Telefone do responsável")
    resp_email = forms.EmailField(label="E-mail do responsável", required=False,
                                  widget=forms.EmailInput(attrs=_TEXTO))

    # --- Responsável financeiro (opcional) ---
    pagador_outro = forms.BooleanField(label="Quem paga é outra pessoa", required=False,
                                       widget=forms.CheckboxInput(attrs=_CHECK))
    pagador_nome = _texto("Nome de quem paga")
    pagador_cpf = _cpf("CPF de quem paga")

    # --- Contato de emergência ---
    emergencia1_nome = _texto("Nome", obrigatorio=True)
    emergencia1_parentesco = _texto("Parentesco", tamanho=60, dica="Ex.: mãe, irmão, amiga")
    emergencia1_telefone = _telefone(obrigatorio=True)
    emergencia2_nome = _texto("Nome")
    emergencia2_parentesco = _texto("Parentesco", tamanho=60, dica="Ex.: mãe, irmão, amiga")
    emergencia2_telefone = _telefone()

    # --- Endereço ---
    pais = _texto("País", tamanho=60)
    cep = forms.CharField(label="CEP", required=False, max_length=9, widget=forms.TextInput(attrs=_CEP))
    logradouro = _texto("Rua", dica="Rua, avenida ou estrada")
    numero = _texto("Número", tamanho=20)
    complemento = _texto("Complemento", tamanho=100, dica="Apto, bloco, referência")
    bairro = _texto("Bairro", tamanho=100)
    cidade = _texto("Cidade", tamanho=100)
    uf = forms.ChoiceField(label="Estado", required=False, choices=_VAZIO + list(Paciente.UF.choices),
                           widget=forms.Select(attrs=_SELECT))

    # --- Perfil e saúde ---
    genero = _texto("Gênero", tamanho=60, list="generos-sugeridos")
    profissao = _texto("Profissão", tamanho=120)
    medicamento = forms.CharField(
        label="Medicamento em uso", required=False, max_length=1000,
        widget=forms.Textarea(attrs={**_TEXTO, "rows": 2, "placeholder": "Se não usa nenhum, escreva “Nenhum”"}))

    # --- LGPD ---
    consentimento = forms.BooleanField(
        label="Li o aviso de privacidade e concordo em enviar estes dados", widget=forms.CheckboxInput(attrs=_CHECK),
        error_messages={"required": "Para enviar o cadastro, é preciso concordar com o aviso de privacidade."})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pais"].initial = "Brasil"

    def clean_data_nascimento(self):
        nascimento = self.cleaned_data["data_nascimento"]
        if nascimento > timezone.localdate():
            raise forms.ValidationError("A data de nascimento não pode estar no futuro.")
        return nascimento

    def clean(self):
        dados = super().clean()
        nascimento = dados.get("data_nascimento")
        menor = bool(dados.get("menor"))
        if nascimento:
            idade = convites.idade_em(nascimento)
            if menor and idade >= 18:
                self.add_error("menor", "Pela data de nascimento, a pessoa já tem 18 anos ou mais.")
            elif not menor and idade < 18:
                self.add_error("menor", "Pela data de nascimento, é menor de 18 anos: marque esta opção e informe "
                                        "o responsável.")
        if menor:
            # Criança pode não ter telefone; o responsável tem de ter.
            for campo, mensagem in [("resp_nome", "Informe o nome do responsável."),
                                    ("resp_telefone", "Informe o telefone do responsável.")]:
                if not dados.get(campo) and campo not in self.errors:
                    self.add_error(campo, mensagem)
        elif not dados.get("telefone") and "telefone" not in self.errors:
            self.add_error("telefone", "Informe um telefone para contato.")

        if dados.get("documento_tipo") == "ESTRANGEIRO":
            dados["cpf"] = ""
        else:
            dados["documento_estrangeiro"] = ""
        # O CEP brasileiro tem formato; o de fora, não — e não é por isso que o cadastro deve travar.
        if dados.get("cep") and (dados.get("pais") or "Brasil").strip().lower() in ("brasil", "brazil"):
            try:
                cep_valido(dados["cep"])
            except forms.ValidationError as erro:
                self.add_error("cep", erro)
        if dados.get("pagador_outro") and not dados.get("pagador_nome"):
            self.add_error("pagador_nome", "Informe o nome de quem paga.")
        if dados.get("emergencia2_nome") and not dados.get("emergencia2_telefone"):
            self.add_error("emergencia2_telefone", "Informe o telefone deste contato.")
        return dados

    def respostas(self) -> dict:
        """O que fica guardado no convite: só texto, no formato que o cadastro do psicólogo entende."""
        dados = self.cleaned_data
        respostas = {campo: dados.get(campo) or "" for campo in convites.CAMPOS_DO_PACIENTE}
        respostas["data_nascimento"] = dados["data_nascimento"].isoformat()
        respostas["menor"] = bool(dados.get("menor"))
        respostas["contatos_de_emergencia"] = [
            {"nome": dados[f"emergencia{n}_nome"], "parentesco": dados.get(f"emergencia{n}_parentesco", ""),
             "telefone": dados.get(f"emergencia{n}_telefone", "")}
            for n in (1, 2) if dados.get(f"emergencia{n}_nome")]
        if dados.get("menor"):
            respostas["responsavel"] = {
                "nome": dados.get("resp_nome", ""), "parentesco": dados.get("resp_parentesco", ""),
                "cpf": dados.get("resp_cpf", ""), "telefone": dados.get("resp_telefone", ""),
                "email": dados.get("resp_email", "")}
        if dados.get("pagador_outro"):
            respostas["pagador"] = {"nome": dados.get("pagador_nome", ""), "cpf": dados.get("pagador_cpf", "")}
        respostas["consentimento_em"] = timezone.now().isoformat()
        return respostas
