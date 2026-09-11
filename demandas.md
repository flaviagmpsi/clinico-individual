# Demandas — Hamilton Individual

Documento vivo. User Stories derivadas das decisões em [complicacoes.md](complicacoes.md).
Cada história é rastreável até a ADR que a originou — se a ADR mudar, a história muda.

**Camada:** 🎨 Front · ⚙️ Back · 🗄️ BD · 🔒 Segurança/Compliance

⚠️ **Leia a legenda antes de confiar nas tabelas.** São duas colunas de estado, e confundi-las
é o erro mais caro que se pode cometer aqui:

| Coluna | O que significa |
|---|---|
| **Estado** | Quanto a história está **decidida**. `✅` = especificada, com ADR fechada. **Não quer dizer que exista código.** · `🟡` = depende de decisão aberta · `⏸️` fora do MVP · `❌` fora de escopo |
| **Código** | O que existe **rodando**. `🟢` no ar · `🟠` parcial · `⚪` não começado |

A esmagadora maioria das linhas está `✅ / ⚪`: **decidida e não construída**. O planejamento
correu 27 rodadas antes da primeira linha de código, de propósito.

---

## ⚡ Onde o código está hoje

**Passos 0 e 1 concluídos.** Rodando, com 54 testes verdes contra PostgreSQL real.

| App | Situação | O que existe |
|---|---|---|
| `core` | 🟢 no ar | Isolamento em três camadas, três papéis de banco, middleware, painel |
| `contas` | 🟠 parcial | Model do psicólogo, login, logout, tela de perfil |
| `pacientes` | 🟠 parcial | Cadastro completo com lista, busca, ficha, edição e exclusão |
| `agenda` `atendimentos` `prontuarios` `documentos` `financeiro` `assinaturas` `indicadores` | ⚪ | **Nem o app existe.** Nenhum `startapp` foi rodado |

**O próximo passo é o 2: `agenda` + `atendimentos`.** A consulta é a âncora de tudo o mais —
o prontuário pende dela (ADR-016) e a cobrança também (ADR-023). Nada depois do passo 2 deve
começar antes dele.

### Antes de escrever a primeira linha, entenda a fundação

Não é opcional, e não dá para contornar: **toda model nova precisa herdar `TenantOwnedModel` e
ganhar sua própria migração de RLS.** Se você criar um model sem isso, ele não vai ter dono e o
Postgres vai recusar o acesso — barulhento, do lado certo do erro, mas você vai perder uma tarde
se não souber o porquê. Leia, nesta ordem:

1. [README.md](README.md) — os três papéis de banco e como subir local.
2. `core/models.py`, `core/managers.py`, `core/middleware.py` — as três camadas, ~120 linhas.
3. `core/tests/test_seguranca.py` — o que já tentaram atravessar e não conseguiram.
4. ADR-001, ADR-045, ADR-046 e ADR-047 em [complicacoes.md](complicacoes.md) — o porquê de tudo isso.

### Receita para um model novo

```python
# 1. Herde de TenantOwnedModel — nunca de models.Model
class Consulta(TenantOwnedModel):
    ...

# 2. Gere a migração normal
python manage.py makemigrations atendimentos

# 3. Crie a migração de RLS SEPARADA (o diff precisa mostrar quando ela faltar)
#    Copie pacientes/migrations/0002_rls.py e troque o nome da tabela.
```

Esqueceu o passo 3? O model funciona nos testes e **não** fica protegido por RLS. Só a camada
Python o cobre. É exatamente o buraco que a auditoria da ADR-046 achou em `contas_psicologo`.

---

## 0. Fundação — app `core`

> Como **plataforma**, preciso garantir que nenhum psicólogo alcance dado de outro,
> **em nenhuma hipótese** — porque o dado é prontuário, sob sigilo profissional e LGPD art. 11.

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| F-01 | Toda model de domínio herda `TenantOwnedModel`, com o dono explícito | 🗄️ | ✅ **feito** | 🟢 | ADR-001 |
| F-02 | `TenantManager` é o manager padrão e **levanta exceção** se a query rodar sem escopo de dono | ⚙️🔒 | ✅ **feito** | 🟢 | ADR-001 |
| F-03 | Middleware abre transação, desce para `hamilton_app` e define o escopo. `SET LOCAL` morre com a transação | ⚙️🔒 | ✅ **feito** | 🟢 | ADR-001, ADR-045 |
| F-04 | RLS com `FORCE ROW LEVEL SECURITY` e papel de aplicação **sem `BYPASSRLS`** | 🗄️🔒 | ✅ **feito** | 🟢 | ADR-001, ADR-045 |
| F-05 | Trilha de auditoria: quem escreveu, quando, o que mudou | ⚙️🔒 | ✅ | ⚪ | ADR-005 |
| F-06 | Teste que **prova** o isolamento nas três camadas — **13 testes, todos passando** | ⚙️🔒 | ✅ **feito** | 🟢 | ADR-001, ADR-045 |

