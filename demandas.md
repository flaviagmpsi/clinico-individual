# Demandas — Hamilton Individual

Documento vivo. User Stories derivadas das decisões em [complicacoes.md](complicacoes.md).
Cada história é rastreável até a ADR que a originou — se a ADR mudar, a história muda.

**Legenda:** 🎨 Front · ⚙️ Back · 🗄️ BD · 🔒 Segurança/Compliance
**Estado:** ✅ especificada · 🟡 depende de decisão aberta · ⏸️ fora do MVP

---

## 0. Fundação — app `core`

> Como **plataforma**, preciso garantir que nenhum psicólogo alcance dado de outro,
> **em nenhuma hipótese** — porque o dado é prontuário, sob sigilo profissional e LGPD art. 11.

| # | História | Camada | Estado | ADR |
|---|---|---|---|---|
| F-01 | Toda model de domínio herda `TenantOwnedModel`, com o dono explícito | 🗄️ | ✅ | ADR-001 |
| F-02 | `TenantManager` é o manager padrão e **levanta exceção** se a query rodar sem escopo de dono | ⚙️🔒 | ✅ | ADR-001 |
| F-03 | Middleware seta a variável de sessão do tenant por request e a **limpa** ao devolver a conexão ao pool | ⚙️🔒 | 🟡 | ADR-001, I-01 |
| F-04 | Row-Level Security no Postgres, com policy amarrada à variável de sessão | 🗄️🔒 | 🟡 | ADR-001, I-01 |
| F-05 | Trilha de auditoria: quem escreveu, quando, o que mudou | ⚙️🔒 | ✅ | ADR-005 |
| F-06 | Teste que **prova** que uma query sem escopo falha, e que o RLS bloqueia acesso cruzado | ⚙️🔒 | ✅ | ADR-001 |

⚠️ **F-03 e F-04 exigem prova de conceito antes de virarem fundação** (I-01): com o pooling do
Neon, uma request pode herdar o tenant da anterior. É o primeiro código a ser escrito.

---

## 1. Conta e perfil — app `contas`

> Como **psicólogo**, quero configurar meus padrões uma vez e não responder a mesma pergunta a cada cadastro.

| # | História | Camada | Estado | ADR |
|---|---|---|---|---|
| C-01 | Cadastro e login; a conta é a raiz do isolamento | 🎨⚙️ | ✅ | ADR-001 |
| C-02 | Perfil com CPF, número do CRP e **regime tributário (PF ou PJ)** | 🎨🗄️ | ✅ | ADR-030 |
| C-03 | Padrões do psicólogo: duração da sessão (50 min), vencimento da mensalidade, cobro falta (sim/não) | 🎨🗄️ | ✅ | ADR-025 |
| C-04 | Toda tela de cadastro mostra **de onde veio** o valor herdado do perfil | 🎨 | ✅ | ADR-025 |
| C-05 | Dados fiscais **opcionais** (outras rendas, INSS, dependentes, pensão), fora do onboarding | 🎨 | ✅ | ADR-012 |

---

## 2. Pacientes e casos — app `pacientes`

> Como **psicólogo**, quero cadastrar quem eu atendo sem preencher campo que não uso.

| # | História | Camada | Estado | ADR |
|---|---|---|---|---|
| P-01 | Cadastro de paciente: nome, CPF, telefone, e-mail, endereço com CEP, nascimento, medicamento em uso | 🎨🗄️ | ✅ | escopo |
| P-02 | `Caso` criado **em silêncio** ao cadastrar paciente individual; a palavra não aparece na tela | ⚙️🗄️ | ✅ | ADR-026 |
| P-03 | Atendimento de casal ou família: um `Caso` com N pacientes | 🎨⚙️🗄️ | ✅ | ADR-026 |
| P-04 | A **pessoa é única** entre atendimentos: mesmo cadastro em terapia individual e de casal | 🗄️ | ✅ | ADR-026 |
| P-05 | **Pagador** separado do paciente, com o CPF do paciente como padrão; segundo campo só ao marcar "quem paga é outra pessoa" | 🎨🗄️ | ✅ | ADR-009 |
| P-06 | **Responsável legal** (1..N) com tipo de guarda registrado | 🎨🗄️ | ✅ | ADR-014 |
| P-07 | Valor acordado e modalidade de cobrança pertencem ao **caso**, não ao paciente | 🗄️ | ✅ | ADR-002, ADR-026 |
| P-08 | Acesso direto, do cadastro, aos prontuários já realizados e à contagem de sessões | 🎨 | ✅ | escopo |
| P-09 | Paciente nascido antes de 2018 pode não ter CPF: avisar, não bloquear | 🎨 | 🟡 | ADR-014, P-34 |

