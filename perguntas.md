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
| P-11 | Prontuário / Legal | O Art. 5º, II garante ao paciente **acesso integral** ao próprio prontuário. Como o sistema atende esse direito? (não estava no escopo declarado) | ❌ Fora de escopo: o sistema não se comunica com pacientes (ADR-039). |
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
| P-20 | Assinatura | Tamanho da carência antes do descarte. | ✅ Resolvida: 30 dias de leitura + 60 arquivada = 90 (ADR-038). |
| P-21 | Fiscal | O sistema **calcula** o imposto ou apenas organiza os dados? | ✅ Resolvida: estimativa informativa (ADR-010). |
| P-22 | Cadastro | **Pagador ≠ beneficiário**: o CSV do Receita Saúde exige os dois CPFs. Pai pagando pelo filho, cônjuge, empresa. Como modelar? | ✅ Resolvida: pagador modelado separado do paciente (ADR-009). |
| P-23 | Fiscal | Classificação de despesas dedutíveis vs. não dedutíveis. | 🟡 Catálogo levantado e proposto em ADR-011 — aguarda validação. |
| P-24 | Perfil | Perfil do psicólogo precisa de **CPF e número do CRP** para a escrituração — não previstos no escopo inicial. | 🟡 Requisito derivado |

## Abertas na Rodada 5 — Fiscal e cadastro

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-25 | Fiscal | O Carnê-Leão é progressivo sobre a renda **total** do mês. Se o psicólogo tem **outra fonte de renda** (CLT, aluguel, outra clínica), a estimativa que só vê a renda daqui é estruturalmente otimista. O sistema pergunta isso? | ✅ Resolvida: campo opcional, não barreira de entrada (ADR-012). |
| P-26 | Fiscal | Deduções que não são livro caixa e hoje não estão no sistema: **INSS**, **dependentes**, **pensão alimentícia**. O psicólogo informa? | ✅ Resolvida: campos opcionais em configurações (ADR-012). |
| P-27 | Cadastro | Paciente **menor de idade sem CPF próprio**: o campo `CPF do beneficiário` é obrigatório no CSV do Receita Saúde. Como resolver? | ✅ Resolvida: CPF obrigatório em certidão desde 01/2018; resta janela para nascidos antes (ADR-014). |
| P-28 | Fiscal | Supervisão clínica, cursos de formação e plano de saúde são zonas cinzentas de dedutibilidade. Requer **parecer contábil**, não pesquisa. | ⏸️ Adiada com a saída fiscal (ADR-013). |
| P-29 | Fiscal | Todo lançamento de despesa precisa de comprovante para a Receita aceitar. Anexo de comprovante entra no MVP? | 🔴 |

## Abertas na Rodada 6

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-30 | Fiscal | Cliente sendo PF **e** PJ, "previsão de impostos" vira **duas** features: tabela progressiva do carnê-leão vs. alíquota do Simples (Anexo V ou III conforme Fator R). Recomendação: sai do MVP junto com as demais saídas fiscais, restando o **faturamento líquido**, que independe de regime. | 🟡 |
| P-31 | Validação | Entre psicólogos autônomos do mercado, quantos são PF e quantos são PJ hoje? Dado que resolve a priorização das saídas fiscais. Vale 20 min de conversa com cinco deles. | 🔴 |

## Abertas na Rodada 7 — Infantil e estrutura

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-32 | Prontuário / Ético | Responsável legal tem direito ao **estritamente necessário**, não ao prontuário inteiro. Como a exportação distingue isso? | ❌ Fora de escopo (ADR-039). |
| P-33 | Prontuário / Ético | **Sigilo do adolescente perante os pais.** O produto não pode assumir que responsável vê tudo. Qual o desenho? | ❌ Fora de escopo (ADR-039). |
| P-34 | Cadastro | Paciente nascido **antes de 2018** pode não ter CPF. O sistema bloqueia, avisa, ou permite cadastro sem CPF? | 🟡 |

