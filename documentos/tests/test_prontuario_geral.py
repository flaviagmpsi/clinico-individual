"""O prontuário geral na aba Documentos (ADR-079, ADR-080).

O prontuário geral é documento — o que se entrega ao paciente ou a quem solicitar — e por isso mora aqui. Os
registros de sessão moram na aba Prontuários, e a evolução é montada com eles: nesta tela ela não se edita.
"""

from datetime import datetime

from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from atendimentos import servicos as agenda
from atendimentos.models import Consulta
from contas.models import Psicologo
from core import contexto
from core.models import RegistroAuditoria
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente
from prontuarios import servicos as prontuarios

SENHA = "senha-de-teste-123"
REALIZADA = Consulta.Estado.REALIZADA


def momento(dia, hora=10):
    return timezone.make_aware(datetime(2026, 9, dia, hora))


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


class BaseProntuarioGeral(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.prontgeral@exemplo.com", "11111111111", "777777")
        self.bruno = criar_psicologo("bruno.prontgeral@exemplo.com", "22222222222", "787878")
        with contexto.como(self.ana.pk):
            self.marcos = Paciente(nome="Marcos Geral")
            caso = cadastrar_paciente(self.marcos)
            self.primeira = agenda.cadastrar_avulsa(caso, estado=REALIZADA, inicio=momento(3))
            self.segunda = agenda.cadastrar_avulsa(caso, estado=REALIZADA, inicio=momento(8))
            self.terceira = agenda.cadastrar_avulsa(caso, estado=REALIZADA, inicio=momento(15))
            self.falta = agenda.cadastrar_avulsa(caso, estado=Consulta.Estado.FALTOU, inicio=momento(4))
            prontuarios.confirmar(self.primeira, self.marcos, texto="Registro da primeira sessão.")
            prontuarios.confirmar(self.segunda, self.marcos, texto="Registro da segunda sessão.")
            prontuarios.salvar_rascunho(self.terceira, self.marcos, texto="Rascunho da terceira.")
        with contexto.como(self.bruno.pk):
            self.carla = Paciente(nome="Carla Geral")
            cadastrar_paciente(self.carla)

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def folha(self, paciente=None):
        return reverse("documentos:prontuario", args=[(paciente or self.marcos).pk])

    def baixar(self, formato="pdf", paciente=None):
        return reverse("documentos:baixar_prontuario", args=[(paciente or self.marcos).pk, formato])


class ExigeLoginENaoAtravessa(BaseProntuarioGeral):
    def test_nao_abre_sem_login(self):
        for rota in [reverse("documentos:escolher_prontuario"), self.folha(), self.baixar()]:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 302)

    def test_paciente_de_outro_psicologo_da_404(self):
        self.entrar(self.ana)
        for rota in [self.folha(self.carla), self.baixar("pdf", self.carla),
                     reverse("documentos:escolher_prontuario") + f"?paciente={self.carla.pk}"]:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 404)
        self.assertEqual(self.client.post(self.folha(self.carla), {"demanda": "Intrusão."}).status_code, 404)


class OndeMora(BaseProntuarioGeral):
    def test_a_aba_documentos_oferece_o_prontuario_e_a_aba_prontuarios_aponta_para_ela(self):
        self.entrar(self.ana)
        aba = self.client.get(reverse("documentos:aba"))
        self.assertContains(aba, "Prontuário psicológico")
        self.assertContains(aba, reverse("documentos:escolher_prontuario"))
        registros = self.client.get(reverse("prontuarios:lista"))
        self.assertContains(registros, "registros de sessão")
        self.assertContains(registros, reverse("documentos:escolher_prontuario"))

    def test_sem_paciente_mostra_a_orientacao_e_o_seletor_so_com_os_proprios(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("documentos:escolher_prontuario"))
        self.assertContains(resposta, "Quatro partes, e nenhuma é opcional")
        self.assertContains(resposta, "Escolha um paciente")
        self.assertContains(resposta, "Marcos Geral")
        self.assertNotContains(resposta, "Carla Geral")
        self.assertNotContains(resposta, 'name="demanda"')

    def test_escolher_o_paciente_leva_a_folha_dele(self):
        self.entrar(self.ana)
        resposta = self.client.get(reverse("documentos:escolher_prontuario"), {"paciente": self.marcos.pk})
        self.assertRedirects(resposta, self.folha(), fetch_redirect_response=False)