---

## 3. Agenda — app `agenda`

> Como **psicólogo**, meu atendimento é fixo quase sempre, mas vez ou outra remarca.

| # | História | Camada | Estado | ADR |
|---|---|---|---|---|
| A-01 | Recorrência por caso: dia, hora e **periodicidade** (semanal, quinzenal, mensal), com âncora | 🎨🗄️ | ✅ | ADR-022, ADR-031 |
| A-02 | Consultas materializadas em janela contínua à frente, empurrada ao abrir a agenda | ⚙️ | ✅ | ADR-022 |
| A-03 | Remarcação avulsa: altera **só aquela** ocorrência; a regra não é tocada | 🎨⚙️ | ✅ | ADR-022 |
| A-04 | A ocorrência remarcada **lembra que foi alterada à mão** e não é sobrescrita por mudança futura na regra | 🗄️ | ✅ | ADR-022 |
| A-05 | Alterar a regra oferece **"só esta"** e **"esta e as próximas"**. "Todas" não existe | 🎨 | ✅ | ADR-022 |
| A-06 | Consulta tem data, **hora e duração** (o original só tem data) | 🗄️ | ✅ | ADR-023 |
| A-07 | Colisão de horário **bloqueia** a marcação | ⚙️ | ✅ | ADR-024 |
| A-08 | Casal não dispara colisão: é uma consulta com dois participantes | ⚙️ | ✅ | ADR-026 |
| A-09 | Grade de horários declarada pelo psicólogo, com ocupação **derivada** — sem manutenção dupla | 🎨⚙️ | ✅ | ADR-029 |
| A-10 | Tela de horários como mapa da semana: o que está ocupado, por quem, e o que sobrou | 🎨 | ✅ | ADR-029 |
| A-11 | Férias, feriados e pausas em bloco | — | ⏸️ | P-47 |

### Integração com Google Agenda

| # | História | Camada | Estado | ADR |
|---|---|---|---|---|
| A-12 | OAuth com **leitura** na conexão; **escrita** pedida só ao ativar o recurso, com explicação na tela | 🎨⚙️ | ✅ | ADR-020 |
| A-13 | Consulta vira evento em calendário **dedicado** ("Hamilton — Atendimentos"), nunca no pessoal dele | ⚙️ | ✅ | ADR-020 |
| A-14 | Leitura da agenda para evitar marcação sobreposta | ⚙️ | ✅ | ADR-020 |
| A-15 | Evento movido no Google é **detectado** e o sistema oferece atualizar aqui | 🎨⚙️ | ✅ | ADR-020 |
| A-16 | Ensinar o psicólogo a ligar o "Resumo diário" do Google — é ele que faz o alerta matinal | 🎨 | ✅ | ADR-018 |

---

## 4. Atendimentos — app `atendimentos`

| # | História | Camada | Estado | ADR |
|---|---|---|---|---|
| T-01 | Consulta com estado: `AGENDADA`, `REALIZADA`, `FALTA`, `CANCELADA` | 🗄️ | ✅ | ADR-022 |
| T-02 | Campo `contabilizada`, **independente** do estado, com padrão vindo do perfil | 🎨🗄️ | ✅ | ADR-023 |
| T-03 | Presença registrada **por participante** — num casal, um pode faltar e o outro não | 🗄️ | ✅ | ADR-026 |
| T-04 | `REALIZADA` dispara **prontuário pendente**; `contabilizada` dispara **conta a receber** | ⚙️ | ✅ | ADR-016, ADR-023 |
| T-05 | Desfecho (alta ou desistência), com o número de sessões derivado, não perguntado | ⚙️🗄️ | ✅ | ADR-027 |

---

## 5. Prontuários — app `prontuarios`

> Como **psicólogo**, quero recuperar os ~20 minutos que gasto escrevendo prontuário depois de cada sessão.