✅ **Passo 0 concluído**, e depois **auditado** (ADR-046, ADR-047). A prova de conceito rodou
contra Postgres real e encontrou o que o planejamento não pegaria: o papel dono do Neon tem
`BYPASSRLS` e ignorava a policy em silêncio (ADR-045).

Uma segunda bateria, escrita de propósito para *atravessar* a fronteira, achou mais quatro furos
— e todos tinham a mesma raiz, a aplicação continuar conectada como dono:

- A requisição **anônima** nunca descia de papel: login e healthcheck liam o banco inteiro.
- `RESET ROLE` desfazia o rebaixamento numa palavra.
- `contas_psicologo` não tinha policy: CPF e **hash de senha** de todos os assinantes, num SELECT.
- `django_session` idem — ler a tabela é se passar por qualquer psicólogo logado.

Resolvido pela ADR-046 (três papéis, `hamilton_web` como papel de conexão, `NOINHERIT`).
**54 testes verdes**, dos quais 21 existem só para tentar vazar e falhar.

⚠️ **F-05 (trilha de auditoria) não foi construída.** É pré-requisito do prontuário (ADR-005:
o prontuário é meio de prova em processo disciplinar, e precisa saber quem escreveu o quê e
quando). Ela tem de existir **antes** do passo 3, não depois.

---

## 1. Conta e perfil — app `contas`
**Código: 🟠 parcial.** No ar: model do psicólogo (é o `AUTH_USER_MODEL`), login por e-mail,
logout e tela de perfil editável. Falta: **cadastro de novo psicólogo** (C-01 só tem a metade do
login — criar conta depende do ciclo de assinatura, passo 7), recuperação de senha, e os padrões
de C-03/C-04/C-05, que só fazem sentido quando existir consulta e cobrança para herdá-los.


> Como **psicólogo**, quero configurar meus padrões uma vez e não responder a mesma pergunta a cada cadastro.

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| C-01 | Cadastro e login; a conta é a raiz do isolamento | 🎨⚙️ | ✅ | 🟢 | ADR-001 |
| C-02 | Perfil: nome completo, CPF, **CRP (região + número)**, telefone, e-mail, regime PF/PJ e **CNPJ se PJ** | 🎨🗄️ | ✅ | 🟢 | ADR-044 |
| C-06 | **Sem CRP não há cadastro.** O registro é condição de entrada | 🎨⚙️ | ✅ | 🟢 | ADR-044 |
| C-07 | Validação de **formato** do CRP. **Sem** consulta ao cadastro do CFP | ⚙️ | ✅ | 🟢 | ADR-044 |
| C-08 | Campos vazios para `situacao_registro` e `verificado_em`, prontos caso a verificação volte | 🗄️ | ✅ | 🟢 | ADR-044 |
| C-09 | CRP da empresa (PJ): campo **opcional** | 🎨🗄️ | ✅ | 🟢 | ADR-044 |
| C-03 | Padrões do psicólogo: duração da sessão (50 min), vencimento da mensalidade, cobro falta (sim/não) | 🎨🗄️ | ✅ | ⚪ | ADR-025 |
| C-04 | Toda tela de cadastro mostra **de onde veio** o valor herdado do perfil | 🎨 | ✅ | ⚪ | ADR-025 |
| C-05 | Dados fiscais **opcionais** (outras rendas, INSS, dependentes, pensão), fora do onboarding | 🎨 | ✅ | ⚪ | ADR-012 |

---

## 2. Pacientes e casos — app `pacientes`
**Código: 🟠 parcial.** No ar: o **cadastro da pessoa** (P-01, P-09) com lista, busca, ficha,
edição e exclusão. Falta tudo que é **vínculo**: `Caso`, `Pagador` e `ResponsavelLegal` (P-02 a
P-07) não existem como model. Eles são o passo 2 junto com a agenda, porque o valor acordado e a
recorrência moram no `Caso`, não no paciente.

