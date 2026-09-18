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

**Passos 0 a 3 concluídos: fundação, cadastro, agenda, financeiro básico, painel e prontuário escrito à mão.** Rodando, com 407 testes verdes contra PostgreSQL real.

| App | Situação | O que existe |
|---|---|---|
| `core` | 🟢 no ar | Isolamento em três camadas, três papéis de banco, middleware, trilha de auditoria, calendário de vencimentos |
| `contas` | 🟠 parcial | Model do psicólogo, login, logout, tela de perfil com padrões de atendimento (C-03), herdados no cadastro (C-04) |
| `pacientes` | 🟠 parcial | Cadastro; `Caso` individual (em silêncio) e de casal; pagador; responsável legal; cobrança com vigência. Falta P-08, que depende de prontuário |
| `agenda` `atendimentos` | 🟢 no ar | Frequência semanal, quinzenal ou avulso; sessões previstas calculadas; cadastro do que aconteceu (realizada, falta cobrada, falta remarcada); pendência; colisão; desfecho e retomada; grade de horários com mapa da semana. Google Agenda depois (ADR-051) |
| `financeiro` | 🟠 parcial | Devido calculado por mês e por sessão; registro de pagamento com forma; lembrete de pendência. Faltam despesas e faturamento líquido |
| `prontuarios` | 🟠 parcial | Texto livre com rascunho, confirmação e correção em versão nova; versão confirmada imutável até no banco; pendentes no painel. IA na etapa final (ADR-058) |
| `indicadores` | 🟠 parcial | Painel com a agenda de hoje, o que ficou para trás e o resumo do mês. Falta a tela de análise |
| `documentos` | 🟠 parcial | Modelos de documento psicológico em branco, rascunho → emitido, cópia congelada |
| `assinaturas` | ⚪ | **Nem o app existe.** Nenhum `startapp` foi rodado |

**O passo 2 está fechado. Do passo 3, a trilha de auditoria (F-05) está no ar** — cadastro e
responsável legal já entram nela. **A construção segue do mais simples ao mais complexo, com a IA
por último** (ADR-058): nada que dependa de IA, transcrição ou provedor entra antes de todo o resto
estar feito e testado. **Ordem definida pelo teste do usuário (ADR-061):** financeiro básico ✅ →
painel novo ✅ → prontuário escrito à mão ✅ → situações da sessão e modalidade ✅ → máscaras, CEP, perfil com
regime e clínica, remarcação com destino e painel como agenda do dia ✅ → **lixeira de pacientes** (o próximo, ADR-048).

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
| F-05 | Trilha de auditoria: quem viu, criou, alterou, excluiu ou exportou, e quando — **campos, nunca valores**; só acrescenta, garantido no banco | ⚙️🔒 | ✅ **feito** | 🟢 | ADR-005, ADR-057 |
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

✅ **F-05 (trilha de auditoria) construída** (ADR-057). Model clínico novo herda
`core.auditoria.Auditado`; a view registra visualização e exportação. A trilha guarda campos, nunca
valores, e o papel da requisição não consegue alterá-la nem apagá-la.

---

## 1. Conta e perfil — app `contas`
**Código: 🟠 parcial.** No ar: model do psicólogo (é o `AUTH_USER_MODEL`), login por e-mail,
logout e tela de perfil editável, com os **padrões de atendimento** (C-03: duração da sessão,
vencimento da mensalidade, cobro falta). O cadastro de paciente já herda o vencimento e diz de onde
ele veio (C-04); duração e cobro falta passam a ser herdados quando a agenda e as consultas
existirem. Falta: **cadastro de novo psicólogo** (C-01 só tem a metade do login — criar conta
depende do ciclo de assinatura, passo 7), recuperação de senha, e os dados fiscais opcionais (C-05),
que só fazem sentido quando houver saída fiscal.


