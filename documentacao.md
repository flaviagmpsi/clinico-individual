# Documentação — Hamilton Individual

Registro da evolução e da arquitetura do projeto. Atualizado a cada rodada de planejamento.

---

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
| Fiscal do psicólogo | Recibo de pessoa física + regras do Carnê-Leão |

## 3. Arquitetura

### 3.1 Isolamento (multi-tenancy)
Decidido em **ADR-001**: banco compartilhado com o dono explícito em cada modelo, manager que
recusa query sem escopo, e Row-Level Security do PostgreSQL como camada final. O mecanismo de
supervisão / "view-as" do original é funcionalidade **proibida** aqui.

### 3.2 Apps Django
🔴 A definir.

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

---

## 4. Relação com o `hamilton-api`

Repositório de referência, clonado em `../hamilton-api`, **somente leitura**.

**O que aproveitamos:** a interface (layout, navegação, densidade de informação — ADR-004) e as
regras de negócio já validadas na prática: cálculo de dias sem atendimento, limiares
REGULAR / ATENÇÃO / CRÍTICO em 7 e 30 dias, `choices` de alta e desistência.

**O que não aproveitamos:** o schema legado (`db_table` em português, PKs `pk_*`, colunas
`fk_*`/`dat_*`/`vlr_*`, herdados de um banco anterior ao Django), a estrutura de dois apps com
`views.py` de 5.639 linhas, as migrations git-ignored, e toda a camada financeira (Stripe +
NFS-e WebmaniaBR), incompatível com Asaas + recibo de PF.

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