class AFolha(BaseProntuarioGeral):
    def test_reune_todos_os_registros_confirmados_em_ordem_e_avisa_do_que_falta(self):
        self.entrar(self.ana)
        resposta = self.client.get(self.folha())
        texto = resposta.content.decode()
        self.assertContains(resposta, "PRONTUÁRIO PSICOLÓGICO")
        self.assertContains(resposta, "Res. CFP nº 001/2009")
        self.assertContains(resposta, "sem frequência fixa")  # a sugestão administrativa da demanda
        self.assertLess(texto.index("Registro da primeira sessão."), texto.index("Registro da segunda sessão."))
        self.assertNotContains(resposta, "Rascunho da terceira.")  # rascunho não é prontuário
        self.assertContains(resposta, "com registro ainda em rascunho")
        self.assertContains(resposta, reverse("prontuarios:escrever", args=[self.terceira.pk, self.marcos.pk]))
        self.assertNotContains(resposta, "04/09/2026")  # falta não tem evolução

    def test_a_evolucao_nao_se_edita_nesta_tela(self):
        self.entrar(self.ana)
        resposta = self.client.get(self.folha())
        self.assertContains(resposta, 'name="demanda"')
        self.assertContains(resposta, 'name="encerramento"')
        self.assertNotContains(resposta, 'name="evolucao')
        self.client.post(self.folha(), {"acao": "salvar", "demanda": "Demanda.", "encerramento": "",
                                        f"evolucao_{self.primeira.pk}": "Adulterado pela folha."})
        with contexto.como(self.ana.pk):
            self.assertEqual(prontuarios.registro_de(self.primeira, self.marcos).vigente.texto,
                             "Registro da primeira sessão.")

    def test_salvar_grava_demanda_e_encerramento(self):
        self.entrar(self.ana)
        resposta = self.client.post(self.folha(), {"acao": "salvar", "demanda": "Demanda pela tela.",
                                                   "encerramento": "Alta em comum acordo."}, follow=True)
        self.assertContains(resposta, "Prontuário salvo.")
        self.assertContains(resposta, "Demanda pela tela.")
        with contexto.como(self.ana.pk):
            ficha = prontuarios.ficha_de(self.marcos)
        self.assertEqual((ficha.demanda, ficha.encerramento), ("Demanda pela tela.", "Alta em comum acordo."))

    def test_abrir_a_folha_entra_na_trilha(self):
        self.entrar(self.ana)
        self.client.get(self.folha())
        self.assertTrue(RegistroAuditoria.objetos_todos.filter(
            acao="VER", titular="pacientes.paciente", titular_id=self.marcos.pk).exists())


class EmArquivo(BaseProntuarioGeral):
    def test_salvar_e_baixar_leva_ao_arquivo(self):
        self.entrar(self.ana)
        resposta = self.client.post(self.folha(), {"acao": "docx", "demanda": "Demanda.", "encerramento": ""})
        self.assertRedirects(resposta, self.baixar("docx"), fetch_redirect_response=False)

    def test_baixar_em_pdf_e_docx_registra_a_exportacao(self):
        self.entrar(self.ana)
        pdf = self.client.get(self.baixar("pdf"))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertIn('filename="prontuario-marcos-geral.pdf"', pdf["Content-Disposition"])
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        docx = self.client.get(self.baixar("docx"))
        self.assertIn("wordprocessingml", docx["Content-Type"])
        self.assertTrue(docx.content.startswith(b"PK"))
        self.assertEqual(RegistroAuditoria.objetos_todos.filter(
            acao="EXPORTAR", titular="pacientes.paciente", titular_id=self.marcos.pk).count(), 2)

    def test_formato_desconhecido_da_404(self):
        self.entrar(self.ana)
        self.assertEqual(self.client.get(self.baixar("exe")).status_code, 404)