⚠️ A exclusão de paciente hoje é **definitiva**. A partir do prontuário isso vira arquivamento:
guarda mínima de 5 anos (ADR-005) e o `CASCADE` levaria o prontuário junto. Ver **P-70**.


> Como **psicólogo**, quero cadastrar quem eu atendo sem preencher campo que não uso.

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| P-01 | Cadastro de paciente: nome, CPF, telefone, e-mail, endereço com CEP, nascimento, medicamento em uso | 🎨🗄️ | ✅ | 🟢 | escopo |
| P-02 | `Caso` criado **em silêncio** ao cadastrar paciente individual; a palavra não aparece na tela | ⚙️🗄️ | ✅ | ⚪ | ADR-026 |
| P-03 | Atendimento de casal ou família: um `Caso` com N pacientes | 🎨⚙️🗄️ | ✅ | ⚪ | ADR-026 |
| P-04 | A **pessoa é única** entre atendimentos: mesmo cadastro em terapia individual e de casal | 🗄️ | ✅ | ⚪ | ADR-026 |
| P-05 | **Pagador** separado do paciente, com o CPF do paciente como padrão; segundo campo só ao marcar "quem paga é outra pessoa" | 🎨🗄️ | ✅ | ⚪ | ADR-009 |
| P-06 | **Responsável legal** (1..N) com tipo de guarda registrado | 🎨🗄️ | ✅ | ⚪ | ADR-014 |
| P-07 | Valor acordado e modalidade de cobrança pertencem ao **caso**, não ao paciente | 🗄️ | ✅ | ⚪ | ADR-002, ADR-026 |
| P-08 | Acesso direto, do cadastro, aos prontuários já realizados e à contagem de sessões | 🎨 | ✅ | ⚪ | escopo |
| P-09 | Paciente nascido antes de 2018 pode não ter CPF: avisar, não bloquear | 🎨 | ✅ | 🟢 | ADR-040 |

---

## 3. Agenda — app `agenda`
**Código: ⚪ nada. O app não existe** — nenhum `startapp agenda` foi rodado. **É o próximo passo.**


> Como **psicólogo**, meu atendimento é fixo quase sempre, mas vez ou outra remarca.

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| A-01 | Recorrência por caso: dia, hora e **periodicidade** (semanal, quinzenal, mensal), com âncora | 🎨🗄️ | ✅ | ⚪ | ADR-022, ADR-031 |
| A-02 | Consultas materializadas em janela contínua à frente, empurrada ao abrir a agenda | ⚙️ | ✅ | ⚪ | ADR-022 |
| A-03 | Remarcação avulsa: altera **só aquela** ocorrência; a regra não é tocada | 🎨⚙️ | ✅ | ⚪ | ADR-022 |
| A-04 | A ocorrência remarcada **lembra que foi alterada à mão** e não é sobrescrita por mudança futura na regra | 🗄️ | ✅ | ⚪ | ADR-022 |
| A-05 | Alterar a regra oferece **"só esta"** e **"esta e as próximas"**. "Todas" não existe | 🎨 | ✅ | ⚪ | ADR-022 |
| A-06 | Consulta tem data, **hora e duração** (o original só tem data) | 🗄️ | ✅ | ⚪ | ADR-023 |
| A-07 | Colisão de horário **bloqueia** a marcação | ⚙️ | ✅ | ⚪ | ADR-024 |
| A-08 | Casal não dispara colisão: é uma consulta com dois participantes | ⚙️ | ✅ | ⚪ | ADR-026 |
| A-09 | Grade de horários declarada pelo psicólogo, com ocupação **derivada** — sem manutenção dupla | 🎨⚙️ | ✅ | ⚪ | ADR-029 |
| A-10 | Tela de horários como mapa da semana: o que está ocupado, por quem, e o que sobrou | 🎨 | ✅ | ⚪ | ADR-029 |
| A-11 | Férias, feriados e pausas em bloco | — | ⏸️ | ⚪ | P-47 |

