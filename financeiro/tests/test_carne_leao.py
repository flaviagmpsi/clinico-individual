"""A categoria do carnê-leão na despesa (ADR-099).

O sistema separa o que a Receita aceita do que ela recusa, mostra a regra e não apura no lugar do psicólogo.
"""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TransactionTestCase
from django.urls import reverse

from contas.models import Psicologo
from core import contexto
from financeiro import carne_leao
from financeiro.models import Despesa

SENHA = "senha-de-teste-123"


class Catalogo(SimpleTestCase):
    def test_toda_categoria_tem_codigo_unico_grupo_e_explicacao(self):
        codigos = [c.codigo for c in carne_leao.CATEGORIAS]
        self.assertEqual(len(codigos), len(set(codigos)))
        for c in carne_leao.CATEGORIAS:
            with self.subTest(categoria=c.codigo):
                self.assertTrue(c.nome and c.grupo and c.explicacao)
                self.assertIn(c.dedutibilidade, carne_leao.Dedutibilidade.ROTULOS)

    def test_o_que_a_receita_recusa_nao_deduz(self):
        """Transporte é o caso que motivou a ADR: antes, "gasolina" virava dedução."""
        self.assertFalse(carne_leao.categoria("TRANSPORTE").deduz)
        self.assertFalse(carne_leao.categoria("EQUIPAMENTO").deduz)
        self.assertFalse(carne_leao.categoria("IMOVEL_PROPRIO").deduz)
        self.assertFalse(carne_leao.categoria("PESSOAL_DO_PSICOLOGO").deduz)

    def test_o_que_e_despesa_de_custeio_deduz(self):
        for codigo in ["ALUGUEL", "CONTAS_DO_CONSULTORIO", "MATERIAL", "PESSOAL", "FORMACAO", "CASA_PROPORCIONAL"]:
            with self.subTest(categoria=codigo):
                self.assertTrue(carne_leao.categoria(codigo).deduz)

    def test_zona_cinzenta_nao_e_apresentada_como_certa(self):
        """Supervisão e CRP dependem do caso concreto: a tela pede confirmação, não decide (P-28)."""
        for codigo in ["SUPERVISAO", "CRP", "OUTRA"]:
            with self.subTest(categoria=codigo):
                categoria = carne_leao.categoria(codigo)
                self.assertEqual(categoria.dedutibilidade, carne_leao.Dedutibilidade.CONFIRMAR)
                self.assertFalse(categoria.deduz)  # na dúvida, não soma sozinho
                self.assertIn("contabilidade", categoria.explicacao.lower())

    def test_codigo_desconhecido_cai_no_padrao_em_vez_de_explodir(self):
        self.assertEqual(carne_leao.categoria("INVENTADA").codigo, carne_leao.PADRAO)

    def test_os_grupos_saem_na_ordem_do_catalogo(self):
        self.assertEqual([grupo for grupo, _ in carne_leao.por_grupo()],
                         ["O consultório", "O trabalho", "Fora do carnê-leão"])


class DespesaComCategoria(TransactionTestCase):
    def setUp(self):
        self.ana = Psicologo.objects.create_user(
            email="ana.carneleao@exemplo.com", password=SENHA, nome_completo="Ana Ribeiro", cpf="11111111111",
            telefone="31988887777", crp_regiao="04", crp_numero="606060")
        self.assertTrue(self.client.login(username=self.ana.email, password=SENHA))
        self.mes = date.today().replace(day=1)

    def cadastrar(self, **campos):
        dados = {"categoria": "ALUGUEL", "descricao": "Sala da terça", "valor": "1.200,00",
                 "vencimento": self.mes.isoformat(), "fim": ""}
        dados.update(campos)
        return self.client.post(reverse("financeiro:despesa_nova"), dados)

    def test_a_tela_oferece_as_categorias_agrupadas_e_diz_o_que_a_receita_faz_com_cada_uma(self):
        corpo = self.client.get(reverse("financeiro:despesa_nova")).content.decode()
        self.assertIn('<optgroup label="O consultório">', corpo)
        self.assertIn('<optgroup label="Fora do carnê-leão">', corpo)
        self.assertIn("Não entra no carnê-leão", corpo)
        self.assertIn("representante comercial autônomo", corpo)  # a regra do transporte, com a razão
        self.assertIn("gov.br/receitafederal", corpo)  # a fonte à vista

    def test_a_despesa_guarda_a_categoria(self):
        self.assertEqual(self.cadastrar().status_code, 302)
        with contexto.como(self.ana.pk):
            despesa = Despesa.objects.get(descricao="Sala da terça")
        self.assertEqual((despesa.categoria, despesa.deduz), ("ALUGUEL", True))

    def test_sem_categoria_nao_cadastra(self):
        resposta = self.cadastrar(categoria="")
        self.assertEqual(resposta.status_code, 200)
        with contexto.como(self.ana.pk):
            self.assertFalse(Despesa.objects.exists())

    def test_categoria_inventada_no_post_e_recusada(self):
        self.assertEqual(self.cadastrar(categoria="GASOLINA").status_code, 200)
        with contexto.como(self.ana.pk):
            self.assertFalse(Despesa.objects.exists())

    def test_o_mes_separa_o_que_entra_no_carne_leao_do_que_so_saiu_do_caixa(self):
        self.cadastrar(categoria="ALUGUEL", descricao="Sala", valor="1.000,00")
        self.cadastrar(categoria="TRANSPORTE", descricao="Uber para o consultório", valor="300,00")
        resposta = self.client.get(f"{reverse('financeiro:despesas')}?mes={self.mes:%Y-%m}")
        self.assertEqual(resposta.context["total"], Decimal("1300.00"))
        self.assertEqual(resposta.context["dedutivel"], Decimal("1000.00"))
        corpo = resposta.content.decode()
        self.assertIn("Entra no carnê-leão", corpo)
        self.assertIn("Transporte e veículo", corpo)
