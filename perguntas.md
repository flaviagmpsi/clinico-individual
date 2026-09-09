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
| P-08 | Financeiro | Formato da conta a receber no modo `POR_SESSAO`. | ✅ Resolvida: cobrança por sessão, agrupamento apenas na apresentação (ADR-002). |
| P-09 | Financeiro | Trocar a modalidade de cobrança de um paciente no meio do mês afeta cobranças já geradas? | 🔴 |

## Abertas na Rodada 3

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-10 | Assinatura | O CFP exige guarda de **no mínimo 5 anos** (Res. 001/2009, Art. 4º §1º). O que acontece com os prontuários quando o psicólogo **cancela a assinatura**? Recomendação: exportação automática + carência, com tamanho da carência a definir. | ✅ Resolvida: exportação e descarte (ADR-007). |
| P-11 | Prontuário / Legal | O Art. 5º, II garante ao paciente **acesso integral** ao próprio prontuário. Como o sistema atende esse direito? (não estava no escopo declarado) | 🔴 |
| P-12 | Prontuário / Legal | Conflito de prazos: CFP diz 5 anos, Lei nº 13.787/2018 diz **20 anos** para prontuário de paciente em saúde. Qual prazo o sistema adota? | 🔴 |
| P-13 | Prontuário / IA | Destino do **áudio** após a transcrição: descartar ou arquivar? Depende de P-16. | ⏸️ Adiada |
| P-14 | Prontuário / IA | Consentimento do paciente para gravação e para processamento por IA de terceiro. Só é necessário se P-16 for "sessão gravada". | ✅ Descartada: sem gravação de sessão, não há consentimento de paciente a coletar (ADR-006). |
| P-15 | Financeiro | Vencimento do modo `MENSAL`: assunção adotada é padrão no perfil, sobrescrevível por paciente. Confirmar. | 🟡 |

## Abertas na Rodada 3 (continuação)

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-16 | Prontuário / IA | **O áudio é o psicólogo ditando sobre a sessão, ou a sessão gravada com a voz do paciente?** Muda modelo de dados, consentimento, custo e perfil de risco. Não adiável. | ✅ Resolvida: relato do psicólogo, ditado ou escrito. A sessão nunca é gravada (ADR-006). |
| P-17 | Prontuário / IA | O texto gerado é rascunho de revisão obrigatória ou vira prontuário direto? Padrão adotado: **rascunho obrigatório** (opção segura, reversão barata). | 🟡 Padrão adotado, a confirmar |
| P-18 | Prontuário / IA | Paulo já tem uma IA escrita em outro código. Avaliar se dá para embutir ou se será construída do zero. **Requer acesso ao código.** Não bloqueia o planejamento. | 🔴 |
| P-19 | Prontuário / IA | Escolha do provedor de IA/transcrição: custo por sessão, latência e **onde o áudio é processado** — se sair do Brasil, muda a base legal da LGPD. | 🔴 |

## Abertas na Rodada 4 — Financeiro

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-20 | Assinatura | Tamanho da carência antes do descarte definitivo no cancelamento. Assunção provisória: **90 dias**. | 🟡 |
| P-21 | Fiscal | O sistema **calcula** o imposto ou apenas organiza os dados? | ✅ Resolvida: estimativa informativa (ADR-010). |
| P-22 | Cadastro | **Pagador ≠ beneficiário**: o CSV do Receita Saúde exige os dois CPFs. Pai pagando pelo filho, cônjuge, empresa. Como modelar? | ✅ Resolvida: pagador modelado separado do paciente (ADR-009). |
| P-23 | Fiscal | Classificação de despesas dedutíveis vs. não dedutíveis. | 🟡 Catálogo levantado e proposto em ADR-011 — aguarda validação. |
| P-24 | Perfil | Perfil do psicólogo precisa de **CPF e número do CRP** para a escrituração — não previstos no escopo inicial. | 🟡 Requisito derivado |

## Abertas na Rodada 5 — Fiscal e cadastro

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-25 | Fiscal | O Carnê-Leão é progressivo sobre a renda **total** do mês. Se o psicólogo tem **outra fonte de renda** (CLT, aluguel, outra clínica), a estimativa que só vê a renda daqui é estruturalmente otimista. O sistema pergunta isso? | 🔴 |
| P-26 | Fiscal | Deduções que não são livro caixa e hoje não estão no sistema: **INSS**, **dependentes**, **pensão alimentícia**. O psicólogo informa? | 🔴 |
| P-27 | Cadastro | Paciente **menor de idade sem CPF próprio**: o campo `CPF do beneficiário` é obrigatório no CSV do Receita Saúde. Como resolver? | 🔴 |
| P-28 | Fiscal | Supervisão clínica, cursos de formação e plano de saúde são zonas cinzentas de dedutibilidade. Requer **parecer contábil**, não pesquisa. | 🔴 |
| P-29 | Fiscal | Todo lançamento de despesa precisa de comprovante para a Receita aceitar. Anexo de comprovante entra no MVP? | 🔴 |
