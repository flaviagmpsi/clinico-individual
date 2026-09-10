# Contexto de geração de código — Hamilton Individual

Este arquivo é a instrução definitiva para escrever o código do projeto. Ele condensa 22 rodadas
de planejamento registradas em [complicacoes.md](complicacoes.md) (ADRs), [demandas.md](demandas.md)
(User Stories) e [documentacao.md](documentacao.md) (arquitetura).

> **Regra de ouro:** quando este arquivo e uma ADR discordarem, **a ADR vence** — ela tem o
> contexto e o porquê. Este arquivo é resumo operacional, não fonte da verdade.

---

## 1. O que estamos construindo

ERP para o **psicólogo clínico autônomo do mercado**. Um SaaS: muitos psicólogos, **sem vínculo
entre si**, usam a mesma aplicação,
cada um com isolamento total dos seus dados. ⚠️ **Não é produto da Allos nem para a Allos** — o
`hamilton-api` é referência de domínio e de interface, e nada mais. Ele gere uma
clínica com vários terapeutas, com coordenação e supervisão; aqui **não existe supervisor, e cada
assinante é uma ilha**.

**Problema central:** devolver tempo ao psicólogo. A referência é o prontuário — hoje ~20 minutos
de escrita após cada sessão.

**Requisito de produto, não estético:** a interface é simples, limpa e densa em informação útil.
O usuário não se perde. Herdado do Hamilton original (ADR-004).

## 2. Stack

| Camada | Escolha |
|---|---|
| Backend | Django, apps modulares por domínio |
| Banco | Neon (PostgreSQL), com Row-Level Security |
| Deploy | Render — ⚠️ **disco efêmero**, `MEDIA_ROOT` some a cada deploy |
| Arquivos grandes | Object storage (áudio) |
| Arquivos jurídicos | Bytes no Postgres (contrato, PDF, comprovante) |
| Assinatura | Asaas — cartão e PIX Automático |
| IA | Atrás de adaptador. O domínio não conhece provedor |

---

## 3. Regras inegociáveis

Violá-las não é bug de estilo, é falha de projeto.

### 3.1 Isolamento entre psicólogos (ADR-001)
Prontuário é dado sensível de saúde sob sigilo profissional. **Nenhum psicólogo alcança dado de
outro, em nenhuma hipótese.** Três camadas:

1. Toda model de domínio herda `TenantOwnedModel`, com o dono explícito.
2. `TenantManager` é o manager padrão e **levanta exceção** se a query rodar sem escopo definido.
   Uma query insegura quebra em teste, não vaza em produção.
3. **Row-Level Security** no Postgres, com policy amarrada a variável de sessão setada por
   request. Nem SQL cru atravessa.

⚠️ O mecanismo de supervisão / "view-as" do `hamilton-api` é **funcionalidade proibida** aqui.

### 3.2 O sistema não se comunica com pacientes (ADR-039)
Sem portal do paciente, sem login do paciente, sem envio automático, sem link compartilhável.
O único destinatário de qualquer coisa que sai do sistema é **o próprio psicólogo**.
Toda feature que proponha falar com o paciente precisa revogar esta ADR antes de existir.

### 3.3 O prontuário é peça de defesa legal (ADR-005)
A Res. CFP 001/2009, Art. 4º, §2º o define como meio de prova em processo disciplinar. Portanto:
versão congelada na confirmação, trilha de auditoria de quem escreveu o quê e quando, e
**rascunho obrigatório** — texto de IA nunca vira registro oficial sem confirmação humana explícita.

### 3.4 A IA fica atrás de um adaptador
O domínio conhece "transformar relato em prontuário". Não conhece provedor, modelo nem chave de
API. É o que permite trocar de provedor ou plugar uma IA existente sem tocar em regra de negócio.

---

## 4. Estrutura de apps

Dez apps. A fronteira é **quem é dono do dado**, nunca em que tela ele aparece.