> Como **psicólogo**, quero configurar meus padrões uma vez e não responder a mesma pergunta a cada cadastro.

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| C-01 | Cadastro e login; a conta é a raiz do isolamento | 🎨⚙️ | ✅ | 🟢 | ADR-001 |
| C-02 | Perfil: nome completo, CPF, **CRP (região + número)**, telefone, e-mail, regime PF/PJ e **CNPJ se PJ** | 🎨🗄️ | ✅ | 🟢 | ADR-044 |
| C-06 | **Sem CRP não há cadastro.** O registro é condição de entrada | 🎨⚙️ | ✅ | 🟢 | ADR-044 |
| C-07 | Validação de **formato** do CRP. **Sem** consulta ao cadastro do CFP | ⚙️ | ✅ | 🟢 | ADR-044 |
| C-08 | Campos vazios para `situacao_registro` e `verificado_em`, prontos caso a verificação volte | 🗄️ | ✅ | 🟢 | ADR-044 |
| C-09 | CRP da empresa (PJ): campo **opcional** | 🎨🗄️ | ✅ | 🟢 | ADR-044 |
| C-10 | **Quiz de cadastro** em quatro passos: conta, regime, abordagem e formas de atendimento, clínica. Tranca o sistema até terminar | 🎨⚙️🗄️ | ✅ | 🟢 | ADR-071 |
| C-11 | **Dados da clínica no perfil**: nome, telefone e endereço, com regime PF/PJ, CNPJ e razão social | 🎨🗄️ | ✅ | 🟢 | ADR-067 |
| C-03 | Padrões do psicólogo: duração da sessão (50 min), vencimento da mensalidade, cobro falta (sim/não) | 🎨🗄️ | ✅ | 🟢 | ADR-025 |
| C-04 | Toda tela de cadastro mostra **de onde veio** o valor herdado do perfil | 🎨 | ✅ | 🟢 | ADR-025 |
| C-05 | Dados fiscais **opcionais** (outras rendas, INSS, dependentes, pensão), fora do onboarding | 🎨 | ✅ | ⚪ | ADR-012 |

---

## 2. Pacientes e casos — app `pacientes`
**Código: 🟠 parcial.** No ar: o **cadastro da pessoa** (P-01, P-09) e o **vínculo** (P-02 a
P-07). Todo paciente cadastrado ganha um `Caso` individual em silêncio; atendimento de casal ou
família é um `Caso` com vários participantes, sem tocar nos individuais. Pagador separado
(participante ou pessoa de fora), responsável legal com guarda, e condição de cobrança com **data de
vigência** — a troca vale no dia 1º do mês seguinte (ADR-050). As quatro tabelas novas estão sob RLS,
e a validação do model recusa ligar registros de psicólogos diferentes, porque a checagem de chave
estrangeira do Postgres ignora as policies. Falta P-08, que depende de prontuário existir.

⚠️ A exclusão de paciente é **definitiva** e leva o caso individual junto — correto pela ADR-048,
porque ainda não existe atendimento, e sem atendimento todo cadastro é "feito por engano". A
**lixeira** para paciente com atendimento entra com o app `atendimentos`. Recusa excluir quem está
em atendimento de casal. Ver **P-70**, resolvida em parte.


