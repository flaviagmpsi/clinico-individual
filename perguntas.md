# Perguntas em Aberto — Hamilton Individual

Backlog de dúvidas sistêmicas e de negócio que dependem de decisão/investigação do Paulo.
Status: 🔴 aberta · 🟡 em discussão · 🟢 resolvida (migra para `documentacao.md`)

---

## Itens que o usuário pediu explicitamente para retomar

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-01 | Dashboard | Quais widgets adicionais entram além dos 3 herdados (pacientes ativos + dias sem atendimento, resumo de receita/sessões do mês, resumo por paciente com sessões e pendência)? | 🔴 |
| P-02 | Horários | Além dos horários disponíveis + leitura do Google Agenda, o que mais a aba precisa? (bloqueios, férias, recorrência, no-show) | 🔴 |
| P-03 | Consultas | O cadastro de consultas do Hamilton original será replicado por inteiro — **o que será adicionado**? | 🔴 |
| P-04 | Pagamentos | Cópia integral da aba do original — **quais campos/fluxos novos**? | 🔴 |
| P-05 | Altas e Desistências | Cópia integral do original — **o que muda para o contexto individual**? (não existe "reencaminhamento para outro terapeuta") | 🔴 |
| P-06 | Análise de Dados | Qual a melhor forma de mostrar desempenho do psicólogo? Definir as perguntas que o gráfico responde antes de escolher o gráfico. | 🔴 |
| P-07 | Lembretes | Aba própria ou embutida em Horários? Decisão depende do gatilho: se o lembrete é sobre **cobrança** (data limite de pagamento), ele é do domínio Financeiro, não da Agenda. | 🔴 |

---

## Escopo declarado (a detalhar)

### Herdado do Hamilton original
- Simplicidade e clareza da interface — tela limpa, sem se perder na informação. **Requisito de produto, não estético.**
- Dashboard: pacientes ativos, último atendimento e dias sem atender.
- Dashboard: resumo de receita — sessões realizadas/previstas no mês, valor a receber vs. já recebido.
- Dashboard: resumo por paciente — sessões realizadas e pendência de pagamento.
- Abas de Consultas, Pagamentos, Altas/Desistências e Horários.

### Novo no Individual
- **Prontuário por IA**: áudio gravado ou texto → prontuário nos padrões do CRP. Download de sessão única ou histórico completo, em DOC ou PDF.
- **Lembretes de cobrança**: data limite de pagamento por paciente, controle de quem falta cobrar no mês.
- **Cadastro de paciente ampliado**: nome completo, CPF, telefone, e-mail, endereço com CEP, data de nascimento, medicamento (se houver), data da primeira sessão, acesso direto aos prontuários realizados, contagem de sessões.
- **Financeiro ampliado**: registro de pagamentos, quem já pagou no mês, data limite, pendências, atrasos, faturamento mensal e **despesas** (imposto, sala, anuidade, supervisão e outras cadastráveis pelo psicólogo).
- **Análise de dados**: painel de desempenho do psicólogo.

---

## Achados técnicos na base de referência (`hamilton-api`)

| # | Achado | Impacto |
|---|---|---|
| A-01 | No dashboard, `valor_devido` do paciente = `vlr_sessao` (valor de **uma** sessão), ignorando quantas sessões ocorreram no mês. Assume cobrança **mensal fixa**, não por sessão. | ✅ Resolvido por ADR-002: modalidade explícita por paciente. |
| A-02 | `pagamento_recente_mes_subquery` pega o valor do **último** pagamento do mês, não a **soma**. Paciente que paga em duas parcelas aparece com valor subnotificado. | ✅ Resolvido por ADR-002: saldo passa a ser calculado sobre registros de conta a receber. |
| A-03 | Sem app de despesas/custos no original — só receita. | O financeiro do Individual é construção nova, não cópia. |
| A-04 | Original usa Stripe + NFS-e (WebmaniaBR). Individual usa Asaas + recibo de PF + Carnê-Leão. | Camada financeira não é reaproveitável. |
| A-05 | `Consulta` valida que a data não pode ser anterior a 3 meses da criação do registro. | Regra a confirmar se permanece. |
| A-06 | Migrations são git-ignored no original (exigem `git add -f`). | Prática a **não** herdar. |

---

## Abertas na Rodada 2

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-08 | Financeiro | Formato da conta a receber gerada por consulta (modalidade `POR_SESSAO`): registro por sessão ou agrupamento mensal para cobrança única? | 🟡 |
| P-09 | Financeiro | Trocar a modalidade de cobrança de um paciente no meio do mês afeta cobranças já geradas? | 🔴 |
