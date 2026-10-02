# Documentação — Hamilton Individual

Registro da evolução e da arquitetura do projeto. Atualizado a cada rodada de planejamento.

---

## ⚡ Estado do código — passos 0 e 1

> Para saber **o que falta construir**, o documento é [demandas.md](demandas.md). Este aqui
> registra o que existe e por quê.

**532 testes verdes contra PostgreSQL real, nenhum pulado.** A suíte roda em **~1,7 min com `--parallel 4`**; em série leva ~11 min. A diferença não é teste lento: medida app a app, a suíte inteira soma ~3,7 min, e o excesso aparece só quando tudo roda num processo só — é a limpeza do banco entre os testes de tela (`TransactionTestCase`), que cresce a cada app novo. Rode em paralelo num PostgreSQL 17 local; contra o Neon gratuito, a suspensão automática do banco derrubava a execução no meio.

### Apps que existem

| App | Contém |
|---|---|
| `core` | `TenantOwnedModel`, `TenantManager`, middleware de escopo, RLS, `dispensa_escopo`, check de deploy, painel provisório |
| `contas` | `Psicologo` (é o `AUTH_USER_MODEL`), login, logout, perfil |
| `pacientes` | `Paciente` com cadastro completo, lista, busca, ficha, edição e exclusão |

Os outros sete apps do plano (`agenda`, `atendimentos`, `prontuarios`, `documentos`,
`financeiro`, `assinaturas`, `indicadores`) **não existem** — nem o diretório.

### Isolamento: três camadas e três papéis

A ADR-001 promete que nenhum psicólogo alcança dado de outro. A promessa se apoia em três
camadas independentes, e a terceira depende de uma separação de papéis no Postgres que só ficou
certa depois de uma auditoria adversarial (ADR-046):

| Camada | Onde | Protege contra |
|---|---|---|
| 1. Dono explícito | `TenantOwnedModel` | Model sem dono; gravar com dono errado |
| 2. Manager que explode | `TenantManager` | Query sem escopo — quebra no teste, não vaza em produção |
| 3. Row-Level Security | Postgres | `.raw()`, `cursor.execute()`, shell, view escrita às pressas |

| Papel de banco | Quando | Alcança |
|---|---|---|
| `hamilton_owner` | só `migrate` (DDL exige) | tudo |
| `hamilton_web` | **conexão da aplicação** e requisição anônima | login e sessão. Nada de clínico |
| `hamilton_app` | `SET LOCAL ROLE` na requisição autenticada | domínio, filtrado pelo RLS |

`hamilton_web` é `NOINHERIT`: pode *virar* `hamilton_app`, mas não *é*. É o que faz `RESET ROLE`
— a fuga clássica de uma injeção de SQL — cair num papel sem permissão nenhuma no domínio.

### Interface

Bootstrap 5 por CDN, sem build nem pipeline de assets. Herda do original a **estrutura** que a
ADR-004 manda portar (sidebar de ícones, header fixo, densidade alta) e **nada** da identidade
visual da Allos — o produto não é dela.

Duas decisões de interface que valem para as telas futuras:

- **A tela declara o que não sabe** (ADR-012). O painel mostra "Faturamento do mês — depende do
  financeiro (passo 4)" em vez de esconder o widget ou inventar número. Os módulos futuros
  aparecem na barra lateral apagados, com o passo no tooltip.
- **Não existe campo de dono em formulário nenhum.** `psicologo` é `editable=False` e vem do
  contexto da requisição. Quem editar o HTML e injetar `psicologo=<id do outro>` não muda nada —
  há teste provando.

### Dívidas registradas

| O quê | Onde |
|---|---|
| ✅ ~~`full_clean()` no `save()` não existe; só o `ModelForm` valida~~ — resolvido por `core.models.ValidaAoSalvar` | P-69 |
| Escopo Python e Postgres podem divergir fora do middleware | P-68 |
| `CASCADE` no dono × guarda de 5 anos do CFP | P-70 |
| Transação por requisição × `StreamingHttpResponse` na exportação | P-71 |
| ~~Trilha de auditoria (F-05) não construída~~ — ✅ construída (ADR-057) | demandas.md §0 |
| `/admin/` registrado é superfície de conferência do passo 0, não produto | `contas/admin.py` |

---


## 0. Quem é o cliente — e quem não é

⚠️ **O Hamilton Individual não é um produto da Allos nem para a Allos.** É um projeto próprio,
que se **inspira** no `hamilton-api` como referência de domínio e de interface, e nada mais.

| | Hamilton original (`hamilton-api`) | Hamilton Individual |
|---|---|---|
| Cliente | A associação Allos | **Psicólogos autônomos do mercado**, sem vínculo entre si |
| Estrutura | Clínica com vários terapeutas, coordenação e supervisão | Um profissional sozinho, replicado N vezes |
| Acesso de supervisor | Existe (decano vê os supervisionados) | **Não existe. Proibido** (ADR-001) |
| Validação de produto | — | Conversar com psicólogos autônomos do mercado, não com um grupo específico |

Consequência prática: nenhuma decisão deste projeto pode assumir contexto de associação, de
supervisão, de coordenação ou de comunidade entre os psicólogos. Cada assinante é uma ilha.

## 1. O que é

ERP para o **psicólogo clínico autônomo**. Uma única plataforma, vendida individualmente: cada
psicólogo acessa sua própria conta com login e senha e faz ali a gestão da sua clínica, com
isolamento total dos dados.