| App | É dono de |
|---|---|
| `core` | `TenantOwnedModel`, `TenantManager`, middleware de RLS, trilha de auditoria. **Nenhum domínio** |
| `contas` | `User`, `Psicologo` (CRP, CPF, regime PF/PJ, padrões, dados fiscais opcionais). Raiz do tenant |
| `pacientes` | `Paciente`, `Caso`, `ResponsavelLegal`, `Pagador` |
| `agenda` | `HorarioDisponivel`, `Recorrencia`, integração Google Agenda |
| `atendimentos` | `Consulta`, `Desfecho` |
| `prontuarios` | `Relato`, `Prontuario`, versões, exportação |
| `documentos` | `Documento` (contrato, anexo de avaliação, cópia emitida), IA de documentos |
| `financeiro` | `ContaReceber`, `Pagamento`, `Despesa`, `TipoDespesa` |
| `assinaturas` | Ciclo de vida da conta, Asaas, exportação e descarte |
| `indicadores` | Painel e análise. **Só leitura** |

### Regras de dependência
1. `core` não depende de ninguém; todos dependem dele.
2. `indicadores` depende de todos; **ninguém depende de `indicadores`**.
3. `assinaturas` **não toca dado clínico** — sabe se a conta está ativa, não o que há dentro.
4. `prontuarios` depende de `atendimentos`; nunca o contrário.
5. Sem dependência circular entre apps de domínio. Se dois precisam conversar nos dois sentidos,
   a conversa sobe para uma camada de serviço.

---

## 5. Modelo de domínio — o que não é óbvio

### `Caso` é a unidade de atendimento (ADR-026)
O vínculo terapêutico, com 1..N pacientes.

| Pertence ao `Caso` | Pertence ao `Paciente` | Pertence à `Consulta` |
|---|---|---|
| Valor acordado, modalidade de cobrança | Dados pessoais, CPF, endereço | Data, hora, duração, estado |
| Recorrência | Responsável legal | `contabilizada` |
| Contrato, pagador | Prontuário (um por paciente, por sessão) | Conta a receber |

**Uma forma só no banco, duas formas na tela.** Cadastrar paciente individual cria um caso de um,
em silêncio. A palavra "Caso" só aparece para quem atende casal. A **pessoa é única** entre
atendimentos — Maria em terapia individual e Maria no casal são o mesmo cadastro.

### Consulta: comparecimento e cobrança são eixos independentes (ADR-023)

| Eixo | Campo | Dispara |
|---|---|---|
| Comparecimento | `estado`: `AGENDADA` / `REALIZADA` / `FALTA` / `CANCELADA` | `REALIZADA` → **prontuário pendente** |
| Cobrança | `contabilizada` (bool) | verdadeiro → **conta a receber** |

A independência é o que cobre falta cobrada (cobrança sem prontuário) e sessão de cortesia
(prontuário sem cobrança). Presença é registrada **por participante** — num casal, um pode faltar.

### Recorrência com exceção por ocorrência (ADR-022, ADR-031)
A **regra** ("toda terça 15h", com periodicidade semanal / quinzenal / mensal e âncora) gera
**consultas concretas**, materializadas numa janela contínua à frente. Cada ocorrência é editável
isoladamente e **lembra que foi alterada à mão** — sem essa marca, uma mudança futura na regra
desfaria a remarcação em silêncio. Alterar a regra oferece "só esta" e "esta e as próximas".
**"Todas" não existe:** reescreveria consultas passadas, que são registro ligado a prontuário e cobrança.

### Financeiro
Modalidade por caso: `MENSAL` (uma cobrança, vencimento no início ou no fim) ou `POR_SESSAO`
(uma cobrança por consulta contabilizada, cobrada logo após). Registros sempre **granulares** — o
agrupamento por paciente existe só na apresentação. O pagamento **dá baixa** numa cobrança, com
**parcial permitida**, deixando saldo visível.

### Ciclo de vida da conta (ADR-038)
`ATIVA` → `TOLERANCIA` (7d) → `SOMENTE_LEITURA` (30d) → `ARQUIVADA` (60d) → `DESCARTADA`.
Um mecanismo, dois gatilhos: inadimplência e cancelamento. Quem regulariza volta a `ATIVA` sem
perder nada.

---

## 6. Convenções de código

**Português no domínio**, como o original: nomes de models, campos, verbose names e interface.
Termos técnicos de framework permanecem em inglês.