| # | História | Camada | Estado | ADR |
|---|---|---|---|---|
| R-01 | Relato de origem em **áudio ditado** ou **texto escrito**, tratados como variações do mesmo insumo | 🎨⚙️ | ✅ | ADR-006 |
| R-02 | A sessão **nunca** é gravada; o único falante é o psicólogo | 🔒 | ✅ | ADR-006 |
| R-03 | IA estrutura o relato no formato do Art. 2º da Res. CFP 001/2009 | ⚙️ | ✅ | ADR-005 |
| R-04 | **Rascunho obrigatório**: revisão e confirmação explícita antes de virar registro oficial | 🎨 | ✅ | ADR-005 |
| R-05 | Versão congelada na confirmação, com trilha de auditoria — é meio de prova em processo disciplinar | ⚙️🔒 | ✅ | ADR-005 |
| R-06 | Sessão de casal: **um relato, um prontuário por participante**, gerados pela IA | ⚙️ | ✅ | ADR-028 |
| R-07 | A fala de um participante **não pode migrar** para o prontuário do outro | ⚙️🔒 | 🟡 | P-53 |
| R-08 | Exportação de uma sessão ou do histórico completo, em PDF ou DOC | 🎨⚙️ | ✅ | escopo |
| R-09 | IA atrás de **adaptador**: o domínio não conhece provedor, modelo nem chave | ⚙️ | ✅ | §3.2 |
| R-10 | Áudio descartado após aprovação do prontuário; retenção como política explícita | ⚙️🔒 | 🟡 | ADR-019, P-13 |
| R-11 | Direito de acesso do paciente ao próprio prontuário (Art. 5º, II) | — | 🟡 | P-11 |
| R-12 | Acesso do responsável legal: apenas o **estritamente necessário**, não o documento inteiro | — | 🟡 | P-32 |
| R-13 | Sigilo do adolescente perante os pais | — | 🟡 | P-33 |

---

## 6. Documentos — app `documentos`

| # | História | Camada | Estado | ADR |
|---|---|---|---|---|
| D-01 | `Documento` com arquivo, tipo, vigência, visibilidade e versões | 🗄️ | ✅ | ADR-021 |
| D-02 | Guarda do **contrato terapêutico** escrito pelo psicólogo, para conferência | 🎨⚙️ | ✅ | ADR-015 |
| D-03 | Alterar **cria versão**; apagar move para **lixeira**; exclusão definitiva só de dentro dela | 🎨⚙️ | ✅ | ADR-015 |
| D-04 | Anexos de avaliação psicológica em **pasta de acesso exclusivo do psicólogo** (inciso V) | 🗄️🔒 | ✅ | ADR-021 |
| D-05 | Cópias de documentos emitidos, com data, finalidade e destinatário (inciso VI) | 🗄️ | ✅ | ADR-021 |
| D-06 | **IA gera Declaração** — sem acesso ao prontuário, proibida de citar sintomas | ⚙️🔒 | ✅ | ADR-032, ADR-034 |
| D-07 | **IA gera Relatório Psicológico** — 5 itens: identificação, demanda, procedimento, análise, conclusão | ⚙️ | ✅ | ADR-032 |
| D-08 | Prazo de validade do conteúdo no **último parágrafo** (Art. 17) | ⚙️ | ✅ | ADR-032 |
| D-09 | Rascunho obrigatório também para documentos gerados | 🎨 | ✅ | ADR-034 |
| D-10 | Diretrizes do CFP consultáveis, com data da versão visível | 🎨 | ✅ | ADR-033 |
| D-11 | Atestado e Laudo | — | ⏸️ | ADR-034 |
| D-12 | Parecer Psicológico | — | ⏸️ | ADR-034 |
| D-13 | Relatório Multiprofissional | — | ❌ Fora | ADR-034 |

---

## 7. Financeiro — app `financeiro`

| # | História | Camada | Estado | ADR |
|---|---|---|---|---|
| N-01 | Modalidade por caso: `MENSAL` (uma cobrança, vencimento no início ou no fim) ou `POR_SESSAO` | 🎨🗄️ | ✅ | ADR-002 |
| N-02 | `POR_SESSAO` gera cobrança **por consulta contabilizada**, cobrada logo após | ⚙️ | ✅ | ADR-002, ADR-023 |
| N-03 | Registros permanecem **granulares**; o agrupamento por paciente existe só na apresentação | ⚙️🎨 | ✅ | ADR-002 |
| N-04 | Registro de pagamento: paciente, quem pagou, valor, data e observação. Sem campo de terapeuta | 🎨🗄️ | ✅ | ADR-035 |
| N-04a | Pagamento **dá baixa** numa cobrança, com **baixa parcial** permitida e saldo remanescente visível | ⚙️ | ✅ | ADR-035 |
| N-04b | **Forma de pagamento** opcional: PIX, dinheiro, transferência, cartão | 🎨🗄️ | ✅ | ADR-035 |
| N-04c | Listagem com busca, filtro por mês e ordenação, portadas do original | 🎨 | ✅ | ADR-035 |
| N-05 | Despesas com **catálogo de tipos** e marca de dedutibilidade | 🎨🗄️ | ✅ | ADR-011 |
| N-06 | Anexo de comprovante na despesa | 🎨⚙️ | 🟡 | P-29 |
| N-07 | **Faturamento líquido** = receita − despesas. Independe de regime | ⚙️ | ✅ | ADR-013 |
| N-08 | Lembrete de cobrança: quem deve, quanto e até quando | 🎨⚙️ | ✅ | ADR-017 |
| N-09 | Lembrete fiscal ciente do regime: PF → Receita Saúde; PJ → nota fiscal | 🎨 | ✅ | ADR-030 |
| N-10 | Carnê-leão (CSV do Receita Saúde) e NFS-e por API | — | ⏸️ | ADR-013 |
| N-11 | Previsão de imposto | — | ⏸️ | P-30 |

