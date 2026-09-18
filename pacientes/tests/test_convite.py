"""Convite de cadastro: o paciente preenche os próprios dados por um link (ADR-081).

- `Servicos` — só o hash é guardado; resposta única; validade; aceitar cria o que veio junto e esvazia o convite.
- `ContatosDeEmergencia` — o serviço só regrava o que mudou.
- `NoBanco` — a fresta de `hamilton_web`: uma linha, uma resposta, e nenhuma tabela clínica.
- `ForaDoBrasil` — endereço escrito à mão: sem formato de CEP, sem DDD, sem lista de UF (ADR-082).
- `TelaPublica` — sem login; menor pede responsável; os becos do link; cabeçalhos que protegem o token.
- `TelasDoPsicologo` — gerar, ver o link uma vez, revisar, cadastrar, cancelar; e o isolamento entre psicólogos.
"""

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.utils import ProgrammingError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from contas.models import Psicologo
from core import contexto, db
from core.models import RegistroAuditoria
from pacientes import convites
from pacientes.models import ContatoDeEmergencia, ConviteDeCadastro, Paciente, ResponsavelLegal
from pacientes.servicos import cadastrar_paciente, caso_individual_de, definir_contatos_de_emergencia

SENHA = "senha-de-teste-123"

RESPOSTAS = {
    "nome": "Helena Prado", "nome_social": "Lena", "raca_cor": "PARDA", "cpf": "11144477735",
    "data_nascimento": "1990-05-20", "estado_civil": "SOLTEIRO", "telefone": "31988887777",
    "email": "helena@exemplo.com", "pais": "Brasil", "cidade": "Belo Horizonte", "uf": "MG",
    "genero": "Mulher cisgênero", "profissao": "Engenheira", "medicamento": "Nenhum",
    "contatos_de_emergencia": [{"nome": "Rosa Prado", "parentesco": "mãe", "telefone": "31977776666"}],
}

FORMULARIO = {
    "nome": "Helena Prado", "nome_social": "Lena", "raca_cor": "PARDA", "documento_tipo": "CPF",
    "cpf": "111.444.777-35", "data_nascimento": "1990-05-20", "estado_civil": "SOLTEIRO",
    "telefone": "(31) 98888-7777", "email": "helena@exemplo.com",
    "emergencia1_nome": "Rosa Prado", "emergencia1_parentesco": "mãe", "emergencia1_telefone": "(31) 97777-6666",
    "pais": "Brasil", "cep": "30140-071", "logradouro": "Rua da Bahia", "numero": "1200", "bairro": "Lourdes",
    "cidade": "Belo Horizonte", "uf": "MG",
    "genero": "Mulher cisgênero", "profissao": "Engenheira", "medicamento": "Nenhum", "consentimento": "on",
}


def criar_psicologo(email, cpf, crp, nome="Psicóloga de Teste"):
    return Psicologo.objects.create_user(
        email=email, password=SENHA, nome_completo=nome, cpf=cpf,
        telefone="31988887777", crp_regiao="04", crp_numero=crp)


