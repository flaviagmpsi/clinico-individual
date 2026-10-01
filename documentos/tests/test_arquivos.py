"""Guarda de arquivo feito fora do sistema (ADR-112, fecha D-01, D-02 e D-04).

O que estes testes protegem, em ordem de gravidade: que **arquivo de um psicólogo não alcança outro**, que
executável renomeado para `.pdf` não entra, e que apagar o arquivo apaga os bytes junto.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo
from core import contexto
from documentos import guarda
from documentos.arquivos import ArquivoGuardado, ConteudoDeArquivo
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente

SENHA = "hamilton123"
PDF = b"%PDF-1.4\n% um contrato de mentira\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


def enviado(conteudo: bytes, nome: str = "contrato.pdf", tipo: str = "application/pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(nome, conteudo, content_type=tipo)


class Conferencia(SimpleTestCase):
    """`guarda.conferir` é a porta: o que passa por ela vira arquivo guardado. Não toca o banco."""

    def test_aceita_pdf_jpg_e_png_pelo_que_os_bytes_dizem(self):
        for conteudo, esperado in ((PDF, "application/pdf"), (PNG, "image/png"),
                                   (b"\xff\xd8\xff" + b"\x00" * 20, "image/jpeg")):
            with self.subTest(esperado=esperado):
                self.assertEqual(guarda.conferir(enviado(conteudo)).tipo_mime, esperado)

    def test_executavel_renomeado_para_pdf_nao_entra(self):
        """O `content_type` do upload vem do cliente e é forjável; a assinatura dos bytes, não."""
        disfarcado = enviado(b"MZ\x90\x00programa", nome="contrato.pdf", tipo="application/pdf")
        with self.assertRaises(ValidationError) as erro:
            guarda.conferir(disfarcado)
        self.assertIn("Formato não aceito", erro.exception.messages[0])

    def test_arquivo_vazio_e_arquivo_grande_demais_sao_recusados(self):
        with self.assertRaises(ValidationError):
            guarda.conferir(enviado(b""))
        with self.assertRaises(ValidationError) as erro:
            guarda.conferir(enviado(PDF + b"\x00" * (10 * 1024 * 1024)))
        self.assertIn("10 MB", erro.exception.messages[0])

    def test_o_nome_perde_caminho_e_ganha_a_extensao_do_formato_real(self):
        """O nome vai para um cabeçalho de download: barra e aspas não podem passar."""
        recebido = guarda.conferir(enviado(PDF, nome="C:\\Users\\Ana\\meu \"contrato\".pdf"))
        self.assertEqual(recebido.nome, "meu contrato.pdf")
        # Um PNG chamado ".pdf" sai com a extensão que os bytes provaram.
        self.assertEqual(guarda.conferir(enviado(PNG, nome="foto.pdf")).nome, "foto.png")

    def test_sem_arquivo_nenhum_tambem_recusa(self):
        with self.assertRaises(ValidationError):
            guarda.conferir(None)


class _Mundo:
    """Dois psicólogos, um paciente de cada. Montado em `setUp` porque as telas pedem `TransactionTestCase`."""

    def montar(self):
        self.ana = Psicologo.objects.create_user(email="ana@t.com", password=SENHA, nome_completo="Ana",
                                                 crp_regiao="04", crp_numero="1")
        self.bruno = Psicologo.objects.create_user(email="bruno@t.com", password=SENHA, nome_completo="Bruno",
                                                   crp_regiao="04", crp_numero="2")
        with contexto.como(self.ana.pk):
            self.paciente = cadastrar_paciente(Paciente(nome="Carolina")).pacientes.first()
        with contexto.como(self.bruno.pk):
            self.paciente_do_bruno = cadastrar_paciente(Paciente(nome="Diego")).pacientes.first()

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))


class Base(_Mundo, TestCase):
    """Para o que fala com o serviço direto, sem passar por view."""

    def setUp(self):
        self.montar()


class BaseDeTela(_Mundo, TransactionTestCase):
    """Para o que passa pela tela.

    `TransactionTestCase` pelo motivo de sempre aqui: o middleware troca o papel do banco com `SET LOCAL ROLE`,
    e num `TestCase` — uma transação só para o teste inteiro — o papel vaza da primeira requisição para a
    seguinte, que morre em `permission denied for table django_session`.
    """

    def setUp(self):
        self.montar()


class Guardar(Base):
    def test_guardar_grava_metadado_e_bytes_juntos(self):
        with contexto.como(self.ana.pk):
            arquivo = guarda.guardar(self.paciente, guarda.conferir(enviado(PDF)),
                                     titulo="Contrato de março", tipo=ArquivoGuardado.Tipo.CONTRATO)
            self.assertEqual(arquivo.tamanho, len(PDF))
            self.assertEqual(guarda.conteudo(arquivo), PDF)

    def test_apagar_o_arquivo_apaga_os_bytes(self):
        """Bytes órfãos seriam dado clínico sem dono — e sem RLS, porque a RLS está no metadado."""
        with contexto.como(self.ana.pk):
            arquivo = guarda.guardar(self.paciente, guarda.conferir(enviado(PDF)), titulo="X",
                                     tipo=ArquivoGuardado.Tipo.CONTRATO)
            pk = arquivo.pk
            arquivo.delete()
            self.assertFalse(ConteudoDeArquivo.objects.filter(pk=pk).exists())

    def test_a_marca_de_restrito_e_guardada(self):
        with contexto.como(self.ana.pk):
            arquivo = guarda.guardar(self.paciente, guarda.conferir(enviado(PDF)), titulo="Protocolo",
                                     tipo=ArquivoGuardado.Tipo.AVALIACAO, restrito=True)
            self.assertTrue(ArquivoGuardado.objects.get(pk=arquivo.pk).restrito)


class NaoAtravessaAFronteira(BaseDeTela):
    def test_a_lista_de_um_nao_mostra_o_arquivo_do_outro(self):
        with contexto.como(self.bruno.pk):
            guarda.guardar(self.paciente_do_bruno, guarda.conferir(enviado(PDF)), titulo="Do Bruno",
                           tipo=ArquivoGuardado.Tipo.CONTRATO)
        with contexto.como(self.ana.pk):
            self.assertEqual(guarda.do_paciente(self.paciente), [])
            self.assertEqual(ArquivoGuardado.objects.count(), 0)

    def test_baixar_arquivo_alheio_pelo_id_da_404(self):
        with contexto.como(self.bruno.pk):
            alheio = guarda.guardar(self.paciente_do_bruno, guarda.conferir(enviado(PDF)), titulo="Do Bruno",
                                    tipo=ArquivoGuardado.Tipo.CONTRATO)
        self.entrar(self.ana)
        for rota in ("documentos:baixar_arquivo", "documentos:excluir_arquivo"):
            with self.subTest(rota=rota):
                metodo = self.client.get if "baixar" in rota else self.client.post
                self.assertEqual(metodo(reverse(rota, args=[alheio.pk])).status_code, 404)

    def test_guardar_em_paciente_alheio_da_404(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("documentos:guardar_arquivo", args=[self.paciente_do_bruno.pk]),
                                    {"titulo": "X", "tipo": "CONTRATO", "arquivo": enviado(PDF)})
        self.assertEqual(resposta.status_code, 404)


class PelaTela(BaseDeTela):
    def test_subir_pela_tela_aparece_na_aba_do_paciente(self):
        self.entrar(self.ana)
        aba = f"{reverse('documentos:aba')}?paciente={self.paciente.pk}"
        self.client.post(reverse("documentos:guardar_arquivo", args=[self.paciente.pk]),
                         {"titulo": "Contrato assinado", "tipo": "CONTRATO", "arquivo": enviado(PDF)})
        self.assertContains(self.client.get(aba), "Contrato assinado")

    def test_baixar_devolve_os_bytes_com_o_nome_limpo(self):
        self.entrar(self.ana)
        with contexto.como(self.ana.pk):
            arquivo = guarda.guardar(self.paciente, guarda.conferir(enviado(PDF, nome="a/b/contrato.pdf")),
                                     titulo="Contrato", tipo=ArquivoGuardado.Tipo.CONTRATO)
        resposta = self.client.get(reverse("documentos:baixar_arquivo", args=[arquivo.pk]))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.content, PDF)
        self.assertEqual(resposta["Content-Disposition"], 'attachment; filename="contrato.pdf"')

    def test_executavel_disfarcado_pela_tela_nao_guarda_nada(self):
        self.entrar(self.ana)
        self.client.post(reverse("documentos:guardar_arquivo", args=[self.paciente.pk]),
                         {"titulo": "X", "tipo": "CONTRATO",
                          "arquivo": enviado(b"MZ\x90\x00", nome="contrato.pdf")})
        with contexto.como(self.ana.pk):
            self.assertEqual(ArquivoGuardado.objects.count(), 0)

    def test_a_aba_sem_nada_guardado_ensina_o_que_cabe_ali(self):
        self.entrar(self.ana)
        resposta = self.client.get(f"{reverse('documentos:aba')}?paciente={self.paciente.pk}")
        self.assertContains(resposta, "contrato terapêutico")


class OBancoTrancaSozinho(TransactionTestCase):
    """A terceira camada da ADR-001: o Postgres recusa, mesmo quando o código pede errado.

    `TransactionTestCase` porque o papel do banco é trocado com `SET LOCAL ROLE`, e isso precisa de transações de
    verdade. SQL cru de propósito: é o caminho que as duas primeiras camadas (manager e `contexto`) não cobrem.
    """

    def setUp(self):
        self.ana = Psicologo.objects.create_user(email="ana.rls@t.com", password=SENHA, nome_completo="Ana",
                                                 crp_regiao="04", crp_numero="31")
        self.bruno = Psicologo.objects.create_user(email="bruno.rls@t.com", password=SENHA, nome_completo="Bruno",
                                                   crp_regiao="04", crp_numero="32")
        with contexto.como(self.bruno.pk):
            paciente = cadastrar_paciente(Paciente(nome="Diego")).pacientes.first()
            self.do_bruno = guarda.guardar(paciente, guarda.conferir(enviado(PDF)), titulo="Contrato do Bruno",
                                           tipo=ArquivoGuardado.Tipo.CONTRATO)

    def test_sql_cru_na_sessao_de_um_nao_le_os_bytes_do_outro(self):
        """O conteúdo mora numa tabela sem coluna de dono; sem a policy da ADR-113, isto devolvia o contrato alheio."""
        from django.db import connection

        from core import db

        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.ana.pk)
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM documentos_conteudodearquivo")
                self.assertEqual(cursor.fetchone()[0], 0, "a Ana enxergou bytes que não são dela")
                cursor.execute("SELECT count(*) FROM documentos_arquivoguardado")
                self.assertEqual(cursor.fetchone()[0], 0)

    def test_e_o_dono_continua_lendo_os_proprios(self):
        """Uma policy que nega tudo também 'passa' no teste acima — este é o outro lado da prova."""
        from django.db import connection

        from core import db

        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.bruno.pk)
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM documentos_conteudodearquivo")
                self.assertEqual(cursor.fetchone()[0], 1)