---

## 8. Assinatura — app `assinaturas`

| # | História | Camada | Estado | ADR |
|---|---|---|---|---|
| S-01 | Cobrança da assinatura via Asaas | ⚙️ | 🟡 | não grilado |
| S-02 | No cancelamento, **exportação automática** do pacote completo, avisos repetidos e descarte após carência | ⚙️🔒 | 🟡 | ADR-007, P-20 |
| S-03 | `assinaturas` **não toca dado clínico**: sabe se a conta está ativa, não o que há dentro | ⚙️🔒 | ✅ | §3.2 |
| S-04 | Onboarding, teste gratuito e inadimplência | — | 🟡 | não grilado |

⚠️ **Módulo ainda não submetido ao Grill-Me.** Inadimplência é delicada: cortar acesso pode deixar
o psicólogo sem a documentação que a lei o obriga a guardar por 5 anos.

---

## 9. Indicadores — app `indicadores`

### Painel (diário, ação)

| # | História | Camada | Estado | ADR |
|---|---|---|---|---|
| I-01 | Pacientes ativos com último atendimento e **dias sem atender**, nos limiares de 7 e 30 dias | 🎨⚙️ | ✅ | portado do original |
| I-02 | Resumo por paciente: sessões do mês e pendência de pagamento | 🎨 | ✅ | escopo |
| I-03 | Pendências de ação: cobranças em aberto e **prontuários não escritos** | 🎨 | ✅ | ADR-017 |
| I-04 | Três indicadores de cabeçalho: receita líquida, ocupação da agenda, entradas × saídas | 🎨 | ✅ | ADR-027 |
| I-05 | Curto o bastante para caber numa tela, **sem gráfico decorativo** | 🎨 | ✅ | ADR-027 |

### Análise (eventual, profundidade)

| # | História | Camada | Estado | ADR |
|---|---|---|---|---|
| I-06 | Quanto do faturamento depende de um paciente só (risco de concentração) | ⚙️ | ✅ | ADR-027 |
| I-07 | Em que momento as pessoas desistem — **calculado**, não perguntado | ⚙️ | ✅ | ADR-027 |
| I-08 | Horas trabalhadas × horas disponíveis (trabalhar = só horário de atendimento) | ⚙️ | ✅ | ADR-027, ADR-029 |
| I-09 | Sessões realizadas por mês | ⚙️ | ✅ | ADR-027 |
| I-10 | A análise usa **apenas dado administrativo**. Nunca conteúdo de prontuário | 🔒 | ✅ | ADR-027 |

---

## Regras de dependência entre apps

1. `core` não depende de ninguém; todos dependem dele.
2. `indicadores` depende de todos; **ninguém depende de `indicadores`**.
3. `assinaturas` não toca dado clínico.
4. Sem dependência circular entre apps de domínio.
5. A IA fica atrás de adaptador — o domínio não conhece provedor.
6. `prontuarios` depende de `atendimentos`; nunca o contrário.

## Ordem sugerida de construção

1. **`core`** — a prova de conceito do isolamento (F-03, F-04). Nada mais começa antes disso.
2. **`contas` + `pacientes`** — sem dono e sem paciente, nada existe.
3. **`agenda` + `atendimentos`** — a consulta é a âncora de tudo o mais.
4. **`prontuarios`** — a razão de o produto existir.
5. **`financeiro`** — depende de consulta contabilizada.
6. **`documentos`** — independente; pode ir em paralelo a partir do passo 3.
7. **`indicadores`** — por último, porque só lê.
8. **`assinaturas`** — necessário para vender, não para validar.