> Como **psicólogo**, quero cadastrar quem eu atendo sem preencher campo que não uso.

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| P-01 | Cadastro de paciente: nome, CPF, telefone, e-mail, endereço com CEP, nascimento, medicamento em uso | 🎨🗄️ | ✅ | 🟢 | escopo |
| P-02 | `Caso` criado **em silêncio** ao cadastrar paciente individual; a palavra não aparece na tela | ⚙️🗄️ | ✅ | 🟢 | ADR-026 |
| P-03 | Atendimento de casal ou família: um `Caso` com N pacientes | 🎨⚙️🗄️ | ✅ | 🟢 | ADR-026 |
| P-04 | A **pessoa é única** entre atendimentos: mesmo cadastro em terapia individual e de casal | 🗄️ | ✅ | 🟢 | ADR-026 |
| P-05 | **Pagador** separado do paciente, com o CPF do paciente como padrão; segundo campo só ao marcar "quem paga é outra pessoa" | 🎨🗄️ | ✅ | 🟢 | ADR-009 |
| P-06 | **Responsável legal** (1..N) com tipo de guarda registrado | 🎨🗄️ | ✅ | 🟢 | ADR-014 |
| P-07 | Valor acordado e modalidade de cobrança pertencem ao **caso**, não ao paciente | 🗄️ | ✅ | 🟢 | ADR-002, ADR-026 |
| P-08 | Acesso direto, do cadastro, aos prontuários já realizados e à contagem de sessões | 🎨 | ✅ | 🟠 | escopo, ADR-064 |
| P-09 | Paciente nascido antes de 2018 pode não ter CPF: avisar, não bloquear | 🎨 | ✅ | 🟢 | ADR-040 |
| P-10 | **Link de cadastro**: o psicólogo gera um link de uso único (7 dias), o paciente preenche os próprios dados numa tela pública, e a resposta espera a revisão — só vira paciente quando o psicólogo salva | 🎨⚙️🗄️🔒 | ✅ | 🟢 | ADR-081 |
| P-11 | Revisão do cadastro enviado pelo paciente dentro do "Novo paciente", já preenchido; ao salvar entram contatos de emergência, responsável legal e responsável financeiro, e a resposta é apagada do convite | 🎨⚙️ | ✅ | 🟢 | ADR-081 |
| P-12 | Cadastro ampliado: nome social, documento estrangeiro, estado civil, gênero, raça/cor, profissão, país e até dois **contatos de emergência** — iguais nas duas portas | 🎨🗄️ | ✅ | 🟢 | ADR-081 |
| P-13 | Tela pública com aviso de privacidade e aceite (LGPD); criança ou adolescente pede o responsável; campo sensível é opcional | 🎨🔒 | ✅ | 🟢 | ADR-081 |
| P-14 | CPF repetido vira erro no campo, e não erro de servidor | ⚙️ | ✅ | 🟢 | ADR-081 |
| P-15 | Endereço **obrigatório** no link de cadastro; para quem mora **fora do Brasil**, tudo escrito à mão — código postal livre, telefone com código do país, estado ou província em texto, sem máscara nem busca de CEP | 🎨⚙️🗄️ | ✅ | 🟢 | ADR-082 |

---

## 3. Agenda — app `agenda`
**Código: 🟢 agenda própria no ar.** A regra de frequência com início e fim (A-01), as sessões previstas **calculadas, nunca gravadas** (A-02, ADR-060), a troca "desta data em diante" (A-05), hora e duração (A-06), a colisão que bloqueia (A-07, A-08) e a grade de horários com o mapa da semana, que avisa e não bloqueia (A-09, A-10, ADR-056). A remarcação (A-03, A-04) saiu com a ADR-060. Google Agenda depois (ADR-051).


> Como **psicólogo**, meu atendimento é fixo quase sempre, mas vez ou outra remarca.

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| A-01 | Frequência por caso: **semanal**, **quinzenal** (semana sim, semana não, com âncora) ou **avulso** (sem sessão prevista) | 🎨🗄️ | ✅ | 🟢 | ADR-022, ADR-053 |
| A-02 | Sessões **previstas** pela frequência aparecem na agenda, **calculadas e nunca gravadas**; a que passou sem cadastro é **pendente** | ⚙️🎨 | ✅ | 🟢 | ADR-052, ADR-060 |
| A-03 | ~~Remarcação avulsa~~ — a sessão que não aconteceu vira falta remarcada, e a nova é cadastrada quando acontecer | — | ❌ | — | ADR-060 |
| A-04 | ~~Ocorrência remarcada lembra que foi alterada à mão~~ — não há mais consulta gravada antes de acontecer | — | ❌ | — | ADR-060 |
| A-05 | Alterar a frequência vale **"desta data em diante"**; o que foi cadastrado não é tocado | 🎨 | ✅ | 🟢 | ADR-022 |
| A-06 | Consulta tem data, **hora e duração** (o original só tem data) | 🗄️ | ✅ | 🟢 | ADR-023 |
| A-07 | Colisão de horário **bloqueia** a marcação | ⚙️ | ✅ | 🟢 | ADR-024 |
| A-08 | Casal não dispara colisão: é uma consulta com dois participantes | ⚙️ | ✅ | 🟢 | ADR-026 |
| A-09 | Grade de horários declarada pelo psicólogo, com ocupação **derivada** — sem manutenção dupla. Fora da grade **avisa**, não bloqueia | 🎨⚙️ | ✅ | 🟢 | ADR-029, ADR-056 |
| A-10 | Tela de horários como mapa da semana: o que está ocupado, por quem, e o que sobrou | 🎨 | ✅ | 🟢 | ADR-029 |
| A-11 | Férias, feriados e pausas em bloco | — | ⏸️ | ⚪ | P-47 |
| A-17 | **Filtro de período** na agenda, com filtro por situação junto | 🎨⚙️ | ✅ | 🟢 | ADR-065 |
| A-18 | **Percentual de online × presencial** entre as sessões da agenda | 🎨⚙️ | ✅ | 🟢 | ADR-065 |
| A-19 | **Remarcada diz para quando**: a data nova entra na agenda esperando cadastro | 🎨⚙️🗄️ | ✅ | 🟢 | ADR-068 |
| A-20 | **Valor desta sessão**: cobrar à parte a extra do mensalista e a sessão de quem não tem valor combinado | 🎨⚙️🗄️ | ✅ | 🟢 | ADR-070 |
| A-21 | **Agenda em formato de calendário**: colunas por dia, cartões por horário, horários livres da grade, visões de dia, semana e mês | 🎨⚙️ | ✅ | 🟢 | ADR-073 |