## Abertas na Rodada 8

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-35 | Contratos | Provedor de assinatura eletrônica: a Autentique é herança do original, não decisão nossa. Comparar custo por documento com D4Sign, Clicksign, ZapSign antes de virar dependência. | ❌ Morta: sem assinatura eletrônica no MVP (ADR-015 revisada). |
| P-36 | Lembretes | **Canal de entrega** do lembrete: in-app, e-mail, evento no Google Agenda, push web ou WhatsApp. Decisão separada da propriedade do dado (ADR-017). | ✅ Resolvida: in-app + Google Agenda (ADR-018). |
| P-37 | Infra | **Onde ficam os arquivos?** O disco do Render é efêmero (I-04). Bytes no Postgres, object storage (S3/R2) ou Neon storage? Áudio de relato pesa muito mais que PDF de contrato. | ✅ Resolvida: misto — banco para jurídico, object storage para áudio (ADR-019). |

## Abertas na Rodada 9

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-38 | Contratos | "Alterar e apagar" colide com *contrato é histórico*. Aceitável porque o original assinado é o papel — mas apagar sem rastro deixa o psicólogo sem cópia. Exclusão definitiva ou lixeira com histórico? | ✅ Resolvida: alterar versiona, apagar vai para lixeira (adendo à ADR-015). |
| P-39 | Agenda | ADR-018 exige **escrever** evento na agenda do psicólogo. Isso muda o escopo do OAuth do Google de leitura para leitura e escrita. Confirmar. | ✅ Resolvida: escrita necessária, pedida sob demanda (ADR-020). |
| P-40 | Documentos | Consolidar `contratos` num app `documentos`? A Res. CFP 001/2009 Art. 2º já exige guardar **anexos de avaliação psicológica** (inciso V, acesso exclusivo do psicólogo) e **cópias de documentos emitidos** (inciso VI). São três necessidades com a mesma forma. | ✅ Resolvida: app `documentos` com contrato como tipo (ADR-021). |
| P-41 | Infra | Provedor de object storage: S3, Cloudflare R2 (sem custo de egresso) ou storage do Neon. Isolamento por tenant exige chave por psicólogo e URL assinada de vida curta. | 🔴 |

## Abertas na Rodada 10

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-42 | Agenda | Divergência silenciosa: se o psicólogo editar o evento direto no Google, a mudança não volta. Como o produto avisa em vez de esconder? | ✅ Resolvida: detectar e oferecer atualização (adendo à ADR-020). |
| P-43 | Agenda | Risco de adoção: o psicólogo que hoje vive no Google Agenda terá de reorganizar **no Hamilton**. Mudança de hábito é o maior risco deste módulo. | 🟡 Mitigado por ADR-022: o caso comum é fixo e cadastrado uma vez só. Validar com psicólogos autônomos do mercado (P-31). |

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-44 | Agenda / Financeiro | **Falta do paciente gera cobrança?** É cláusula típica de contrato terapêutico e muda o que o estado `FALTA` dispara. | ✅ Resolvida: eixos independentes, padrão no perfil (ADR-023). |
| P-45 | Agenda | Alterar a **regra** de recorrência: vale a partir de quando? Precisa do equivalente a "este / este e os seguintes / todos". | ✅ Resolvida: "só esta" e "esta e as próximas"; "todas" não existe (adendo à ADR-022). |
| P-46 | Agenda | Tamanho da janela de materialização e o momento de empurrá-la (sem agendador, ao abrir a agenda). | 🟡 Decisão técnica |

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-47 | Agenda | Férias, feriados e pausas: suspender ocorrências em bloco. **Adiado a pedido do usuário** — retomar depois do MVP. | ⏸️ Adiada |
| P-48 | Agenda | **Colisão de horário** na remarcação avulsa: se a nova data cair sobre outro paciente ou compromisso do Google, o sistema bloqueia, avisa ou permite? | ✅ Resolvida: bloqueia (ADR-024). |
| P-49 | Agenda | **Duração da sessão**: padrão no perfil (50 min) com ajuste por paciente ou por consulta? | ✅ Resolvida: padrão no perfil, ajustável por paciente (ADR-025). |

