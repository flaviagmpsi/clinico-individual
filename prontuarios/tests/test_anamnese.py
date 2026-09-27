"""A anamnese: sub-aba opcional da ficha do paciente (ADR-085), por blocos que o psicólogo edita (ADR-101).

Opcional de verdade — abrir e salvar em branco não grava nada —, editável, auditada sem o conteúdo, isolada por
psicólogo, e protege o paciente contra exclusão. O roteiro é do psicólogo: ele acrescenta, arquiva e reordena temas.
"""

import json

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo
from core import contexto, db
from core.models import RegistroAuditoria
from pacientes.models import Paciente
from pacientes.servicos import cadastrar_paciente, excluir_paciente
from prontuarios import anamneses
from prontuarios.models import Anamnese, RespostaDeAnamnese, TemaDeAnamnese
from prontuarios.temas import TEMAS_SUGERIDOS

SENHA = "senha-de-teste-123"


def criar_psicologo(email, cpf, crp):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=email, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


class Base(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.anamnese@exemplo.com", "11111111111", "707070")
        self.bruno = criar_psicologo("bruno.anamnese@exemplo.com", "22222222222", "717171")
        with contexto.como(self.ana.pk):
            self.marcos = Paciente(nome="Marcos Anamnese")
            cadastrar_paciente(self.marcos)
        with contexto.como(self.bruno.pk):
            self.carla = Paciente(nome="Carla Anamnese")
            cadastrar_paciente(self.carla)
            anamneses.salvar(self.carla, {self.tema_do_bruno("queixa_principal").pk: "Queixa da Carla."})

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def rota(self, paciente=None):
        return reverse("prontuarios:anamnese", args=[(paciente or self.marcos).pk])

    def tema(self, origem: str, dono=None) -> TemaDeAnamnese:
        with contexto.como((dono or self.ana).pk):
            return next(t for t in anamneses.roteiro() if t.origem == origem)

    def tema_do_bruno(self, origem: str) -> TemaDeAnamnese:
        return next(t for t in anamneses.roteiro() if t.origem == origem)

    def tem_bloco(self, resposta, tema) -> bool:
        """O tema está no roteiro **daquela** anamnese quando a caixa de texto dele está na tela.

        Procurar o título solto no HTML não serve: ele também aparece no exemplo do campo de tema novo e na lista
        de arquivados — foi assim que a primeira versão destes testes se enganou.
        """
        return f'name="tema_{tema.pk}"' in resposta.content.decode()

    def escrever(self, **por_origem):
        """POST no formulário, dizendo o tema pela origem: `escrever(queixa_principal="...")`."""
        return self.client.post(self.rota(), {f"tema_{self.tema(o).pk}": texto for o, texto in por_origem.items()})


class AnamneseDoPaciente(Base):
    def test_exige_login_e_nao_abre_a_de_outro_psicologo(self):
        self.assertEqual(self.client.get(self.rota()).status_code, 302)
        self.entrar(self.ana)
        self.assertEqual(self.client.get(self.rota(self.carla)).status_code, 404)
        self.assertEqual(self.client.post(self.rota(self.carla), {}).status_code, 404)
        with contexto.como(self.bruno.pk):
            self.assertEqual(Anamnese.objects.get(paciente=self.carla).respostas.first().texto, "Queixa da Carla.")

    def test_e_opcional_abrir_e_salvar_em_branco_nao_grava_nada(self):
        self.entrar(self.ana)
        resposta = self.client.get(self.rota())
        self.assertContains(resposta, "opcional")
        self.assertContains(resposta, "Queixa principal")
        self.assertContains(resposta, "não entra no prontuário")
        self.escrever(queixa_principal="   ")
        self.assertFalse(Anamnese.objetos_todos.filter(paciente=self.marcos).exists())

    def test_o_roteiro_sugerido_nasce_na_primeira_abertura(self):
        self.entrar(self.ana)
        self.assertEqual(TemaDeAnamnese.objetos_todos.filter(psicologo=self.ana).count(), 0)
        corpo = self.client.get(self.rota()).content.decode()
        self.assertEqual(TemaDeAnamnese.objetos_todos.filter(psicologo=self.ana).count(), len(TEMAS_SUGERIDOS))
        for _, titulo, _ in TEMAS_SUGERIDOS:
            self.assertIn(titulo, corpo)

    def test_salva_edita_e_a_trilha_nao_guarda_o_conteudo(self):
        self.entrar(self.ana)
        self.escrever(queixa_principal="Conteúdo sigiloso da queixa.", expectativas="Dormir.")
        anamnese = Anamnese.objetos_todos.get(paciente=self.marcos)
        self.assertEqual(anamnese.psicologo_id, self.ana.pk)
        with contexto.como(self.ana.pk):
            self.assertEqual(anamnese.preenchidos, 2)
        self.escrever(queixa_principal="Queixa revista.", expectativas="Dormir.")
        with contexto.como(self.ana.pk):
            texto = anamnese.respostas.get(tema__origem="queixa_principal").texto
        self.assertEqual(texto, "Queixa revista.")  # edita-se, ao contrário do registro de sessão
        self.assertEqual(Anamnese.objetos_todos.filter(paciente=self.marcos).count(), 1)
        self.assertContains(self.client.get(self.rota()), "Queixa revista.")
        trilha = RegistroAuditoria.objetos_todos.filter(alvo="prontuarios.anamnese", titular_id=self.marcos.pk)
        self.assertEqual({r.acao for r in trilha}, {"CRIAR", "ALTERAR", "VER"})
        # a trilha diz qual tema mudou, nunca o que foi escrito nele
        self.assertIn(["Queixa principal"], [r.campos for r in trilha])
        self.assertNotIn("sigiloso", json.dumps([r.campos for r in trilha]))

    def test_paciente_com_anamnese_nao_e_apagado(self):
        with contexto.como(self.ana.pk):
            excluir_paciente(Paciente.objects.get(pk=cadastrar_e_devolver("Sem Anamnese")))
            anamneses.salvar(self.marcos, {self.tema("queixa_principal").pk: "Queixa."})
            with self.assertRaises(ValidationError):
                excluir_paciente(self.marcos)

    def test_sql_cru_so_devolve_a_resposta_do_dono(self):
        if connection.vendor != "postgresql":
            self.skipTest("RLS exige PostgreSQL.")
        with contexto.como(self.ana.pk):
            anamneses.salvar(self.marcos, {self.tema("queixa_principal").pk: "Queixa do Marcos."})
        with transaction.atomic():
            db.assumir_papel_da_aplicacao()
            db.aplicar_escopo(self.ana.pk)
            with connection.cursor() as cursor:
                cursor.execute("SELECT texto FROM prontuarios_respostadeanamnese")
                self.assertEqual(cursor.fetchall(), [("Queixa do Marcos.",)])


class RoteiroDoPsicologo(Base):
    """ADR-101: os blocos que já estão lá, mais os que o psicólogo criar."""

    def setUp(self):
        super().setUp()
        self.entrar(self.ana)
        self.client.get(self.rota())  # nasce o roteiro sugerido

    def test_acrescenta_tema_e_ele_vale_para_os_proximos_pacientes(self):
        resposta = self.client.post(self.rota(), {"acao": "tema:novo", "titulo": "  História espiritual ",
                                                  "ajuda": "Fé e práticas."}, follow=True)
        self.assertContains(resposta, "História espiritual")
        with contexto.como(self.ana.pk):
            tema = TemaDeAnamnese.objects.get(titulo="História espiritual")
        self.assertEqual((tema.ajuda, tema.arquivado), ("Fé e práticas.", False))
        # o tema é do psicólogo: aparece na anamnese de outro paciente dele
        with contexto.como(self.ana.pk):
            outra = Paciente(nome="Outra Paciente")
            cadastrar_paciente(outra)
        self.assertTrue(self.tem_bloco(self.client.get(self.rota(outra)), tema))
        # e não vaza para outro psicólogo
        self.client.logout()
        self.entrar(self.bruno)
        self.assertFalse(self.tem_bloco(self.client.get(self.rota(self.carla)), tema))

    def test_tema_repetido_e_recusado(self):
        self.client.post(self.rota(), {"acao": "tema:novo", "titulo": "História espiritual"})
        resposta = self.client.post(self.rota(), {"acao": "tema:novo", "titulo": "história ESPIRITUAL"})
        self.assertContains(resposta, "já tem um tema chamado")
        with contexto.como(self.ana.pk):
            self.assertEqual(TemaDeAnamnese.objects.filter(titulo__icontains="espiritual").count(), 1)

    def test_tema_sem_nome_e_recusado(self):
        resposta = self.client.post(self.rota(), {"acao": "tema:novo", "titulo": "   "})
        self.assertEqual(resposta.status_code, 200)
        with contexto.como(self.ana.pk):
            self.assertEqual(TemaDeAnamnese.objects.count(), len(TEMAS_SUGERIDOS))

    def test_arquivar_tira_do_roteiro_e_mantem_o_que_ja_foi_escrito(self):
        tema = self.tema("rotina_e_lazer")
        self.escrever(rotina_e_lazer="Corre de manhã.")
        self.client.post(self.rota(), {"acao": f"tema:arquivar:{tema.pk}"})
        # some da anamnese em branco de outro paciente
        with contexto.como(self.ana.pk):
            outra = Paciente(nome="Outra Sem Rotina")
            cadastrar_paciente(outra)
        em_branco = self.client.get(self.rota(outra))
        self.assertFalse(self.tem_bloco(em_branco, tema))
        self.assertContains(em_branco, "Arquivados: Rotina e lazer")  # dito, para ele saber que pode voltar
        # e continua onde já havia resposta
        aberta = self.client.get(self.rota())
        self.assertTrue(self.tem_bloco(aberta, tema))
        self.assertContains(aberta, "Corre de manhã.")
        self.assertContains(aberta, "arquivado")
        # volta ao roteiro
        self.client.post(self.rota(), {"acao": f"tema:voltar:{tema.pk}"})
        self.assertTrue(self.tem_bloco(self.client.get(self.rota(outra)), tema))

    def test_mover_troca_a_ordem_com_o_vizinho(self):
        with contexto.como(self.ana.pk):
            primeiro, segundo = list(anamneses.roteiro())[:2]
        self.client.post(self.rota(), {"acao": f"tema:subir:{segundo.pk}"})
        with contexto.como(self.ana.pk):
            self.assertEqual([t.pk for t in anamneses.roteiro()][:2], [segundo.pk, primeiro.pk])
        # o primeiro do roteiro não sobe mais: a tela não quebra, só não faz nada
        self.client.post(self.rota(), {"acao": f"tema:subir:{segundo.pk}"})
        with contexto.como(self.ana.pk):
            self.assertEqual([t.pk for t in anamneses.roteiro()][0], segundo.pk)

    def test_mexer_no_roteiro_nao_perde_o_que_esta_escrito(self):
        self.escrever(queixa_principal="Não pode sumir.")
        tema = self.tema("saude_geral")
        self.client.post(self.rota(), {**{f"tema_{self.tema('queixa_principal').pk}": "Não pode sumir."},
                                       "acao": f"tema:arquivar:{tema.pk}"})
        self.assertContains(self.client.get(self.rota()), "Não pode sumir.")

    def test_tema_de_outro_psicologo_da_404(self):
        with contexto.como(self.bruno.pk):
            dele = anamneses.roteiro()[0]
        self.assertEqual(self.client.post(self.rota(), {"acao": f"tema:arquivar:{dele.pk}"}).status_code, 404)

    def test_tema_com_resposta_nao_e_apagado_por_engano(self):
        """`PROTECT` na resposta: o roteiro se arquiva, não se apaga com texto dentro."""
        self.escrever(queixa_principal="Texto.")
        with contexto.como(self.ana.pk):
            tema = self.tema("queixa_principal")
            with self.assertRaises(Exception):
                tema.delete()
            self.assertEqual(RespostaDeAnamnese.objects.count(), 1)


def cadastrar_e_devolver(nome: str) -> int:
    paciente = Paciente(nome=nome)
    cadastrar_paciente(paciente)
    return paciente.pk