### Integração com Google Agenda — depois da agenda própria (ADR-051)

Exige verificação do Google, de 4 a 6 semanas, e sem ela o produto trava em 100 usuários. Nada aqui foi revogado; só vem depois.

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| A-12 | OAuth com **leitura** na conexão; **escrita** pedida só ao ativar o recurso, com explicação na tela | 🎨⚙️ | ✅ | ⚪ | ADR-020 |
| A-13 | Consulta vira evento em calendário **dedicado** ("Hamilton — Atendimentos"), nunca no pessoal dele | ⚙️ | ✅ | ⚪ | ADR-020 |
| A-14 | Leitura da agenda para evitar marcação sobreposta | ⚙️ | ✅ | ⚪ | ADR-020 |
| A-15 | Evento movido no Google é **detectado** e o sistema oferece atualizar aqui | 🎨⚙️ | ✅ | ⚪ | ADR-020 |
| A-16 | Ensinar o psicólogo a ligar o "Resumo diário" do Google — é ele que faz o alerta matinal | 🎨 | ✅ | ⚪ | ADR-018 |

---

## 4. Atendimentos — app `atendimentos`
**Código: 🟢 no ar.** O psicólogo cadastra a consulta — realizada, falta cobrada ou falta remarcada —, e a cobrança deriva da situação (T-01, T-02, ADR-060). O sistema nunca cadastra sozinho: sessão prevista que passou sem cadastro é pendência no painel e na agenda (ADR-052). Desfecho com retomada, e paciente encerrado numa aba própria (T-05, ADR-055). T-04 está pronto do lado da consulta — os disparos passam a existir quando houver prontuário e financeiro. Presença por participante saiu do escopo (ADR-054).


| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| T-01 | Consulta **cadastrada pelo psicólogo**, só depois de acontecer, da frequência ou avulsa | 🎨🗄️ | ✅ | 🟢 | ADR-060 |
| T-02 | Cobrança **deriva da situação**, e só o cancelamento do cliente aceita desmarcar | 🗄️ | ✅ | 🟢 | ADR-060, ADR-065 |
| T-03 | ~~Presença registrada por participante~~ — consulta de casal registrada uma vez; ausência vai no prontuário | 🗄️ | ❌ | — | ADR-054 |
| T-04 | `REALIZADA` dispara **prontuário pendente**; consulta cobrada dispara **conta a receber** | ⚙️ | ✅ | 🟠 | ADR-016, ADR-060 |
| T-05 | Desfecho (alta, desistência, encaminhamento, interrupção), com o número de sessões derivado, não perguntado; encerra a agenda do caso e pode ser retomado | ⚙️🗄️ | ✅ | 🟢 | ADR-027, ADR-049, ADR-055 |
| T-06 | **Cinco situações**: presente, faltou sem avisar, cliente cancelou, profissional cancelou, remarcada — a sessão é presumida confirmada | 🎨🗄️ | ✅ | 🟢 | ADR-065 |
| T-07 | **Modalidade da sessão**: online ou presencial, com padrão vindo do paciente | 🎨🗄️ | ✅ | 🟢 | ADR-065 |

---