Distinção em relação ao `hamilton-api` (sistema de origem): o Hamilton original gere uma
**clínica com vários terapeutas**, com coordenação, supervisão, match de paciente e plantão.
O Individual atende **um profissional sozinho**, replicado N vezes.

**Problema central:** devolver tempo ao psicólogo. A referência concreta é o prontuário —
hoje ~20 min de escrita após cada sessão.

**Requisito de produto herdado explicitamente:** a simplicidade da interface do Hamilton
original. Tela limpa, informação sem ruído, o usuário não se perde. Isso é requisito, não
estética (ADR-004).

## 2. Stack

| Camada | Escolha |
|---|---|
| Backend | Django, organizado em apps modulares por domínio |
| Banco | Neon (PostgreSQL) |
| Deploy | Render |
| Cobrança da assinatura | Asaas (o psicólogo assinante paga o Hamilton) |
| Fiscal do psicólogo | 🚫 Fora do MVP (ADR-013). Cliente-alvo é **PF e PJ**; carnê-leão e NFS-e ficam para depois do núcleo. |

## 3. Arquitetura

### 3.1 Isolamento (multi-tenancy)
Decidido em **ADR-001**: banco compartilhado com o dono explícito em cada modelo, manager que
recusa query sem escopo, e Row-Level Security do PostgreSQL como camada final. O mecanismo de
supervisão / "view-as" do original é funcionalidade **proibida** aqui.

### 3.2 Apps Django
🟡 **Proposta — Rodada 7, aguardando validação.**

Dez apps: um de infraestrutura, oito de domínio e um de leitura. O critério de fronteira é
**quem é dono do dado**, não em que tela ele aparece.

| App | É dono de | Não é dono de |
|---|---|---|
| `core` | Base multi-tenant: `TenantOwnedModel`, `TenantManager`, middleware de RLS, trilha de auditoria. **Nenhum domínio.** | Qualquer regra de negócio |
| `contas` | `User`, `Psicologo` (CRP, CPF, regime tributário, dados fiscais opcionais). **Raiz do tenant.** | Pacientes |
| `pacientes` | `Paciente`, `ResponsavelLegal`, `Pagador` | Consultas, cobranças, contratos |
| `documentos` | `Documento` (arquivo, tipo, vigência, visibilidade, versões). Contrato, anexo de avaliação e cópia de documento emitido são **tipos** | Quem é o paciente; geração e assinatura do documento |
| `agenda` | `HorarioDisponivel`, frequência, bloqueios; integração Google Agenda depois (ADR-051) | Consulta realizada |
| `atendimentos` | `Consulta`, `Desfecho` (alta/desistência) | O texto clínico |
| `prontuarios` | `Relato` (áudio ou texto), `Prontuario`, versões, assinatura, exportação | Quando a sessão ocorreu |
| `financeiro` | `ContaReceber`, `Pagamento`, `Despesa`, `TipoDespesa`, lembretes de cobrança | Preço acordado do paciente |
| `assinaturas` | Ciclo de vida da assinatura (Asaas), cancelamento, exportação e descarte (ADR-007) | Dados clínicos |
| `indicadores` | Dashboard, KPIs, análise de desempenho. **Só leitura.** | Absolutamente nada |

**Regras de dependência** (o que impede o `views.py` de 5.639 linhas do original de renascer):

1. `core` não depende de ninguém; todos dependem dele. Toda model de domínio herda
   `TenantOwnedModel` — é assim que a ADR-001 deixa de ser disciplina e vira estrutura.
2. `indicadores` depende de todos; **ninguém depende de `indicadores`**. Por isso ele pode ler à
   vontade sem criar ciclo.
3. `assinaturas` não toca dado clínico. Ele sabe se a conta está ativa; não sabe o que tem dentro.
4. Sem dependência circular entre apps de domínio. Quando dois precisarem conversar nos dois
   sentidos, a conversa sobe para uma camada de serviço, não vira import cruzado.
5. **A IA fica atrás de um adaptador** em `prontuarios`. O domínio conhece "transformar relato em
   prontuário"; não conhece provedor, modelo nem chave de API. É o que permite plugar a IA já
   existente (P-18) ou trocar de provedor (P-19) sem tocar em regra de negócio.

**Fronteiras que a modelagem já impõe:**
- `Paciente`, `Pagador` e `ResponsavelLegal` são eixos distintos (ADR-009, ADR-014) e vivem
  juntos em `pacientes`, porque nascem e morrem com o cadastro.
- O preço acordado é do paciente; a cobrança gerada é do financeiro. `financeiro` lê o preço,
  não o define.
- `prontuarios` guarda o texto clínico; `atendimentos` guarda o fato de a sessão ter ocorrido.
  Separados porque têm ciclos de vida e regras de retenção diferentes (ADR-005: 5 anos).

### 3.3 Modelo financeiro
Decidido em **ADR-002**: modalidade de cobrança explícita por paciente.
- `POR_SESSAO` — cada consulta registrada gera sua própria cobrança, cobrada logo após o
  atendimento. Agrupamento por paciente só na apresentação da tela de Lembretes.
- `MENSAL` — uma cobrança por mês, com vencimento no início ou no fim, conforme preferência.

Surge uma entidade de **conta a receber** que o original não possui — é ela que torna possível
a aba de Lembretes de cobrança.