### Integração com Google Agenda

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| A-12 | OAuth com **leitura** na conexão; **escrita** pedida só ao ativar o recurso, com explicação na tela | 🎨⚙️ | ✅ | ⚪ | ADR-020 |
| A-13 | Consulta vira evento em calendário **dedicado** ("Hamilton — Atendimentos"), nunca no pessoal dele | ⚙️ | ✅ | ⚪ | ADR-020 |
| A-14 | Leitura da agenda para evitar marcação sobreposta | ⚙️ | ✅ | ⚪ | ADR-020 |
| A-15 | Evento movido no Google é **detectado** e o sistema oferece atualizar aqui | 🎨⚙️ | ✅ | ⚪ | ADR-020 |
| A-16 | Ensinar o psicólogo a ligar o "Resumo diário" do Google — é ele que faz o alerta matinal | 🎨 | ✅ | ⚪ | ADR-018 |

---

## 4. Atendimentos — app `atendimentos`
**Código: ⚪ nada. O app não existe.** Passo 2, junto com `agenda`.


| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| T-01 | Consulta com estado: `AGENDADA`, `REALIZADA`, `FALTA`, `CANCELADA` | 🗄️ | ✅ | ⚪ | ADR-022 |
| T-02 | Campo `contabilizada`, **independente** do estado, com padrão vindo do perfil | 🎨🗄️ | ✅ | ⚪ | ADR-023 |
| T-03 | Presença registrada **por participante** — num casal, um pode faltar e o outro não | 🗄️ | ✅ | ⚪ | ADR-026 |
| T-04 | `REALIZADA` dispara **prontuário pendente**; `contabilizada` dispara **conta a receber** | ⚙️ | ✅ | ⚪ | ADR-016, ADR-023 |
| T-05 | Desfecho (alta ou desistência), com o número de sessões derivado, não perguntado | ⚙️🗄️ | ✅ | ⚪ | ADR-027 |

---

## 5. Prontuários — app `prontuarios`
**Código: ⚪ nada. O app não existe.** Passo 3 — e depende de F-05 (trilha de auditoria), que
também não existe.


> Como **psicólogo**, quero recuperar os ~20 minutos que gasto escrevendo prontuário depois de cada sessão.

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| R-01 | Relato de origem em **áudio ditado** ou **texto escrito** — duas portas para o mesmo pipeline. O texto **não** passa por transcrição | 🎨⚙️ | ✅ | ⚪ | ADR-006, ADR-042 |
| R-02 | A sessão **nunca** é gravada; o único falante é o psicólogo | 🔒 | ✅ | ⚪ | ADR-006 |
| R-03 | IA estrutura o relato no formato do Art. 2º da Res. CFP 001/2009 | ⚙️ | ✅ | ⚪ | ADR-005 |
| R-04 | **Rascunho obrigatório**: revisão e confirmação explícita antes de virar registro oficial | 🎨 | ✅ | ⚪ | ADR-005 |
| R-05 | Versão congelada na confirmação, com trilha de auditoria — é meio de prova em processo disciplinar | ⚙️🔒 | ✅ | ⚪ | ADR-005 |
| R-06 | Sessão de casal: **um relato gravado por participante**; `Relato` é 1:1 com `Prontuario` | 🎨⚙️ | ✅ | ⚪ | ADR-041 |
| R-07 | Risco de migração da fala entre prontuários: **eliminado por construção** | 🔒 | ✅ | ⚪ | ADR-041 |
| R-08 | Exportação de uma sessão ou do histórico completo, em PDF ou DOC | 🎨⚙️ | ✅ | ⚪ | escopo |
| R-09 | IA atrás de **adaptador**: o domínio não conhece provedor, modelo nem chave | ⚙️ | ✅ | ⚪ | §3.2 |
| R-10 | **No caminho do áudio:** áudio → transcrição → prontuário. O áudio é apagado assim que transcrito | ⚙️🔒 | ✅ | ⚪ | ADR-042 |
| R-14 | A **transcrição permanece** ligada ao prontuário, como insumo e prova de autoria | 🗄️🔒 | ✅ | ⚪ | ADR-042 |
| R-11 | Direito de acesso do paciente: obrigação **do psicólogo**, exercida fora do sistema | — | ❌ Fora | ⚪ | ADR-039 |
| R-12 | Acesso do responsável legal: decidido pelo psicólogo, fora do sistema | — | ❌ Fora | ⚪ | ADR-039 |
| R-13 | Sigilo do adolescente perante os pais: decisão clínica do psicólogo, não do software | — | ❌ Fora | ⚪ | ADR-039 |

---