## 5. Prontuários — app `prontuarios`
**Código: 🟠 prontuário escrito à mão no ar.** Texto livre, um por participante de cada sessão realizada, com
rascunho, confirmação e correção em versão nova com motivo; versão confirmada imutável até no banco; trilha de
auditoria; pendentes no painel, na ficha e na tela da consulta (ADR-064). A IA vem na etapa final.

⏸️ **IA e transcrição (R-01, R-03, R-09, R-10, R-14) ficam para a etapa final** (ADR-058). O
prontuário **escrito à mão** vem antes — com rascunho, confirmação e versão congelada (R-04, R-05) —,
e a IA depois passa a preencher o mesmo rascunho. Avaliação do protótipo Exyo em P-18.


> Como **psicólogo**, quero recuperar os ~20 minutos que gasto escrevendo prontuário depois de cada sessão.

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| R-01 | Relato de origem em **áudio ditado** ou **texto escrito** — duas portas para o mesmo pipeline. O texto **não** passa por transcrição | 🎨⚙️ | ✅ | ⚪ | ADR-006, ADR-042 |
| R-02 | A sessão **nunca** é gravada; o único falante é o psicólogo | 🔒 | ✅ | ⚪ | ADR-006 |
| R-03 | IA estrutura o relato no formato do Art. 2º da Res. CFP 001/2009 | ⚙️ | ✅ | ⚪ | ADR-005 |
| R-04 | **Rascunho obrigatório**: revisão e confirmação explícita antes de virar registro oficial | 🎨 | ✅ | 🟢 | ADR-005, ADR-064 |
| R-05 | Versão congelada na confirmação, com trilha de auditoria — é meio de prova em processo disciplinar. Imutável no model **e no banco** (gatilho) | ⚙️🔒 | ✅ | 🟢 | ADR-005, ADR-064 |
| R-15 | Prontuário escrito à mão, **texto livre**, um por participante de cada sessão realizada; pendente calculado | 🎨⚙️ | ✅ | 🟢 | ADR-064 |
| R-16 | **Editar** prontuário confirmado cria nova versão, em silêncio — sem motivo e sem falar em versão na tela; as anteriores ficam no histórico | 🎨⚙️ | ✅ | 🟢 | ADR-064, ADR-075 |
| R-17 | **Prontuário geral do paciente, na aba Documentos**, na forma da Res. CFP 001/2009: identificação (do cadastro), avaliação da demanda e objetivos, **evolução montada com todos os registros de sessão confirmados** (só leitura), encaminhamento ou encerramento — com a orientação do CFP ao lado e o administrativo pré-preenchido | 🎨⚙️ | ✅ | 🟢 | ADR-079, ADR-080 |
| R-18 | `FichaDoProntuario` (demanda e encerramento) **só se acrescenta**: imutável no model e no banco (gatilho), RLS própria; paciente com ficha escrita não é apagado | 🗄️🔒 | ✅ | 🟢 | ADR-079 |
| R-19 | Prontuário em **PDF e DOCX** — só o que está confirmado; exportação na trilha de auditoria | ⚙️🔒 | ✅ | 🟢 | ADR-078, ADR-079 |
| R-20 | Aba **Prontuários só com os registros de sessão**, com filtro por paciente e aviso de onde fica o prontuário geral | 🎨 | ✅ | 🟢 | ADR-080 |
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
**Código: 🟠 aba de modelos no ar.** Cinco modalidades da Res. 06/2019 e três termos de apoio, em branco, com a orientação do CFP em cada sub-aba; rascunho → emitido, com a cópia congelada no registro documental (ADR-076). Faltam a guarda de arquivos (D-01 a D-04) e a geração por IA, que fica para o fim (ADR-058).


| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| D-01 | `Documento` com arquivo, tipo, vigência, visibilidade e versões | 🗄️ | ✅ | ⚪ | ADR-021 |
| D-02 | Guarda do **contrato terapêutico** escrito pelo psicólogo, para conferência | 🎨⚙️ | ✅ | ⚪ | ADR-015 |
| D-03 | Alterar **cria versão**; apagar move para **lixeira**; exclusão definitiva só de dentro dela | 🎨⚙️ | ✅ | ⚪ | ADR-015 |
| D-04 | Anexos de avaliação psicológica em **pasta de acesso exclusivo do psicólogo** (inciso V) | 🗄️🔒 | ✅ | ⚪ | ADR-021 |
| D-05 | Cópias de documentos emitidos, com data, finalidade e destinatário (inciso VI) | 🗄️ | ✅ | 🟢 | ADR-021, ADR-076 |
| D-06 | **IA gera Declaração** — sem acesso ao prontuário, proibida de citar sintomas | ⚙️🔒 | ✅ | ⚪ | ADR-032, ADR-034 |
| D-07 | **IA gera Relatório Psicológico** — 5 itens: identificação, demanda, procedimento, análise, conclusão | ⚙️ | ✅ | ⚪ | ADR-032 |
| D-08 | Prazo de validade do conteúdo no **último parágrafo** (Art. 17) | ⚙️ | ✅ | ⚪ | ADR-032 |
| D-09 | Rascunho obrigatório também para documentos gerados | 🎨 | ✅ | ⚪ | ADR-034 |
| D-10 | Diretrizes do CFP em cada sub-aba, com palavras nossas, link para a fonte e versão da norma visível | 🎨 | ✅ | 🟢 | ADR-033, ADR-076 |
| D-11 | Atestado e Laudo — **modelo em branco**, com o pré-requisito da avaliação no topo. Geração por IA segue adiada | 🎨 | ✅ | 🟢 | ADR-076 |
| D-12 | Parecer Psicológico — modelo em branco, com titulação e referências obrigatórias | 🎨 | ✅ | 🟢 | ADR-076 |
| D-13 | Relatório Multiprofissional | — | ❌ Fora | ⚪ | ADR-034 |
| D-14 | **Modelos em branco**, preenchidos **dentro da folha do documento**, com a explicação do campo em foco; rascunho → emitido; impressão pelo navegador | 🎨⚙️🗄️ | ✅ | 🟢 | ADR-076, ADR-077 |
| D-15 | Termos de apoio: entrega de documento, autorização para criança e adolescente (Res. 13/2022), encaminhamento | 🎨 | ✅ | 🟢 | ADR-076 |
| D-16 | **Salvar em PDF e em DOCX**, da mesma composição da folha: laudas numeradas, traços do atestado, rascunho marcado; exportação na trilha de auditoria | ⚙️🔒 | ✅ | 🟢 | ADR-078 |

---

## 7. Financeiro — app `financeiro`
**Código: 🟠 financeiro básico no ar.** O mês com o devido, o pago e o que falta de cada paciente; registro de pagamento da mensalidade (dia fixo ou dia útil) e da sessão; forma de pagamento; lembrete de pagamento pendente no financeiro e no painel (ADR-062, ADR-063). O devido é calculado, nunca gravado. Faltam despesas (N-05, N-06), faturamento líquido (N-07) e o lembrete fiscal (N-09).


| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| N-01 | Modalidade por caso: `MENSAL` ou `POR_SESSAO` | 🎨🗄️ | ✅ | 🟢 | ADR-002 |
| N-02 | `POR_SESSAO`: **cada sessão cobrada** — realizada ou falta cobrada — **gera um pagamento pendente** daquela sessão, que vence no dia dela | ⚙️ | ✅ | 🟢 | ADR-063 |
| N-13 | `MENSAL` vence numa **data personalizada** por paciente: **dia fixo** ("todo dia 10") ou **dia útil** ("5º dia útil", seg–sex sem feriado nacional), com padrão no perfil | 🎨🗄️ | ✅ | 🟢 | ADR-063 |
| N-03 | Registros permanecem **granulares**; o agrupamento por paciente existe só na apresentação | ⚙️🎨 | ✅ | ⚪ | ADR-002 |
| N-04 | Registro de pagamento pelo psicólogo: valor, data e observação, referente **ao mês** (mensalidade) **ou à sessão** (por sessão). Sem campo de terapeuta | 🎨🗄️ | ✅ | 🟢 | ADR-035, ADR-063 |
| N-04a | Pagou menos, o restante fica **pendente**; pagou a mais, é só mais um registro | ⚙️ | ✅ | 🟢 | ADR-062 |
| N-04b | **Forma de pagamento obrigatória**: Pix, cartão, dinheiro ou transferência | 🎨🗄️ | ✅ | 🟢 | ADR-063 |
| N-04c | Listagem com busca, filtro por mês e ordenação, portadas do original | 🎨 | ✅ | ⚪ | ADR-035 |
| N-05 | Despesas com **catálogo de tipos** e marca de dedutibilidade | 🎨🗄️ | ✅ | ⚪ | ADR-011 |
| N-06 | Anexo de comprovante na despesa, **opcional** | 🎨⚙️ | ✅ | ⚪ | ADR-040 |
| N-12 | ~~Pagamento sem cobrança vira crédito do caso~~ — pagamento a mais é só mais um registro | — | ❌ | — | ADR-062 |
| N-07 | **Faturamento líquido** = receita − despesas. Independe de regime | ⚙️ | ✅ | ⚪ | ADR-013 |
| N-08 | Lembrete de pagamento pendente: aparece no vencimento e continua até o pagamento cobrir; **pago antes do vencimento, não aparece** | 🎨⚙️ | ✅ | 🟢 | ADR-017, ADR-063 |
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
**Código: 🟠 painel no ar, análise não.** O painel mora no app `indicadores` desde a Rodada 39 e mostra o que a
ADR-061 pediu: sessões feitas e que faltam, receita recebida e a receber, e cada atendimento em curso com situação,
dias sem sessão, sessões no mês e o financeiro do mês. A tela de análise (I-06 a I-09) ainda não existe.