### 3.4 Prontuário — especificação legal
Decidido em **ADR-005**: a estrutura obrigatória vem do Art. 2º da **Resolução CFP nº 001/2009**
(identificação, avaliação de demanda e objetivos, evolução do trabalho e procedimentos,
encaminhamento/encerramento, anexos de avaliação em pasta exclusiva, cópias de documentos
emitidos). Guarda mínima de 5 anos, direito de acesso integral do paciente, e valor de **meio
de prova** em processo disciplinar — o que exige trilha de auditoria, não só um campo de texto.


### 3.5 Assinatura — fatos levantados sobre o Asaas

O Asaas tem **assinaturas** nativas: criada a assinatura, ele gera as cobranças na periodicidade
configurada, e **cada cobrança tem ID, status e ciclo próprios**. Meios disponíveis: PIX, boleto,
cartão de crédito e débito, TED. Há ainda **PIX Automático**, que cobra por autorização do pagador
em vez de cartão salvo. **Webhooks são o mecanismo principal de sincronização** — não se deve
consultar a API em laço.

⚠️ **O fluxo de status muda conforme o meio, e isso não é detalhe:**

| Meio | Sequência de eventos |
|---|---|
| **PIX** | `PAYMENT_CREATED` → `PAYMENT_RECEIVED` |
| **Boleto** | `PAYMENT_CREATED` → `PAYMENT_CONFIRMED` → `PAYMENT_RECEIVED` |
| **Cartão** | `PAYMENT_CREATED` → `PAYMENT_CONFIRMED` → `PAYMENT_RECEIVED` **32 dias depois** |

**Referência do original:** o `hamilton-api` usa Stripe e rastreia sete estados de assinatura
(`active`, `past_due`, `canceled`, `incomplete`, `incomplete_expired`, `trialing`, `unpaid`).
O conjunto é bom guia do que precisa existir, mesmo trocando de provedor.

---

## 4. Relação com o `hamilton-api`

Repositório de referência, clonado em `../hamilton-api`, **somente leitura**.

**O que aproveitamos:** a interface (layout, navegação, densidade de informação — ADR-004) e as
regras de negócio já validadas na prática: cálculo de dias sem atendimento, limiares
REGULAR / ATENÇÃO / CRÍTICO em 7 e 30 dias, `choices` de alta e desistência.

**O que não aproveitamos:** o schema legado (`db_table` em português, PKs `pk_*`, colunas
`fk_*`/`dat_*`/`vlr_*`, herdados de um banco anterior ao Django), a estrutura de dois apps com
`views.py` de 5.639 linhas, as migrations git-ignored, e toda a camada financeira (Stripe +
NFS-e WebmaniaBR). ⚠️ **Ressalva (ADR-013):** `acessorios/webmania.py` é uma integração de NFS-e
em funcionamento e volta a ter valor de reuso se atendermos psicólogos PJ.

**Telas do original que não existem no Individual**, por serem de clínica coletiva: match
paciente↔terapeuta, seleção e supervisão de terapeutas, plantão, controle de novos pacientes e
encaminhamento entre profissionais.

---

## 5. Fontes normativas