## 6. Documentos — app `documentos`
**Código: ⚪ nada. O app não existe.** Passo 5.


| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| D-01 | `Documento` com arquivo, tipo, vigência, visibilidade e versões | 🗄️ | ✅ | ⚪ | ADR-021 |
| D-02 | Guarda do **contrato terapêutico** escrito pelo psicólogo, para conferência | 🎨⚙️ | ✅ | ⚪ | ADR-015 |
| D-03 | Alterar **cria versão**; apagar move para **lixeira**; exclusão definitiva só de dentro dela | 🎨⚙️ | ✅ | ⚪ | ADR-015 |
| D-04 | Anexos de avaliação psicológica em **pasta de acesso exclusivo do psicólogo** (inciso V) | 🗄️🔒 | ✅ | ⚪ | ADR-021 |
| D-05 | Cópias de documentos emitidos, com data, finalidade e destinatário (inciso VI) | 🗄️ | ✅ | ⚪ | ADR-021 |
| D-06 | **IA gera Declaração** — sem acesso ao prontuário, proibida de citar sintomas | ⚙️🔒 | ✅ | ⚪ | ADR-032, ADR-034 |
| D-07 | **IA gera Relatório Psicológico** — 5 itens: identificação, demanda, procedimento, análise, conclusão | ⚙️ | ✅ | ⚪ | ADR-032 |
| D-08 | Prazo de validade do conteúdo no **último parágrafo** (Art. 17) | ⚙️ | ✅ | ⚪ | ADR-032 |
| D-09 | Rascunho obrigatório também para documentos gerados | 🎨 | ✅ | ⚪ | ADR-034 |
| D-10 | Diretrizes do CFP consultáveis, com data da versão visível | 🎨 | ✅ | ⚪ | ADR-033 |
| D-11 | Atestado e Laudo | — | ⏸️ | ⚪ | ADR-034 |
| D-12 | Parecer Psicológico | — | ⏸️ | ⚪ | ADR-034 |
| D-13 | Relatório Multiprofissional | — | ❌ Fora | ⚪ | ADR-034 |

---

## 7. Financeiro — app `financeiro`
**Código: ⚪ nada. O app não existe.** Passo 4 — depende de consulta contabilizada (ADR-023).


| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| N-01 | Modalidade por caso: `MENSAL` (uma cobrança, vencimento no início ou no fim) ou `POR_SESSAO` | 🎨🗄️ | ✅ | ⚪ | ADR-002 |
| N-02 | `POR_SESSAO` gera cobrança **por consulta contabilizada**, cobrada logo após | ⚙️ | ✅ | ⚪ | ADR-002, ADR-023 |
| N-03 | Registros permanecem **granulares**; o agrupamento por paciente existe só na apresentação | ⚙️🎨 | ✅ | ⚪ | ADR-002 |
| N-04 | Registro de pagamento: paciente, quem pagou, valor, data e observação. Sem campo de terapeuta | 🎨🗄️ | ✅ | ⚪ | ADR-035 |
| N-04a | Pagamento **dá baixa** numa cobrança, com **baixa parcial** permitida e saldo remanescente visível | ⚙️ | ✅ | ⚪ | ADR-035 |
| N-04b | **Forma de pagamento** opcional: PIX, dinheiro, transferência, cartão | 🎨🗄️ | ✅ | ⚪ | ADR-035 |
| N-04c | Listagem com busca, filtro por mês e ordenação, portadas do original | 🎨 | ✅ | ⚪ | ADR-035 |
| N-05 | Despesas com **catálogo de tipos** e marca de dedutibilidade | 🎨🗄️ | ✅ | ⚪ | ADR-011 |
| N-06 | Anexo de comprovante na despesa, **opcional** | 🎨⚙️ | ✅ | ⚪ | ADR-040 |
| N-12 | Pagamento sem cobrança vira **crédito do caso**, que quita as próximas automaticamente | ⚙️ | ✅ | ⚪ | ADR-040 |
| N-07 | **Faturamento líquido** = receita − despesas. Independe de regime | ⚙️ | ✅ | ⚪ | ADR-013 |
| N-08 | Lembrete de cobrança: quem deve, quanto e até quando | 🎨⚙️ | ✅ | ⚪ | ADR-017 |
| N-09 | Lembrete fiscal ciente do regime: PF → Receita Saúde; PJ → nota fiscal | 🎨 | ✅ | ⚪ | ADR-030 |
| N-10 | Carnê-leão (CSV do Receita Saúde) e NFS-e por API | — | ⏸️ | ⚪ | ADR-013 |
| N-11 | Previsão de imposto | — | ⏸️ | ⚪ | P-30 |