### Painel (diário, ação)

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| I-01 | **A agenda de hoje** no painel: horário, paciente, modalidade e situação — só o dia | 🎨⚙️ | ✅ | 🟢 | ADR-069, ADR-072 |
| I-02 | ~~Dias sem sessão~~ — retirado por completo: não é relevante | 🎨⚙️ | ❌ | — | ADR-072 |
| I-03 | **Um bloco só de pendências**: sessões esperando cadastro, pagamentos pendentes, prontuários por escrever — cada item com o link que o resolve | 🎨 | ✅ | 🟢 | ADR-017, ADR-072 |
| I-04 | Resumo do mês: **sessões feitas × que faltam**; **receita recebida × a receber** (previsto) | 🎨 | ✅ | 🟢 | ADR-061 |
| I-05 | Curto o bastante para caber numa tela, **sem gráfico decorativo** | 🎨 | ✅ | ⚪ | ADR-027 |

### Análise (eventual, profundidade)

| # | História | Camada | Estado | Código | ADR |
|---|---|---|---|---|---|
| I-06 | Quanto do faturamento depende de um paciente só (risco de concentração) | ⚙️ | ✅ | ⚪ | ADR-027 |
| I-07 | Em que momento as pessoas desistem — **calculado**, não perguntado | ⚙️ | ✅ | ⚪ | ADR-027 |
| I-08 | Horas trabalhadas × horas disponíveis (trabalhar = só horário de atendimento) | ⚙️ | ✅ | ⚪ | ADR-027, ADR-029 |
| I-09 | Sessões realizadas por mês | ⚙️ | ✅ | ⚪ | ADR-027 |
| I-10 | A análise usa **apenas dado administrativo**. Nunca conteúdo de prontuário | 🔒 | ✅ | ⚪ | ADR-027 |
| I-11 | **Gráfico de status de presença** — na tela de análise, nunca no painel (ADR-027) | 🎨 | ✅ | ⚪ | ADR-027 |
| I-12 | **Gráfico de resultado previsto no ano**: receitas × despesas | 🎨⚙️ | 🟡 | ⚪ | depende de despesas (N-05) |

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
   independentes** — é o que cobre falta cobrada e sessão de cortesia.
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
| P-69 | Validação de qualquer model novo | ✅ Resolvida: `full_clean()` roda em todo `save()` — herde de `core.models.ValidaAoSalvar` ou de `TenantOwnedModel`, que já herda dele |
| P-70 | `Caso`, e depois `Prontuario` | 🟡 Paciente resolvido por serviço (ADR-048); falta o `CASCADE` a partir do psicólogo |
| P-71 | Exportação de prontuário (passo 3) | Transação por requisição × `StreamingHttpResponse` |
| P-46 | Recorrência (item 5 acima) | Tamanho da janela de materialização e quando empurrá-la |
| P-09 | Financeiro (passo 4) | ✅ Resolvida: a troca vale no dia 1º do mês seguinte (ADR-050) |

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
