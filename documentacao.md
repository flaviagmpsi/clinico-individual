# Documentação — Hamilton Individual

Registro da evolução e da arquitetura do projeto. Atualizado a cada rodada de planejamento.

---

## 1. O que é

ERP para o **psicólogo clínico autônomo**. Um SaaS vendido individualmente: muitos psicólogos
usam a mesma aplicação, cada um com isolamento total dos seus dados.

Distinção em relação ao `hamilton-api` (sistema de origem): o Hamilton original gere uma
**clínica com vários terapeutas**, com coordenação, supervisão, match de paciente e plantão.
O Individual atende **um profissional sozinho**, replicado N vezes.

**Problema central:** devolver tempo ao psicólogo. A referência concreta é o prontuário —
hoje ~20 min de escrita após cada sessão.

**Requisito de produto herdado explicitamente:** a simplicidade da interface do Hamilton original.
Tela limpa, informação sem ruído, o usuário não se perde. Isso é requisito, não estética.

## 2. Stack

| Camada | Escolha |
|---|---|
| Backend | Django, organizado em apps modulares por domínio |
| Banco | Neon (PostgreSQL) |
| Deploy | Render |
| Cobrança da assinatura | Asaas (o psicólogo assinante paga o Hamilton) |
| Fiscal do psicólogo | Recibo de pessoa física + regras do Carnê-Leão |

## 3. Arquitetura

### 3.1 Isolamento (multi-tenancy)
Decidido em **ADR-001**: banco compartilhado com o dono explícito em cada modelo, manager que
recusa query sem escopo, e Row-Level Security do PostgreSQL como camada final. O mecanismo de
supervisão/"view-as" do original é funcionalidade **proibida** aqui.

### 3.2 Apps Django
🔴 A definir — depende de ADR-003.

### 3.3 Modelo financeiro
Decidido em **ADR-002**: modalidade de cobrança explícita por paciente (`MENSAL` ou
`POR_SESSAO`), com uma entidade de conta a receber que o original não possui.

---

## 4. Relação com o `hamilton-api`

Repositório de referência, clonado em `../hamilton-api`, **somente leitura**.

**O que aproveitamos:** regras de negócio já validadas na prática (cálculo de dias sem
atendimento, limiares REGULAR/ATENÇÃO/CRÍTICO em 7 e 30 dias, `choices` de alta e desistência),
os templates das telas aprovadas e o aprendizado de onde o sistema dói.

**O que não aproveitamos:** o schema legado (`db_table` em português, PKs `pk_*`, colunas
`fk_*`/`dat_*`/`vlr_*`, herdados de um banco que existia antes do Django), a estrutura de dois
apps com `views.py` de 5.639 linhas, as migrations git-ignored, e toda a camada financeira
(Stripe + NFS-e WebmaniaBR), incompatível com Asaas + recibo de PF.

---

## 5. Log de evolução

| Data | Rodada | O que ficou decidido |
|---|---|---|
| 2026-09-08 | Setup | Repositórios clonados, artefatos criados, Grill-Me configurado como padrão do projeto. |
| 2026-09-08 | 1 | ADR-001 (isolamento total) e ADR-002 (modalidade de cobrança) aceitas. ADR-003 (projeto novo vs. fork) reaberta para reformulação. |