---

## 8. Assinatura — app `assinaturas`
**Código: ⚪ nada. O app não existe.** Passo 7.


| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| S-01 | Assinatura via Asaas: **cartão de crédito e PIX Automático**. Sem boleto | ⚙️ | ✅ | ⚪ | ADR-036 |
| S-01a | Acesso liberado em `PAYMENT_CONFIRMED`, nunca em `PAYMENT_RECEIVED` — no cartão há 32 dias entre os dois | ⚙️ | ✅ | ⚪ | I-06 |
| S-01b | Webhook do Asaas como mecanismo de sincronização; sem consulta em laço | ⚙️ | ✅ | ⚪ | §3.5 |
| S-02 | No cancelamento, **exportação automática** do pacote completo, avisos repetidos e descarte após carência | ⚙️🔒 | 🟡 | ⚪ | ADR-007, P-20 |
| S-03 | `assinaturas` **não toca dado clínico**: sabe se a conta está ativa, não o que há dentro | ⚙️🔒 | ✅ | ⚪ | §3.2 |
| S-04 | **Sem teste gratuito.** Paga antes de usar | 🎨⚙️ | ✅ | ⚪ | ADR-036 |
| S-05 | E-mail de cancelamento leva **link autenticado**, nunca prontuário anexado | ⚙️🔒 | ✅ | ⚪ | ADR-037 |
| S-06 | Máquina de estados da conta: `ATIVA` → `TOLERANCIA` (7d) → `SOMENTE_LEITURA` (30d) → `ARQUIVADA` (60d) → `DESCARTADA` | ⚙️🔒 | ✅ | ⚪ | ADR-038 |
| S-07 | Em `SOMENTE_LEITURA` ele navega e baixa o que quiser; não cria nada | 🎨⚙️ | ✅ | ⚪ | ADR-038 |
| S-08 | Notificação repetida durante os 90 dias, em três camadas: in-app, e-mail e **WhatsApp** | 🎨⚙️ | ✅ | ⚪ | ADR-043 |
| S-11 | O relógio do descarte **congela** sem prova de aviso entregue ou acesso à conta | ⚙️🔒 | ✅ | ⚪ | ADR-043 |
| S-09 | Inadimplente que regulariza volta a `ATIVA` sem perder nada | ⚙️ | ✅ | ⚪ | ADR-038 |
| S-10 | **Demonstração com dados fictícios** para conhecer o produto antes de assinar | 🎨 | ✅ | ⚪ | P-62 |

⚠️ **Módulo ainda não submetido ao Grill-Me.** Inadimplência é delicada: cortar acesso pode deixar
o psicólogo sem a documentação que a lei o obriga a guardar por 5 anos.

---

## 9. Indicadores — app `indicadores`
**Código: ⚪ como app.** O painel provisório vive em `core/views.py` e mostra só o que o cadastro
de pacientes permite — declarando na tela o que ainda não sabe (ADR-012). Ele **não** é o app
`indicadores`: quando `Consulta` existir, o painel muda de dono e sai de `core`.


### Painel (diário, ação)

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| I-01 | Pacientes ativos com último atendimento e **dias sem atender**, nos limiares de 7 e 30 dias | 🎨⚙️ | ✅ | 🟠 | portado do original |
| I-02 | Resumo por paciente: sessões do mês e pendência de pagamento | 🎨 | ✅ | ⚪ | escopo |
| I-03 | Pendências de ação: cobranças em aberto e **prontuários não escritos** | 🎨 | ✅ | ⚪ | ADR-017 |
| I-04 | Três indicadores de cabeçalho: receita líquida, ocupação da agenda, entradas × saídas | 🎨 | ✅ | ⚪ | ADR-027 |
| I-05 | Curto o bastante para caber numa tela, **sem gráfico decorativo** | 🎨 | ✅ | ⚪ | ADR-027 |