## Abertas na Rodada 12

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-50 | Modelagem | **Atendimento de casal, família ou grupo.** Nunca foi tratado. A Res. CFP 001/2009, Art. 5º, III exige que, em atendimento em grupo não eventual, o psicólogo mantenha **documentação individual de cada usuário** além dos registros do atendimento. Afeta consulta, prontuário, cobrança e a colisão de horário (ADR-024). | ✅ Resolvida: `Caso` aceito, invisível no atendimento individual (ADR-026). |
| P-51 | Dashboard | Separar **dashboard operacional** (o que exige ação hoje) de **análise de desempenho** (como estou indo)? | ✅ Resolvida: telas separadas (ADR-027). |
| P-52 | Dashboard | Quais perguntas a aba de análise deve responder? Definir as perguntas **antes** de escolher gráfico. | ✅ Resolvida: quatro perguntas escolhidas, nenhuma exige campo novo (adendo à ADR-027). |

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-53 | Prontuário / IA | Em sessão de casal, impedir que a fala de um participante migre para o prontuário do outro. Instrução da IA e revisão humana. | 🔴 Risco clínico |
| P-54 | Análise | Como o sistema sabe as **horas disponíveis** do psicólogo, se declarar a grade não pode ser barreira de entrada (ADR-012)? | ✅ Resolvida: grade declarada, ocupação derivada (ADR-029). |

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-55 | Interface | Como chamar o `Caso` na tela, quando aparecer para quem atende casal? "Caso", "atendimento", "vínculo" ou outro termo natural para psicólogo. | ✅ Resolvida: "Caso" fica também na tela. |

## Abertas na Rodada 17

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-56 | Avaliação psicológica | **Tema inteiro ainda não tratado.** A Res. CFP 31/2022 rege a avaliação psicológica e o SATEPSI (testes com validade máxima de 15 anos). Ela é pré-requisito do Atestado e do Laudo (ADR-032) e origem dos anexos de acesso exclusivo (ADR-005, inciso V). Entra no MVP ou é módulo próprio depois? | ⏸️ Módulo próprio, depois do MVP (ADR-034). |
| P-57 | Documentos / IA | A IA de documentos tem acesso ao **conteúdo do prontuário**? Um laudo precisa de material clínico; uma declaração, não. | ✅ Resolvida: acesso por tipo de documento (ADR-034). |
| P-58 | Documentos | **Relatório Multiprofissional** pressupõe equipe. Faz sentido num produto para psicólogo individual? | ✅ Resolvida: fora do escopo (ADR-034). |
| P-59 | Documentos | Atestado e Laudo pressupõem avaliação psicológica realizada, e o CRP pode exigir a fundamentação em até 5 anos. Como amarrar o documento gerado ao registro que o fundamenta? | ✅ Resolvida: Atestado e Laudo saem do MVP com a avaliação (ADR-034). |
| P-60 | Documentos | Manter norma dentro do produto cria **dever de atualização**. Quem verifica se a resolução exibida ainda é a vigente? | 🟡 |

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-61 | Financeiro | Pagamento **sem cobrança correspondente**: adiantamento, pacote pago à frente, ou dinheiro recebido antes da sessão. Como registrar? | 🔴 |

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-62 | Comercial | Sem teste gratuito, como o psicólogo conhece o produto antes de pagar? Demonstração com dados fictícios, garantia de reembolso, indicação? | ✅ Resolvida: demonstração com dados fictícios. |
| P-63 | Assinatura | **Inadimplência** (parou de pagar sem cancelar) é estado diferente de **cancelamento**. O que acontece nesse meio-tempo? | ✅ Resolvida: somente-leitura após tolerância (ADR-038). |

| # | Tema | Pergunta | Status |
|---|---|---|---|
| P-64 | Assinatura | **E se o e-mail de aviso não chegar?** Endereço trocado ou caixa cheia fazem o aviso falhar em silêncio, e o descarte acontece sem o psicólogo saber. | 🔴 |