- [Resolução CFP nº 001/2009](https://site.cfp.org.br/wp-content/uploads/2009/04/resolucao2009_01.pdf) — obrigatoriedade do registro documental; estrutura do prontuário (Art. 2º) e guarda de 5 anos (Art. 4º).
- [Resolução CFP nº 06/2019 comentada](https://site.cfp.org.br/wp-content/uploads/2019/09/Resolu%C3%A7%C3%A3o-CFP-n-06-2019-comentada.pdf) — elementos mínimos dos documentos escritos.
- [Manual Orientativo de Registro e Elaboração de Documentos Psicológicos (CFP, 2025)](https://site.cfp.org.br/wp-content/uploads/2025/11/Manual_Orientativo.pdf) — orientação vigente mais recente.
  Lido na íntegra na Rodada 45. O que ele traz e que pesa em decisão nossa:
  - **Estrutura mínima do registro** (Res. 01/2009): identificação · avaliação da demanda e objetivos · evolução ·
    encaminhamento ou encerramento. Plataforma de prontuário que não garanta essa estrutura "necessita realizar
    adequações" numa fiscalização (nota 4) — ver P-80.
  - **Prontuário × registro documental**: o prontuário é direito do paciente, que pode pedi-lo. Hipótese
    diagnóstica e interpretação não compartilhada vão no *registro documental*, não no prontuário.
  - **Integridade**: evitar espaço em branco para prevenir adulteração; o registro é "prova idônea" em processo
    ético; plataforma eletrônica deve assegurar autenticidade e segurança do conteúdo (nota 3).
  - **Cinco modalidades de documento** (Res. 06/2019) e a tabela de estrutura de cada uma (p. 31). Declaração não
    informa sintoma nem estado psicológico; atestado e laudo resultam de avaliação psicológica (Res. 31/2022);
    parecer **não** decorre de avaliação nem de intervenção. Validade só em atestado, laudo e relatório, no último
    parágrafo. Laudas numeradas ("1/10"), rubricadas até a penúltima, assinatura na última; assinatura
    eletrônica ICP-Brasil dispensa rubrica (Lei 14.063/2020).
  - **Entrega**: protocolo de entrega assinado; relatório e laudo pedem **entrevista devolutiva**.
  - **Guarda**: 5 anos do último registro; 20 anos para prontuário em serviço de saúde (Lei 13.787/2018);
    criança e adolescente, até a maioridade e depois os prazos gerais.
  - **IA** (pergunta 16): permitida como apoio à redação e organização; conteúdo clínico é exclusivo da psicóloga;
    evitar inserir dado sensível em sistema de IA sem respaldo legal ou ético; a responsabilidade não se
    terceiriza. Baliza a IA de prontuário e de documentos, que ficaram para o fim (ADR-058).
- [Guarda de documentos e termo de descarte — CRP-PR](https://crppr.org.br/orientacoes/guarda-de-documentos-e-termo-de-descarte/) — prazos e conflito com a Lei nº 13.787/2018.

---

## 6. Log de evolução

| Data | Rodada | O que ficou decidido |
|---|---|---|
| 2026-09-08 | Setup | Repositórios clonados, artefatos criados, Grill-Me configurado como padrão do projeto. |
| 2026-09-08 | 1 | ADR-001 (isolamento total) e ADR-002 (modalidade de cobrança) aceitas. ADR-003 reaberta para reformulação. |
| 2026-09-08 | 2 | ADR-003 (projeto novo), ADR-004 (reuso de interface, não de código) e ADR-005 (prontuário pela Res. CFP 001/2009) aceitas. ADR-002 refinada: no modo por sessão, cobrança sessão a sessão. |
| 2026-09-08 | 3 | ADR-006 (relato do psicólogo, sem gravar sessão), ADR-007 (exportação e descarte) e ADR-008 (Receita Saúde: não emitimos recibo, geramos CSV). |
| 2026-09-08 | 4 | ADR-009 (pagador ≠ beneficiário), ADR-010 (previsão fiscal é estimativa) e ADR-011 (catálogo de despesas). |
| 2026-09-08 | 5 | ADR-012: precisão fiscal opcional e progressiva. Princípio geral — degradar com honestidade. |
| 2026-09-08 | 6 | ADR-013: carnê-leão e NFS-e fora do MVP. Cliente-alvo é PF **e** PJ. Núcleo financeiro serve os dois regimes. |
| 2026-09-09 | 7–18 | Estrutura de dez apps proposta. ADR-014 a ADR-034: infantil, contrato, lembretes, armazenamento, agenda de mão única, recorrência com exceção, comparecimento × cobrança, `Caso`, painel × análise, IA de documentos pela Res. CFP 06/2019. `demandas.md` escrito. |
| 2026-09-09 | 19–22 | ADR-035 a ADR-039: registro de pagamento com baixa, assinatura (cartão e PIX Automático, sem trial), exportação por link autenticado, ciclo de vida da conta, e a fronteira de que **o sistema não se comunica com pacientes**. `claude.md` escrito. Planejamento do MVP fechado. |
| 2026-09-09 | 23–27 | ADR-040 a ADR-044: pendências menores, um relato por prontuário, transcrição preservada, WhatsApp para descarte, perfil e CRP obrigatório. **Passo 0 implementado e executado** — ADR-045 registra a falha encontrada em produção real: `BYPASSRLS` no papel dono do Neon. |
| 2026-09-13 | 28 | P-69 resolvida: validação do model em toda gravação. `Caso`, pagador, responsável legal, atendimento de casal e cobrança com vigência implementados. ADR-048 (exclusão), 049 (desfechos) e 050 (troca de cobrança no dia 1º). Suíte migrada para PostgreSQL local: 104 testes. |
| 2026-09-13 | 29 | Padrões de atendimento no perfil (C-03: duração da sessão, vencimento da mensalidade, cobro falta) e herança visível no cadastro (C-04). 108 testes. |
| 2026-09-13 | 30 | ADR-051 (agenda própria antes do Google Agenda), 052 (consulta passada nunca é marcada sozinha) e 053 (frequência semanal, quinzenal ou avulso — revisa a 031). |
| 2026-09-13 | 31 | Agenda, primeira parte: apps `agenda` e `atendimentos`. Frequência, previsão de 8 semanas, consulta avulsa, remarcação, colisão (inclusive contra sessões ainda não geradas), registro e pendência no painel. 154 testes. |
| 2026-09-13 | 32 | ADR-054 (casal sem presença por participante — revisa a 026), 055 (desfecho encerra a agenda do caso; retomada reabre) e 056 (grade avisa, nunca bloqueia). Agenda, segunda parte: desfecho e retomada, pacientes encerrados em aba própria, grade de horários com mapa da semana e ocupação, exclusão de casal com sessões agendadas sem erro 500. 200 testes. |
| 2026-09-13 | 33 | ADR-057: trilha de auditoria (F-05) para dado do paciente e, depois, prontuário — visualizar, criar, alterar, excluir e exportar; guarda campos, nunca valores; só acrescenta, com `UPDATE`/`DELETE` revogados do papel da requisição. Tela de histórico na ficha. Lixeira vem com o prontuário; P-72 (Google) adiada. 215 testes. |
| 2026-09-15 | 34 | Avaliado o protótipo `prontuario-exyo` (P-18): não embutir, aproveitar ideias — 5 perguntas guiadas, caderno privativo de supervisão, PDF/DOCX no padrão CFP. ADR-058: construir do mais simples ao mais complexo, **IA por último**; P-18 e P-19 adiadas. |
| 2026-09-15 | 35 | Primeiro teste do produto pelo usuário. ADR-059 (vencimento é dia do mês), ADR-060 (a consulta só existe quando o psicólogo cadastra: realizada, falta cobrada ou falta remarcada; previsão calculada, nunca gravada; sai a remarcação e o "cobro falta") e ADR-061 (painel com sessões, receita e situação de cada paciente). Semente corrigida para contas com atendimento. 227 testes. |
| 2026-09-15 | 36 | ADR-062 (financeiro básico): pagamento por paciente e mês de referência, pagamento a mais é só mais um registro (sai o crédito automático), mensalidade sempre cheia e dia combinado de pagamento para todo paciente (revisa a 059). Aberta a P-73: de que mês são as sessões que o dia combinado cobra. |
| 2026-09-15 | 37 | ADR-063 (revisa a 062): mensalidade vence numa data do mês — dia fixo ou dia útil —, e quem paga por sessão tem um pagamento pendente por sessão. Lembrete no vencimento, que não aparece se o pagamento vier antes; forma de pagamento obrigatória. Abertas P-74 (dia útil), P-75 (várias sessões num pagamento) e P-76 (falta cobrada gera pendência). |
| 2026-09-15 | 38 | P-74 a P-76 fechadas: dia útil é seg–sex sem feriado nacional; quem acerta várias sessões é mensalidade; falta cobrada gera pendência. **Financeiro básico no ar** (app `financeiro`): devido calculado por mês e por sessão, registro de pagamento com forma obrigatória, lembrete de pendência no financeiro e no painel. Calendário de feriados nacionais em `core.calendario`. 264 testes. |
| 2026-09-15 | 39 | Definições do painel fechadas (recebido é o referente ao mês; dias sem sessão desde a última realizada; por sessão numa linha só). **Painel novo no ar**, no app `indicadores`: sessões feitas × que faltam, receita recebida × a receber, e cada atendimento em curso com situação, dias sem sessão, sessões e financeiro do mês. `core` volta a não importar domínio. 274 testes. |
| 2026-09-18 | 45 | O usuário enviou o **Manual Orientativo do CFP (2025)**, lido na íntegra; os fatos que pesam em decisão nossa foram para a seção 5. ADR-075 (**prontuário com "Editar"**: sem motivo e sem falar em versão na tela; por baixo, a versão anterior continua congelada) e ADR-076 (**aba de documentos psicológicos**, app `documentos`: cinco modalidades da Res. 06/2019 e três termos de apoio, em branco, com a orientação do CFP e a ajuda de cada campo escritas com palavras nossas; rascunho → emitido com cópia congelada por model e gatilho; sugestão só de identificação e assinatura, nunca dado clínico; impressão e PDF pelo navegador — revisa as ADRs 032 e 034). ADR-077, no mesmo dia: **o documento se preenche dentro dele** — a tela é a folha, cada espaço é um campo, e a folha de preencher e a impressa saem do mesmo gabarito. Aberta a P-80: a estrutura mínima do prontuário da Res. 01/2009. 407 testes. |
| 2026-09-18 | 46 | Pedido do usuário: salvar em PDF e DOCX, e o prontuário no mesmo desenho da aba de documentos. ADR-078 (**PDF e DOCX** por `core.exportacao`, com `reportlab` e `python-docx`; rascunho sai marcado; exportar entra na trilha) e ADR-079 (**prontuário na forma da Res. CFP 001/2009**: folha por paciente com as quatro partes, orientação do CFP ao lado, administrativo pré-preenchido, `FichaDoProntuario` só-acréscimo com gatilho e RLS). Fecha a P-80; abre a P-84 (registro documental restrito). |
| 2026-09-18 | 47 | Correção do usuário sobre a ADR-079: são **dois prontuários**, e juntos confundem. ADR-080 — a aba Prontuários fica só com os **registros de sessão**; o **prontuário geral** vai para a aba Documentos, com a evolução **montada** a partir de todos os registros confirmados e somente leitura. `documentos` passa a ler `prontuarios`, sem ciclo. Abre a P-85 (registrar a entrega da cópia). |
| 2026-09-18 | 48 | ADR-081: **link de cadastro** — o paciente preenche os próprios dados numa tela pública, e a resposta espera no convite até o psicólogo revisar e salvar pelo "Novo paciente". Só o hash do token no banco, uso único, 7 dias; `hamilton_web` enxerga uma linha e atualiza duas colunas. Cadastro ganhou nome social, documento estrangeiro, estado civil, gênero, raça/cor, profissão, país e contatos de emergência. Corrigido: CPF repetido dava erro de servidor. Abre P-86 e P-87. |
| 2026-09-18 | 49 | Duas correções do usuário sobre o link de cadastro. ADR-082: **endereço obrigatório** na tela do paciente; e **fora do Brasil tudo se escreve à mão** — sem máscara nem busca de CEP, sem DDD, sem lista de UF. O formato de telefone e CEP passou a depender do país (`Paciente.clean`), com `estado_exterior` em texto livre. Antes disto, quem mora fora não conseguia se cadastrar. |
| 2026-09-18 | 50 | Lote grande do usuário. ADR-083 (**despesas em texto livre** — a mensal é uma linha, a ocorrência é cálculo, "paguei" é a baixa do mês — e **fluxo de caixa** por competência; o financeiro virou três abas), ADR-084 (**aba Estatísticas** com o resultado previsto do ano e o retrato dos atendimentos; **frequência e situação financeira na ficha**, via template tag de `indicadores`; **aniversariantes** no painel) e ADR-085 (**anamnese** opcional e editável, no app `prontuarios`). A semente ganhou meses de história: sessões, pagamentos, registros de sessão, despesas do ano, anamneses. Abre P-88 e P-89. **Achado:** com o histórico, o painel levava 43 s — ADR-086, o financeiro passou a ler em lote (222 → 44 consultas). |
| 2026-09-18 | 51 | Discussão sobre onde mora o prontuário geral (ficha do paciente recomendada; decisão pendente) e sobre a separação entre registro de sessão e prontuário geral (escreve-se em dois lugares, lê-se em um). ADR-087: **estatísticas abrem no mês**, ano no botão de cima; no mês, todos os pacientes em atendimento aparecem, com "sem sessão no mês". |
| 2026-09-18 | 52 | ADR-088: **navegação** — barra lateral que abre com os nomes ao passar o mouse (e faixa horizontal no celular), caminho clicável no topo (seção › página), sub-abas do paciente que acompanham o paciente em registros de sessão, prontuário geral e documentos. |
| 2026-10-01 | 77 | **O sistema fica pronto para outras pessoas usarem.** ADR-113: achado auditando — a tabela dos bytes de arquivo, criada na véspera, estava sem RLS, e um `SELECT` cru devolvia o contrato de todos os psicólogos; a policy passa a perguntar o dono ao metadado, com teste em SQL cru dos dois lados. ADR-114: `ACESSO_LIBERADO` destranca o sistema sem plano nem prazo (o usuário decidiu que não haverá assinatura nem teste de 7 dias nesta fase); nasce **recuperação de senha**, que não existia e trancava para sempre quem esquecesse; entra **freio de login** por e-mail e por IP; entra **teto mensal de IA por conta**, porque a chave é uma só e quem paga é quem hospeda; e entram `render.yaml`, `build.sh` e `Procfile`, com duas `DATABASE_URL` — a da aplicação sem BYPASSRLS, a do dono só para migrar. |
| 2026-10-01 | 76 | **O psicólogo guarda no Hamilton o que fez fora dele.** ADR-112: a aba de Documentos do paciente passa a receber contrato terapêutico, autorização, anexo de avaliação e encaminhamento de outro profissional — PDF, JPG ou PNG até 10 MB, em bytes no Postgres (ADR-019), numa tabela à parte dos metadados para a listagem não carregar os bytes. O formato é decidido pela **assinatura dos bytes**, não pelo que o navegador diz, e o nome do arquivo é reescrito antes de ir para o cabeçalho de download. Entra a marca de **acesso exclusivo** do inciso V. Fecha D-01, D-02 e D-04, abertas desde a Rodada 9; adia a lixeira e o versionamento da D-03. É o primeiro upload de arquivo do sistema, e a validação mora no serviço porque o comprovante de despesa (N-06) vai pedir a mesma peça. |
| 2026-09-30 | 75 | **A IA entra no registro de sessão.** ADR-111: o psicólogo grava um áudio só respondendo a quatro pontos, o Whisper transcreve, o **código** troca por `[nome omitido]` todo nome que o sistema conhece — paciente, nome social, responsáveis legais e o próprio psicólogo —, e só então a síntese é pedida. A identificação do documento continua montada por código, como já era; o bloco de identificação que o `prontuario-exyo` pedia ao modelo saiu do prompt. Nasce desligada, com interruptor em Configurações. O áudio e a transcrição não são guardados, o que **revoga a R-14** e a parte da ADR-042 que os mantinha como prova de autoria. Baseado no `prontuario-exyo`, de Arthur Pinho, com autorização. |
| 2026-09-27 | 74 | **A abordagem volta a ser catálogo, e o visual fica terroso.** ADR-107: abordagens e outras áreas viram **lista fechada guardada por código** — texto livre não conta, e contar quantos usam cada abordagem era o pedido; "Outra" com campo escrito garante que ninguém trave no cadastro, e avaliação neuropsicológica sai das abordagens (é área) para não ser contada duas vezes; a migração 0012 converte o que já estava escrito sem perder ninguém. ADR-108: **direção terrosa** (fundo pêssego, acento terracota, tipografia Bitter com os números na própria letra), que revoga a Prancheta da ADR-089; ícones da barra redesenhados à mão; caixa alta sai dos selos. ADR-109: **pacientes em blocos**, com a frequência em cor e a carga em lote. ADR-110: os quatro estados da agenda passam a se distinguir de relance — ΔE medido de 7,7 para 31,6 entre "prevista" e "a cadastrar". |
| 2026-09-20 | 53 | Redesenho. Diagnóstico do frontend e exploração de quatro direções estéticas do painel, fora do app (`../design-exploration/`). O usuário escolheu a **Prancheta**. ADR-089: tema único em `components/_tema.html` (IBM Plex Sans + Mono, marinho e cobalto, 13 px, raio de 2 px, sem sombra), hierarquia por peso e não por caixa colorida, próxima sessão do dia destacada no painel; agenda e login dentro da paleta. |
| 2026-09-20 | 54 | ADR-090: o tema ficou pálido e parado no primeiro uso — **mais saturação** (acento, situações, agenda, fundo), **alvos de clique maiores** e **resposta a todo gesto** (acende ao passar, afunda ao clicar, anel de foco luminoso). Sombra continua sem separar blocos; brilho passa a marcar ação e gesto. |
| 2026-09-20 | 55 | ADR-091: três refinamentos de interação **globais** — card de navegação (borda nítida, texto mais forte, `scale(1.02)`), **entrada de página** em CSS (a navegação recarrega a página; 220 ms, três regiões, moldura parada) e **linha inteira** reagindo e clicável (fundo de 7% da cor principal + filete). Conferido com Playwright, inclusive sem JavaScript e com menos movimento; o âmbar reprovava em contraste e o token foi corrigido. |
| 2026-09-20 | 56 | A semente monta um **dia de exemplo** no painel, relativo ao dia em que roda (o que passou vira sessão cadastrada; o que vem sai de três pacientes com frequência no dia da semana de hoje). ADR-092: **financeiro do mês numa tabela só** — data, forma, observação e o desfazer do pagamento foram para dentro da cobrança; pendentes primeiro, com filete; filtros com contagem; aviso do que entrou de outros meses. |
| 2026-09-20 | 57 | ADR-093: o campo **"valor desta sessão" só na avulsa**. Sessão da frequência e data nova de remarcação não perguntam valor — por sessão, a cobrança nasce sozinha da condição; na mensalidade, não gera cobrança nova. No lugar do campo, a tela diz o que vai acontecer no financeiro. |
| 2026-09-20 | 58 | ADR-094: **cadastro do psicólogo em três tempos** — conta só com login e CRP, escolha entre **assinar ou testar grátis 7 dias** (revoga o "sem teste" da ADR-036), e o quiz já dentro do sistema, com **abordagens escritas à mão** (mais de uma), outras áreas de atuação, PF/PJ como chave da nota fiscal e endereço só para o presencial. Nasce o app `assinaturas`, com pagamento **simulado** fora de produção; o Asaas de verdade continua na S-01. Abertas P-91 a P-94. |
| 2026-09-20 | 59 | Correção apontada pelo usuário: **o CPF era recusado no quiz "por causa dos pontos"**. O campo saía com `maxlength="11"` (o tamanho do número puro no banco) e, com a máscara, o CPF tem 14 caracteres: o navegador cortava a digitação e chegavam 9 números. Valia para CPF, CNPJ e CEP em **todo** o sistema. Corrigido na raiz — `LimpaMascara` tira o limite dos campos mascarados, e o script de máscara do `base.html` faz o mesmo. Lição de conferência: o `fill()` do Playwright ignora `maxlength`; tela com máscara se confere digitando tecla por tecla. |
| 2026-09-20 | 60 | ADR-095: **o horário de atendimento se escolhe no cadastro do paciente**. O usuário percebeu que o paciente cadastrado não aparecia na agenda: a frequência só se definia numa tela à parte. Agora "Novo paciente" tem o bloco de horário, com os horários livres da aba Horários (menos os já ocupados), a opção de outro horário e a de paciente sem horário fixo. Tudo numa transação: horário ocupado não grava nem o paciente. `pacientes.cadastro` é o encaixe que mantém a dependência `atendimentos` → `pacientes`. |
| 2026-09-20 | 61 | Correção apontada pelo usuário na ADR-095: **o dia da semana e o horário não apareciam** ao abrir o cadastro — o bloco escondia tudo até a frequência ser marcada. Agora os dois campos ficam sempre à vista, e os horários livres viraram atalhos que os preenchem (o que coincide com os campos fica aceso). Lição: esconder campo obrigatório atrás de outra escolha faz o usuário concluir que ele não existe. |
| 2026-09-21 | 63 | ADR-096: **os documentos produzidos sobre o paciente ficam à vista no perfil dele**. O vínculo já existia, mas a sub-aba Documentos da ficha era a aba geral com filtro — o arquivo do paciente ficava no fim da página, depois de todos os modelos, e as sub-abas no meio. Agora abre com "Documentos de <paciente>" e só depois oferece os modelos. (Rodada 62: teste de ponta a ponta do horário livre dando lugar ao atendimento na agenda.) Também nasce `ligar-hamilton.bat` na raiz do workspace: o servidor local passa a rodar em janela própria, fora da sessão do Claude. |
| 2026-09-27 | 64–68 | Cinco frentes de uma vez. ADR-097 (**cantos arredondados** em escala, sem `overflow` que comesse o menu do financeiro); ADR-098 (**Agenda e Horários numa seção só**, horários como sub-aba); ADR-099 (**categoria do carnê-leão na despesa**, levantada na Receita Federal e no RIR/2018 — com "confirme com a contabilidade" onde a norma não decide, e total dedutível separado do que saiu do caixa); ADR-100 (**Configurações**: despesas opcionais desde o quiz, e troca PF↔PJ com data e histórico); ADR-101 (**anamnese por blocos**: o roteiro virou dado do psicólogo, com migração que preserva o que já estava escrito). Abertas P-95 a P-97. |
| 2026-09-27 | 70 | ADR-102: a ficha do paciente passa a ter **quatro sub-abas** — "Registros de sessão" vira **Prontuário**, e o **prontuário geral** deixa de ter aba própria para ser o primeiro cartão de Documentos. **Documentos sai da barra lateral**: todo documento é sobre um paciente, e a barra precisa caber na faixa do celular. As sub-abas subiram para o topo da ficha, onde no celular estavam soterradas. |
| 2026-09-27 | 71 | ADR-103: **a aba de Estatísticas desaparece** e cada bloco vai para a tela de que ele fala — presença e atendimentos em curso no painel, horário/dia/frequência na agenda, presença por paciente em Pacientes, resultado previsto no Financeiro. Todos respondem por mês ou por ano, com o mesmo seletor (`indicadores/periodo.py`), que preserva os filtros já aplicados. `montar()` virou quatro funções, para cada tela pagar só pelo que mostra. |
| 2026-09-27 | 72 | ADR-104 (**pendências em resumo**: "25 sessões esperando cadastro" numa linha que abre a lista com `<details>`, sem script) e ADR-105 (**a conta sobe para o topo**: o nome leva ao perfil e mostra um balão "Meu perfil", a engrenagem leva a Configurações, e o sair passa a morar lá). A barra lateral vai de nove entradas a **cinco**. O balão precisou ficar fora do fluxo: trocar o nome pela dica mudava a largura do topo e fazia o alvo do clique fugir do cursor. |
| 2026-09-27 | 73 | ADR-106: três acertos pedidos pelo usuário. A agenda passa a **distinguir pela cor** a sessão prevista (palha) da que passou sem cadastro (âmbar); o painel perde o card **pacientes ativos**, que repetia "atendimentos em curso"; e a lista de pendências deixa de rolar para o lado — a causa era a margem negativa que o tema dá a todo item de lista, recortada pelo container. |
| 2026-09-17 | 44 | Terceiro teste do usuário. ADR-072 (**painel diz cada coisa uma vez**: um bloco só de pendências; "dias sem sessão" retirado por completo; a agenda do painel é só o dia) e ADR-073 (**agenda em formato de calendário**, no desenho da planilha do psicólogo: colunas por dia, cartões `NOME - 14H`, `LIVRE - 8H` só onde há horário cadastrado, segunda a sexta com fim de semana sob demanda, visões de dia, semana e mês). Semente com 12 pacientes e grade realista. 361 testes. |
| 2026-09-17 | 43 | ADR-070 (**valor desta sessão**: campo opcional na consulta que cobra à parte a extra do mensalista e a sessão de quem não tem valor combinado; paciente infrequente já era coberto pela avulsa) e ADR-071 (**quiz de cadastro** em quatro passos — conta, regime, abordagem e formas de atendimento, clínica —, cada um gravando o que coleta; `CadastroCompletoMiddleware` tranca o sistema até o fim; endereço só para quem atende presencialmente; tudo editável no perfil). Fecha a P-77. 357 testes. |
| 2026-09-16 | 41 | ADR-065: **cinco situações da sessão** — presente, faltou sem avisar, cliente cancelou, profissional cancelou, remarcada —, com a sessão **presumida confirmada** (nada a clicar antes) e a cobrança decorrendo da situação; só o cancelamento do cliente admite desmarcar. **Modalidade** online × presencial com padrão no paciente e ajuste por sessão. Agenda com filtro de período e de situação e o percentual de online. 310 testes. |
| 2026-09-17 | 42 | Segundo teste do produto pelo usuário. ADR-066 (máscara é da tela: CPF, CNPJ, telefone, CEP e valor formatados no navegador, banco com número puro; CEP busca o endereço no ViaCEP), ADR-067 (**regime PF/PJ e dados da clínica no perfil** — o regime decide os recursos fiscais adiante; PJ sem CNPJ é recusado; UF e validadores de endereço vão para `core.enderecos`), ADR-068 (**a remarcada diz para quando**: a data nova entra na agenda esperando cadastro, sem gravar consulta antes de acontecer) e ADR-069 (**o painel é a agenda de hoje**, com o que ficou para trás logo acima; "dias sem sessão" sai da lista e vira alerta de ritmo perdido). 338 testes. |
| 2026-09-15 | 40 | ADR-064: **prontuário escrito à mão no ar** (app `prontuarios`) — texto livre, um por participante de cada sessão realizada, rascunho, confirmação e correção em versão nova com motivo. Versão confirmada imutável no model e por gatilho no banco; trilha de auditoria; pendentes no painel, na ficha e na consulta. 297 testes. |
| 2026-10-02 | 79 | ADR-115: **a conta superusuária atravessa o isolamento em todas as tabelas**, a pedido do usuário e depois de o custo ser apresentado duas vezes. A trava é uma segunda variável de sessão (`hamilton.administradora`), e não uma função no banco: a primeira tentativa usou `SECURITY DEFINER`, foi referenciada por `ativar_rls` e passou a ser exigida por **todas** as migrações antigas — nenhum banco novo subia. O admin do Django passa a registrar 27 models. |
| 2026-10-02 | 80 | Oito defeitos relatados do uso real do sistema no ar. **Três não eram defeito**: o prontuário pendente já só aparecia depois de a sessão ser registrada como realizada, e todos os 30 campos do cadastro do paciente já eram editáveis. Os outros cinco, com a causa achada no banco de produção: ADR-116 (**a agenda abria na semana do calendário**, quase toda passado — paciente de segunda cadastrado numa sexta não aparecia em lugar nenhum, e o horário livre dele continuava livre; eram o mesmo defeito, e nenhum dos dois estava na lógica); ADR-117 (**cobrança ganha a situação do meio**: existe desde o dia 1º do mês, fica "a receber" até vencer e só então vira alerta — e o cadastro passa a avisar quando o paciente fica sem valor, que foi o caso real); ADR-118 (**o convite mandava `no-referrer`** e o envio morria em 403 de CSRF sob HTTPS nos navegadores que não mandam `Origin` — como o embutido do WhatsApp, por onde o link viaja). Mais a UF que estava num doze avos da linha e o botão de voltar que faltava no quiz. |