### Análise (eventual, profundidade)

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| I-06 | Quanto do faturamento depende de um paciente só (risco de concentração) | ⚙️ | ✅ | ⚪ | ADR-027 |
| I-07 | Em que momento as pessoas desistem — **calculado**, não perguntado | ⚙️ | ✅ | ⚪ | ADR-027 |
| I-08 | Horas trabalhadas × horas disponíveis (trabalhar = só horário de atendimento) | ⚙️ | ✅ | ⚪ | ADR-027, ADR-029 |
| I-09 | Sessões realizadas por mês | ⚙️ | ✅ | ⚪ | ADR-027 |
| I-10 | A análise usa **apenas dado administrativo**. Nunca conteúdo de prontuário | 🔒 | ✅ | ⚪ | ADR-027 |

---

## Regras de dependência entre apps

1. `core` não depende de ninguém; todos dependem dele.
2. `indicadores` depende de todos; **ninguém depende de `indicadores`**.
3. `assinaturas` não toca dado clínico.
4. Sem dependência circular entre apps de domínio.
5. A IA fica atrás de adaptador — o domínio não conhece provedor.
6. `prontuarios` depende de `atendimentos`; nunca o contrário.

## 🎯 O próximo passo, em detalhe

O passo 2 é **`agenda` + `atendimentos`**, e eles vêm juntos porque a recorrência (agenda) só faz
sentido gerando consultas concretas (atendimentos).

**Sequência sugerida**, do mais barato ao mais caro, cada item utilizável antes do seguinte:

1. **F-05 primeiro — trilha de auditoria em `core`.** Não é agenda, mas é pré-requisito do
   prontuário e fica muito mais caro de acrescentar depois que existirem models gravando.
2. **`Caso` em `pacientes`** (P-02 a P-04). A consulta pende do caso, não do paciente. Lembre do
   ponto sutil da ADR-026: cadastrar paciente individual cria um caso de um **em silêncio**, e a
   palavra "Caso" só aparece na tela para quem atende casal.
3. **`Consulta` em `atendimentos`** (T-01, T-02): estado e `contabilizada` como **eixos
   independentes** — é o que cobre falta cobrada e sessão de cortesia. Presença por participante.
4. **`HorarioDisponivel` e a grade** (A-09, A-10): declarada pelo psicólogo, ocupação derivada.
5. **`Recorrencia`** (A-01 a A-05): a parte mais difícil do passo. A ocorrência remarcada à mão
   precisa **lembrar disso** e sobreviver a uma mudança na regra. "Todas" não existe.
6. **Google Agenda** (A-12 a A-16) por último: é integração externa, e tudo acima funciona sem ela.

**Testes obrigatórios deste passo** (claude.md §10): remarcação avulsa que sobrevive a mudança na
regra; quinzenal com âncora; e as cinco combinações de estado × `contabilizada`.

**Armadilha registrada:** materializar a recorrência **não** pode criar prontuário pendente nem
cobrança de sessão futura. O gatilho é a consulta ficar `REALIZADA`, nunca o agendamento.

---

## 🚧 Decisões abertas que bloqueiam trabalho

Não decida sozinho — são do Paulo. Estão em [perguntas.md](perguntas.md).

| # | Bloqueia | Pergunta |
|---|---|---|
| P-68 | Qualquer comando de management ou tarefa que toque dado | Escopo Python e escopo Postgres podem divergir fora do middleware |
| P-69 | Validação de qualquer model novo | `full_clean()` no `save()`: ligar ou não? Hoje só o `ModelForm` valida |
| P-70 | `Caso`, e depois `Prontuario` | `CASCADE` no dono × guarda de 5 anos do CFP |
| P-71 | Exportação de prontuário (passo 3) | Transação por requisição × `StreamingHttpResponse` |
| P-46 | Recorrência (item 5 acima) | Tamanho da janela de materialização e quando empurrá-la |
| P-09 | Financeiro (passo 4) | Trocar modalidade de cobrança no meio do mês afeta cobranças já geradas? |

---

## Ordem sugerida de construção

1. **`core`** — a prova de conceito do isolamento (F-03, F-04). Nada mais começa antes disso.
2. **`contas` + `pacientes`** — sem dono e sem paciente, nada existe.
3. **`agenda` + `atendimentos`** — a consulta é a âncora de tudo o mais.
4. **`prontuarios`** — a razão de o produto existir.
5. **`financeiro`** — depende de consulta contabilizada.
6. **`documentos`** — independente; pode ir em paralelo a partir do passo 3.
7. **`indicadores`** — por último, porque só lê.
8. **`assinaturas`** — necessário para vender, não para validar.