class Servicos(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.convite@exemplo.com", "11111111111", "818181")
        cls.bruno = criar_psicologo("bruno.convite@exemplo.com", "22222222222", "828282")

    def test_guarda_so_o_hash_e_vale_sete_dias(self):
        agora = timezone.now()
        with contexto.como(self.ana.pk):
            convite, token = convites.gerar_convite("Helena", agora=agora)
        self.assertGreaterEqual(len(token), 40)
        self.assertNotIn(token, str(ConviteDeCadastro.objetos_todos.filter(pk=convite.pk).values().get()))
        self.assertEqual(len(convite.token_hash), 64)
        self.assertEqual(convite.expira_em, agora + timedelta(days=7))
        self.assertEqual(convite.situacao, "aguardando")

    def test_apresentar_acha_pelo_token_e_so_por_ele(self):
        with contexto.como(self.ana.pk):
            convite, token = convites.gerar_convite()
        self.assertEqual(convites.apresentar(token).pk, convite.pk)
        self.assertIsNone(convites.apresentar(token + "x"))
        self.assertIsNone(convites.apresentar(convite.token_hash))  # o hash não serve de token

    def test_responde_uma_vez_so(self):
        with contexto.como(self.ana.pk):
            convite, _ = convites.gerar_convite()
        self.assertTrue(convites.responder(convite, RESPOSTAS))
        self.assertFalse(convites.responder(convite, {**RESPOSTAS, "nome": "Outra Pessoa"}))
        convite.refresh_from_db()
        self.assertEqual(convite.nome_informado, "Helena Prado")
        self.assertEqual(convite.situacao, "respondido")

    def test_vencido_nao_aceita_resposta(self):
        with contexto.como(self.ana.pk):
            convite, _ = convites.gerar_convite(agora=timezone.now() - timedelta(days=8))
        self.assertEqual(convite.situacao, "expirado")
        self.assertFalse(convites.responder(convite, RESPOSTAS))

    def test_iniciais_levam_os_campos_do_paciente_e_os_contatos(self):
        convite = ConviteDeCadastro(respostas=RESPOSTAS)
        iniciais = convites.iniciais_do_paciente(convite)
        self.assertEqual(iniciais["nome"], "Helena Prado")
        self.assertEqual(iniciais["emergencia1_nome"], "Rosa Prado")
        self.assertEqual(iniciais["emergencia1_telefone"], "31977776666")
        self.assertNotIn("contatos_de_emergencia", iniciais)
        self.assertNotIn("logradouro", iniciais)  # vazio não vira inicial

    def test_aceitar_cria_responsavel_e_pagador_e_esvazia_o_convite(self):
        respostas = {**RESPOSTAS, "nome": "Téo Prado", "menor": True, "cpf": "",
                     "responsavel": {"nome": "Rosa Prado", "parentesco": "mãe", "cpf": "", "telefone": "31977776666",
                                     "email": ""},
                     "pagador": {"nome": "Avô do Téo", "cpf": "52998224725"}}
        with contexto.como(self.ana.pk):
            convite, _ = convites.gerar_convite()
            convites.responder(convite, respostas)
            convite.refresh_from_db()
            paciente = Paciente(nome="Téo Prado", data_nascimento=date(2015, 3, 1))
            cadastrar_paciente(paciente)
            convites.aceitar(convite, paciente)
            responsavel = ResponsavelLegal.objects.get(paciente=paciente)
            caso = caso_individual_de(paciente)
        self.assertEqual((responsavel.nome, responsavel.parentesco), ("Rosa Prado", "mãe"))
        self.assertEqual((caso.pagador_nome, caso.pagador_cpf, caso.pagador_paciente), ("Avô do Téo", "52998224725", None))
        convite.refresh_from_db()
        self.assertEqual(convite.situacao, "cadastrado")
        self.assertEqual(convite.respostas, {})  # o dado passa a existir num lugar só
        self.assertEqual(convite.paciente_id, paciente.pk)
        with contexto.como(self.ana.pk), self.assertRaises(ValidationError):
            convites.aceitar(convite, paciente)

    def test_cancelar_apaga_a_resposta_mas_nao_o_que_ja_virou_cadastro(self):
        with contexto.como(self.ana.pk):
            convite, _ = convites.gerar_convite()
            convites.responder(convite, RESPOSTAS)
            convites.cancelar(convite)
            self.assertFalse(ConviteDeCadastro.objects.exists())
            aceito, _ = convites.gerar_convite()
            paciente = Paciente(nome="Helena Prado")
            cadastrar_paciente(paciente)
            convites.aceitar(aceito, paciente)
            with self.assertRaises(ValidationError):
                convites.cancelar(aceito)

    def test_cada_psicologo_ve_so_os_proprios_convites(self):
        with contexto.como(self.ana.pk):
            convite, _ = convites.gerar_convite()
            convites.responder(convite, RESPOSTAS)
        with contexto.como(self.bruno.pk):
            self.assertEqual(convites.convites(), [])
            self.assertEqual(convites.esperando_revisao(), 0)
        with contexto.como(self.ana.pk):
            self.assertEqual(convites.esperando_revisao(), 1)


class ContatosDeEmergencia(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.emergencia@exemplo.com", "11111111111", "838383")
        with contexto.como(cls.ana.pk):
            cls.helena = Paciente(nome="Helena Prado")
            cadastrar_paciente(cls.helena)

    def test_define_troca_e_nao_regrava_o_que_nao_mudou(self):
        rosa = {"nome": "Rosa Prado", "parentesco": "mãe", "telefone": "31977776666"}
        with contexto.como(self.ana.pk):
            definir_contatos_de_emergencia(self.helena, [rosa])
            primeiro = ContatoDeEmergencia.objects.get()
            definir_contatos_de_emergencia(self.helena, [rosa])
            self.assertEqual(ContatoDeEmergencia.objects.get().pk, primeiro.pk)  # igual: nem apagou nem recriou
            definir_contatos_de_emergencia(self.helena, [rosa, {"nome": "Ivo", "telefone": "31966665555"}])
            self.assertEqual([c.nome for c in self.helena.contatos_de_emergencia.all()], ["Rosa Prado", "Ivo"])
            definir_contatos_de_emergencia(self.helena, [])
            self.assertFalse(ContatoDeEmergencia.objects.exists())
        trilha = RegistroAuditoria.objetos_todos.filter(alvo="pacientes.contatodeemergencia", titular_id=self.helena.pk)
        self.assertEqual(trilha.filter(acao="CRIAR").count(), 3)


class ForaDoBrasil(TestCase):
    """ADR-082: o formato de telefone e de CEP é o do país; fora do Brasil, o estado se escreve à mão."""

    @classmethod
    def setUpTestData(cls):
        cls.ana = criar_psicologo("ana.exterior@exemplo.com", "11111111111", "878787")

    def test_no_brasil_valem_as_regras_de_sempre(self):
        with contexto.como(self.ana.pk):
            for campo, valor in [("telefone", "442079460958123"), ("cep", "SW1A 1AA"), ("telefone", "123")]:
                with self.subTest(campo=campo, valor=valor), self.assertRaises(ValidationError) as erro:
                    cadastrar_paciente(Paciente(nome="Daqui", **{campo: valor}))
                self.assertIn(campo, erro.exception.message_dict)

    def test_fora_do_brasil_aceita_o_formato_do_pais_e_guarda_o_estado_em_texto(self):
        with contexto.como(self.ana.pk):
            paciente = Paciente(nome="Emma Clarke", pais="Reino Unido", telefone="442079460958", cep="SW1A 1AA",
                                logradouro="Downing Street", numero="10", cidade="Londres",
                                estado_exterior="Inglaterra", uf="MG")
            cadastrar_paciente(paciente)
        paciente.refresh_from_db()
        self.assertEqual((paciente.cep, paciente.uf, paciente.estado_exterior), ("SW1A 1AA", "", "Inglaterra"))
        self.assertIn("Inglaterra", paciente.endereco)

    def test_pais_em_branco_conta_como_brasil_e_limpa_o_estado_de_fora(self):
        with contexto.como(self.ana.pk):
            paciente = Paciente(nome="Sem País", pais="", uf="MG", estado_exterior="Sobrou")
            cadastrar_paciente(paciente)
            with self.assertRaises(ValidationError):
                cadastrar_paciente(Paciente(nome="Outro", pais="", cep="SW1A 1AA"))
        self.assertEqual((paciente.uf, paciente.estado_exterior), ("MG", ""))

    def test_absurdo_continua_recusado_la_fora(self):
        with contexto.como(self.ana.pk):
            for campo, valor in [("telefone", "12345"), ("telefone", "1234567890123456"), ("cep", "codigo longo demais")]:
                with self.subTest(campo=campo, valor=valor), self.assertRaises(ValidationError):
                    cadastrar_paciente(Paciente(nome="De Fora", pais="Portugal", **{campo: valor}))


class NoBanco(TransactionTestCase):
    """A fresta de `hamilton_web` na tabela de convites — e só nela."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("RLS e grant por coluna exigem PostgreSQL.")
        self.ana = criar_psicologo("ana.convitebanco@exemplo.com", "33333333333", "848484")
        with contexto.como(self.ana.pk):
            self.convite, self.token = convites.gerar_convite()
            self.outro, _ = convites.gerar_convite()
            convites.responder(self.outro, RESPOSTAS)
            cadastrar_paciente(Paciente(nome="Paciente Clínico"))

    def consultar(self, sql, *, token_hash=None):
        with transaction.atomic():
            db.assumir_papel_da_web()
            if token_hash:
                db.aplicar_convite(token_hash)
            with connection.cursor() as cursor:
                cursor.execute(sql)
                return cursor.fetchall() if cursor.description else cursor.rowcount

    def test_sem_apresentar_token_o_visitante_nao_ve_convite_nenhum(self):
        self.assertEqual(self.consultar("SELECT id FROM pacientes_convitedecadastro"), [])

    def test_com_o_token_ve_so_aquela_linha(self):
        linhas = self.consultar("SELECT id FROM pacientes_convitedecadastro", token_hash=self.convite.token_hash)
        self.assertEqual(linhas, [(self.convite.pk,)])

    def test_nao_responde_de_novo_nem_responde_o_convite_dos_outros(self):
        sql = "UPDATE pacientes_convitedecadastro SET respostas = '{\"nome\": \"Intruso\"}'"
        self.assertEqual(self.consultar(sql, token_hash=self.outro.token_hash), 0)  # já respondido
        self.assertEqual(self.consultar(sql, token_hash=self.convite.token_hash), 1)  # só o dele
        self.outro.refresh_from_db()
        self.assertEqual(self.outro.nome_informado, "Helena Prado")

    def test_nao_troca_dono_prazo_nem_paciente(self):
        for coluna, valor in [("psicologo_id", "1"), ("expira_em", "now() + interval '10 years'"),
                              ("token_hash", "'x'"), ("aceito_em", "now()")]:
            with self.subTest(coluna=coluna), self.assertRaises(ProgrammingError):
                self.consultar(f"UPDATE pacientes_convitedecadastro SET {coluna} = {valor}",
                               token_hash=self.convite.token_hash)

    def test_nao_alcanca_tabela_clinica_nem_cria_ou_apaga_convite(self):
        for sql in ["SELECT 1 FROM pacientes_paciente", "SELECT 1 FROM pacientes_contatodeemergencia",
                    "DELETE FROM pacientes_convitedecadastro",
                    "INSERT INTO pacientes_convitedecadastro (token_hash) VALUES ('x')"]:
            with self.subTest(sql=sql), self.assertRaises(ProgrammingError):
                self.consultar(sql, token_hash=self.convite.token_hash)


class BaseTelas(TransactionTestCase):
    def setUp(self):
        self.ana = criar_psicologo("ana.telaconvite@exemplo.com", "11111111111", "858585", nome="Ana Convida")
        self.bruno = criar_psicologo("bruno.telaconvite@exemplo.com", "22222222222", "868686")
        with contexto.como(self.ana.pk):
            self.convite, self.token = convites.gerar_convite("Helena")

    def entrar(self, quem):
        self.assertTrue(self.client.login(username=quem.email, password=SENHA))

    def link(self, token=None):
        return reverse("cadastro_pelo_paciente", args=[token or self.token])


class TelaPublica(BaseTelas):
    def test_abre_sem_login_diz_quem_convidou_e_protege_o_token(self):
        resposta = self.client.get(self.link())
        self.assertContains(resposta, "Ana Convida")
        self.assertContains(resposta, "Aviso de privacidade")
        self.assertEqual(resposta["Referrer-Policy"], "no-referrer")
        self.assertEqual(resposta["Cache-Control"], "no-store")
        self.assertIn("noindex", resposta["X-Robots-Tag"])

    def test_enviar_guarda_a_resposta_sem_criar_paciente_e_mata_o_link(self):
        resposta = self.client.post(self.link(), FORMULARIO)
        self.assertContains(resposta, "Cadastro enviado")
        self.convite.refresh_from_db()
        self.assertEqual(self.convite.respostas["cpf"], "11144477735")  # sem máscara, como o cadastro guarda
        self.assertEqual(self.convite.respostas["contatos_de_emergencia"][0]["telefone"], "31977776666")
        self.assertIn("consentimento_em", self.convite.respostas)
        self.assertFalse(Paciente.objetos_todos.filter(nome="Helena Prado").exists())
        self.assertContains(self.client.get(self.link()), "já foi enviado")
        self.assertContains(self.client.post(self.link(), {**FORMULARIO, "nome": "Outra"}), "já foi enviado")
        self.convite.refresh_from_db()
        self.assertEqual(self.convite.nome_informado, "Helena Prado")

    def test_exige_o_minimo_e_o_consentimento(self):
        resposta = self.client.post(self.link(), {"nome": "Helena Prado"})
        for campo in ["data_nascimento", "telefone", "emergencia1_nome", "emergencia1_telefone", "consentimento",
                      "cep", "logradouro", "numero", "bairro", "cidade", "uf"]:
            with self.subTest(campo=campo):
                self.assertIn(campo, resposta.context["form"].errors)
        self.convite.refresh_from_db()
        self.assertIsNone(self.convite.respondido_em)

    def test_crianca_pede_responsavel_e_dispensa_o_telefone_dela(self):
        crianca = {**FORMULARIO, "nome": "Téo Prado", "data_nascimento": "2016-03-01", "telefone": "", "cpf": ""}
        erros = self.client.post(self.link(), crianca).context["form"].errors
        self.assertIn("menor", erros)  # menor de 18 sem marcar a opção
        erros = self.client.post(self.link(), {**crianca, "menor": "on"}).context["form"].errors
        self.assertEqual(set(erros), {"resp_nome", "resp_telefone"})
        resposta = self.client.post(self.link(), {**crianca, "menor": "on", "resp_nome": "Rosa Prado",
                                                  "resp_parentesco": "mãe", "resp_telefone": "(31) 97777-6666"})
        self.assertContains(resposta, "Cadastro enviado")
        self.convite.refresh_from_db()
        self.assertEqual(self.convite.respostas["responsavel"]["nome"], "Rosa Prado")

    def test_adulto_marcado_como_crianca_e_recusado(self):
        erros = self.client.post(self.link(), {**FORMULARIO, "menor": "on"}).context["form"].errors
        self.assertIn("menor", erros)

    def test_endereco_e_obrigatorio_mas_fora_do_brasil_nao_pede_cep_bairro_nem_estado(self):
        sem_rua = {**FORMULARIO, "logradouro": "", "uf": ""}
        self.assertEqual(set(self.client.post(self.link(), sem_rua).context["form"].errors), {"logradouro", "uf"})
        de_fora = {**FORMULARIO, "pais": "Portugal", "cep": "", "bairro": "", "uf": "", "cidade": "Lisboa"}
        self.assertContains(self.client.post(self.link(), de_fora), "Cadastro enviado")

    def test_de_fora_do_brasil_escreve_tudo_a_mao_e_o_cadastro_chega_inteiro_ao_psicologo(self):
        de_fora = {**FORMULARIO, "documento_tipo": "ESTRANGEIRO", "documento_estrangeiro": "GB123456",
                   "pais": "Reino Unido", "telefone": "+44 20 7946 0958", "emergencia1_telefone": "+44 20 7946 0000",
                   "cep": "SW1A 1AA", "logradouro": "Downing Street", "numero": "10", "bairro": "",
                   "cidade": "Londres", "uf": "MG", "estado_exterior": "Inglaterra"}
        self.assertContains(self.client.post(self.link(), de_fora), "Cadastro enviado")
        self.convite.refresh_from_db()
        respostas = self.convite.respostas
        self.assertEqual((respostas["cep"], respostas["telefone"], respostas["uf"], respostas["estado_exterior"]),
                         ("SW1A 1AA", "442079460958", "", "Inglaterra"))  # o CEP de fora guarda as letras

        self.assertTrue(self.client.login(username=self.ana.email, password=SENHA))
        revisar = reverse("pacientes:novo") + f"?convite={self.convite.pk}"
        iniciais = self.client.get(revisar).context["form"].initial
        self.client.post(revisar, dict(iniciais))
        emma = Paciente.objetos_todos.get(nome="Helena Prado")
        self.assertEqual((emma.pais, emma.cep, emma.telefone, emma.estado_exterior, emma.uf),
                         ("Reino Unido", "SW1A 1AA", "442079460958", "Inglaterra", ""))
        with contexto.como(self.ana.pk):
            self.assertEqual(emma.contatos_de_emergencia.get().telefone, "442079460000")

    def test_no_brasil_telefone_e_cep_seguem_o_formato_brasileiro(self):
        erros = self.client.post(self.link(), {**FORMULARIO, "telefone": "+44 20 7946 0958 123",
                                               "cep": "SW1A 1AA"}).context["form"].errors
        self.assertEqual(set(erros), {"telefone", "cep"})

    def test_estrangeiro_informa_documento_e_nao_cpf(self):
        self.client.post(self.link(), {**FORMULARIO, "documento_tipo": "ESTRANGEIRO",
                                       "documento_estrangeiro": "AB123456", "pais": "Portugal", "cep": "1000-001"})
        self.convite.refresh_from_db()
        self.assertEqual((self.convite.respostas["cpf"], self.convite.respostas["documento_estrangeiro"]),
                         ("", "AB123456"))

    def test_link_inexistente_vencido_e_cancelado(self):
        self.assertEqual(self.client.get(self.link("token-que-nao-existe")).status_code, 404)
        ConviteDeCadastro.objetos_todos.filter(pk=self.convite.pk).update(expira_em=timezone.now() - timedelta(hours=1))
        resposta = self.client.post(self.link(), FORMULARIO)
        self.assertEqual(resposta.status_code, 410)
        self.convite.refresh_from_db()
        self.assertIsNone(self.convite.respondido_em)
        with contexto.como(self.ana.pk):
            convites.cancelar(self.convite)
        self.assertEqual(self.client.get(self.link()).status_code, 404)


class TelasDoPsicologo(BaseTelas):
    def test_exigem_login(self):
        for rota in [reverse("pacientes:convites"), reverse("pacientes:convite_gerar"),
                     reverse("pacientes:convite_cancelar", args=[self.convite.pk])]:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.post(rota).status_code, 302)

    def test_gerar_mostra_o_link_uma_vez_so(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("pacientes:convite_gerar"), {"rotulo": "Mariana"}, follow=True)
        self.assertContains(resposta, "/cadastro/")
        self.assertContains(resposta, "wa.me")
        self.assertContains(resposta, "Mariana")
        self.assertNotContains(self.client.get(reverse("pacientes:convites")), 'id="link-do-convite"')

    def test_o_link_gerado_pela_tela_funciona_para_o_visitante(self):
        self.entrar(self.ana)
        resposta = self.client.post(reverse("pacientes:convite_gerar"), follow=True)
        link = resposta.context["link"]
        self.client.logout()
        self.assertContains(self.client.get(link[link.index("/cadastro/"):]), "Ana Convida")

    def test_revisar_traz_as_respostas_e_salvar_cadastra_tudo(self):
        self.client.post(self.link(), {**FORMULARIO, "pagador_outro": "on", "pagador_nome": "Rosa Prado"})
        self.entrar(self.ana)
        self.assertContains(self.client.get(reverse("pacientes:lista")), "Link de cadastro")
        self.assertContains(self.client.get(reverse("pacientes:convites")), "Respondido — revisar")
        revisar = reverse("pacientes:novo") + f"?convite={self.convite.pk}"
        resposta = self.client.get(revisar)
        self.assertContains(resposta, "Revisão do cadastro enviado pelo paciente")
        self.assertContains(resposta, 'value="Helena Prado"')
        self.assertContains(resposta, 'value="Rosa Prado"')
        iniciais = resposta.context["form"].initial
        dados = {**{campo: valor for campo, valor in iniciais.items() if valor is not None},
                 "modalidade": "ONLINE", "cobranca-modalidade": "POR_SESSAO", "cobranca-valor": "180,00"}
        resposta = self.client.post(revisar, dados)
        helena = Paciente.objetos_todos.get(nome="Helena Prado")
        self.assertRedirects(resposta, reverse("pacientes:detalhe", args=[helena.pk]), fetch_redirect_response=False)
        self.assertEqual((helena.nome_social, helena.raca_cor, helena.profissao, helena.modalidade),
                         ("Lena", "PARDA", "Engenheira", "ONLINE"))
        with contexto.como(self.ana.pk):
            self.assertEqual([c.nome for c in helena.contatos_de_emergencia.all()], ["Rosa Prado"])
            self.assertEqual(caso_individual_de(helena).pagador_nome, "Rosa Prado")
        self.convite.refresh_from_db()
        self.assertEqual((self.convite.situacao, self.convite.respostas), ("cadastrado", {}))
        self.assertContains(self.client.get(reverse("pacientes:detalhe", args=[helena.pk])), "Rosa Prado")
        self.assertEqual(self.client.get(revisar).status_code, 404)  # já virou cadastro

    def test_cpf_de_quem_ja_e_paciente_vira_erro_no_campo_e_nao_erro_de_servidor(self):
        with contexto.como(self.ana.pk):
            cadastrar_paciente(Paciente(nome="Helena Antiga", cpf="11144477735"))
        self.client.post(self.link(), FORMULARIO)
        self.entrar(self.ana)
        revisar = reverse("pacientes:novo") + f"?convite={self.convite.pk}"
        iniciais = self.client.get(revisar).context["form"].initial
        resposta = self.client.post(revisar, dict(iniciais))
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Helena Antiga", resposta.context["form"].errors["cpf"][0])
        self.convite.refresh_from_db()
        self.assertEqual(self.convite.situacao, "respondido")

    def test_outro_psicologo_nao_ve_nao_revisa_nem_cancela(self):
        self.client.post(self.link(), FORMULARIO)
        self.entrar(self.bruno)
        self.assertNotContains(self.client.get(reverse("pacientes:convites")), "Helena")
        self.assertEqual(self.client.get(reverse("pacientes:novo") + f"?convite={self.convite.pk}").status_code, 404)
        self.assertEqual(self.client.post(reverse("pacientes:convite_cancelar", args=[self.convite.pk])).status_code, 404)
        self.assertTrue(ConviteDeCadastro.objetos_todos.filter(pk=self.convite.pk).exists())

    def test_cancelar_apaga_o_link_e_a_resposta(self):
        self.client.post(self.link(), FORMULARIO)
        self.entrar(self.ana)
        self.client.post(reverse("pacientes:convite_cancelar", args=[self.convite.pk]))
        self.assertFalse(ConviteDeCadastro.objetos_todos.filter(pk=self.convite.pk).exists())

    def test_editar_o_paciente_mantem_e_troca_os_contatos_de_emergencia(self):
        with contexto.como(self.ana.pk):
            helena = Paciente(nome="Helena Prado")
            cadastrar_paciente(helena)
            definir_contatos_de_emergencia(helena, [{"nome": "Rosa Prado", "parentesco": "mãe",
                                                     "telefone": "31977776666"}])
        self.entrar(self.ana)
        editar = reverse("pacientes:editar", args=[helena.pk])
        self.assertContains(self.client.get(editar), 'value="Rosa Prado"')
        self.client.post(editar, {"nome": "Helena Prado", "pais": "Brasil", "emergencia1_nome": "Ivo Prado",
                                  "emergencia1_telefone": "(31) 96666-5555"})
        with contexto.como(self.ana.pk):
            self.assertEqual([(c.nome, c.telefone) for c in helena.contatos_de_emergencia.all()],
                             [("Ivo Prado", "31966665555")])