### ❌ Não portar do `hamilton-api`
| Prática do original | Aqui |
|---|---|
| `db_table` explícito em português (`pacientes`, `avaliação` com acento) | Deixar o Django nomear |
| PKs customizadas (`pk_paciente`, `pk_consulta`) | `id` padrão |
| Prefixos `fk_*`, `dat_*`, `vlr_*`, `is_*` nas colunas | Nomes diretos: `paciente`, `data`, `valor`, `ativo` |
| Migrations git-ignored (exigem `git add -f`) | **Migrations versionadas** |
| `views.py` de 5.639 linhas misturando HTML e API | Views curtas; regra de negócio em serviços |
| `Consulta` com só data, sem hora | Data, hora **e** duração |
| Valor devido = preço de uma sessão, ignorando quantas houve | Cobrança sobre registros reais |
| Último pagamento do mês em vez da soma | Saldo = devido − baixas |
| IDs mágicos no código (o terapeuta `73` do original) | Nunca |

### ✅ Portar deliberadamente
- Cálculo de dias desde o último atendimento e limiares **REGULAR / ATENÇÃO / CRÍTICO** (7 e 30 dias).
- `choices` de alta e desistência.
- A **interface**: layout, navegação, densidade, organização das abas (ADR-004).
- A tela `gerenciar_horarios`.
- Campos do registro de pagamento — menos o de terapeuta, que aqui é ruído.

### Estilo
- Clean Code: funções curtas, nome que diz o que faz, sem comentário que repete o código.
- **Comentário explica *por quê*, nunca *o quê*.** O `hamilton-api` faz isso bem em
  `principais/contratos/LEIA-ME.md` e nas docstrings de `ContratoPaciente` — usar como referência
  de tom.
- Regra de negócio em camada de serviço, não em view nem em model gordo.
- Validação no model (`full_clean()` no `save()`, como o original faz) para que a regra valha
  independentemente de onde o dado entra.

---

## 7. Princípios do produto

Emergiram das decisões e valem para features futuras.

1. **Configura uma vez, ajusta na exceção** (ADR-025). Toda preferência tem padrão no perfil do
   psicólogo e é sobrescrita no nível mais específico. Nunca perguntar de novo o que já foi
   respondido. A tela deve mostrar **de onde veio** o valor herdado.
2. **Degradar com honestidade** (ADR-012). Feature que precisa de dado que o usuário não tem à mão
   funciona com o que sabe e **declara o que não sabe**. Nem bloquear, nem chutar.
3. **A complexidade fica onde é barata** — no modelo, não na frente do usuário (ADR-026).
4. **Dono do dado e lugar na tela são coisas diferentes.** A tela pode reunir o que o modelo separa.
5. **Restrição estrutural vence instrução** (ADR-034). Se a IA não pode usar um dado, não entregue
   o dado. Instruir o modelo a se comportar não é garantia.
6. **A análise usa apenas dado administrativo** (ADR-027). Nunca conteúdo de prontuário.

---

## 8. Armadilhas conhecidas

| # | Armadilha | Onde dói |
|---|---|---|
| I-01 | **RLS + pooling do Neon**: a variável de sessão precisa ser setada por request e **limpa** ao devolver a conexão, ou uma request herda o tenant da anterior | Vazamento entre psicólogos |
| I-04 | **Disco do Render é efêmero** | Arquivo salvo em `MEDIA_ROOT` some no próximo deploy |
| I-06 | **Asaas, cartão**: `PAYMENT_RECEIVED` só chega **32 dias** após `PAYMENT_CONFIRMED` | Liberar acesso em `RECEIVED` bloqueia quem já pagou, por um mês |
| — | Escrever evento no Google exige **permissão de escrita**, pedida só quando o psicólogo ativar o recurso | Abandono no OAuth |
| — | Materializar recorrência **não** pode criar prontuário pendente nem cobrança de sessão futura | O gatilho é `REALIZADA`, não o agendamento |

---

## 9. Conformidade — o que a norma exige

