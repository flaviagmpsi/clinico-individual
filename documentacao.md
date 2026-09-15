# Documentação — Hamilton Individual

Registro da evolução e da arquitetura do projeto. Atualizado a cada rodada de planejamento.

---

## ⚡ Estado do código — passos 0 e 1

> Para saber **o que falta construir**, o documento é [demandas.md](demandas.md). Este aqui
> registra o que existe e por quê.

**227 testes verdes contra PostgreSQL real, nenhum pulado.** A suíte roda em ~2,5 min num PostgreSQL 17 local; contra o Neon gratuito, a suspensão automática do banco derrubava a execução no meio.

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