| Norma | Exigência | Onde vive |
|---|---|---|
| Res. CFP 001/2009, Art. 2º | Estrutura do prontuário: identificação · demanda e objetivos · **evolução e procedimentos** · encaminhamento/encerramento · anexos de avaliação em pasta **exclusiva do psicólogo** · cópias de documentos emitidos com data, finalidade e destinatário | `prontuarios`, `documentos` |
| Res. CFP 001/2009, Art. 4º | Guarda mínima de **5 anos** | `assinaturas` (ADR-038) |
| Res. CFP 001/2009, Art. 5º, III | Atendimento em grupo: **documentação individual de cada usuário** | `prontuarios` (ADR-028) |
| Res. CFP 06/2019, Art. 9º, §1º | 🚫 Declaração **não pode** registrar sintomas, situações ou estados psicológicos | `documentos` (ADR-034) |
| Res. CFP 06/2019 | Relatório: 5 itens (identificação, demanda, procedimento, análise, conclusão) | `documentos` |
| Res. CFP 06/2019, Art. 17 | Prazo de validade do conteúdo no **último parágrafo** | `documentos` |
| Receita Federal | Desde 01/2025, recibo de psicólogo PF só pelo **Receita Saúde** | Lembrete apenas (ADR-030) |
| LGPD art. 11 | Prontuário é dado sensível de saúde | ADR-001, ADR-039 |

---

## 10. Passo a passo de construção

### Passo 0 — A prova de conceito do isolamento
**O primeiro código do projeto não é feature nenhuma.** Antes de qualquer model de domínio:

1. `TenantOwnedModel` e `TenantManager` que levanta exceção sem escopo.
2. Middleware que seta e **limpa** a variável de sessão do tenant, com pooling do Neon ligado.
3. Policy de RLS no Postgres.
4. **Teste que prova o vazamento impossível**: dois psicólogos, um tentando ler o dado do outro
   por ORM, por `.raw()` e por query sem escopo. Os três precisam falhar.

Se o passo 0 não fechar, nada mais deve ser escrito — o produto inteiro se apoia nele.

### Passos seguintes
| Ordem | App | Por quê |
|---|---|---|
| 1 | `contas`, `pacientes` | Sem dono e sem paciente, nada existe |
| 2 | `agenda`, `atendimentos` | A consulta é a âncora de tudo o mais |
| 3 | `prontuarios` | A razão de o produto existir |
| 4 | `financeiro` | Depende de consulta contabilizada |
| 5 | `documentos` | Independente; pode ir em paralelo a partir do passo 2 |
| 6 | `indicadores` | Por último, porque só lê |
| 7 | `assinaturas` | Necessário para vender, não para validar |

### Testes obrigatórios, por app
- **`core`** — isolamento, nas três camadas.
- **`agenda`** — remarcação avulsa que sobrevive a mudança na regra; quinzenal com âncora.
- **`atendimentos`** — as cinco combinações de estado × `contabilizada` (ADR-023).
- **`financeiro`** — baixa parcial deixando saldo correto; cobrança de casal indo ao pagador do caso.
- **`documentos`** — a IA de Declaração **não recebe** conteúdo de prontuário.
- **`assinaturas`** — a máquina de estados, incluindo o retorno de inadimplente a `ATIVA`.

---

## 11. Fora do MVP

Não construir, não deixar gancho pela metade. Cada um tem ADR explicando por quê.

| O quê | ADR |
|---|---|
| Carnê-leão (CSV do Receita Saúde) e NFS-e por API | ADR-013 |
| Previsão de imposto | P-30 |
| Módulo de avaliação psicológica | ADR-034 |
| Atestado, Laudo e Parecer | ADR-034 |
| Relatório Multiprofissional | ❌ nunca |
| Assinatura eletrônica de contrato (Autentique) | ADR-015 |
| Lembrete por WhatsApp, e-mail ou push | ADR-018 |
| Férias, feriados e pausas em bloco | P-47 |
| Qualquer superfície voltada ao paciente | ADR-039 |

---

## 12. Antes de escrever código, ler

1. [complicacoes.md](complicacoes.md) — as 39 ADRs, com o porquê de cada decisão.
2. [demandas.md](demandas.md) — as User Stories, rastreáveis até a ADR de origem.
3. [perguntas.md](perguntas.md) — o que **ainda não** foi decidido. Se a tarefa esbarrar num item
   aberto, **perguntar**, não decidir sozinho.
4. `../hamilton-api/CLAUDE.md` — a arquitetura de referência. Ler para entender o domínio e para
   saber o que **não** repetir.
