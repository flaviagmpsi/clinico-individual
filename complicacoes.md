# Decisões Arquiteturais e Impeditivos — Hamilton Individual

Registro de ADRs (Architecture Decision Records), impeditivos e perguntas ainda sem resposta.
Uma decisão registrada aqui só muda por outra decisão registrada aqui.

---

## ADR-001 — Isolamento total entre psicólogos (multi-tenancy)

**Status:** ✅ Aceita — Rodada 1
**Contexto:** O Hamilton Individual é um SaaS: muitos psicólogos autônomos usam a mesma
aplicação, cada um com sua própria carteira de pacientes. O Hamilton original resolve o
problema oposto — lá todos pertencem à mesma clínica, e `supervisao.py::get_terapeuta_visualizado()`
existe justamente para permitir que um decano veja os pacientes de outro terapeuta.
Prontuário é dado pessoal **sensível** (LGPD art. 11) e está sob sigilo profissional (CFP).

**Decisão:** Isolamento total. Nenhum psicólogo acessa dado de outro, em nenhuma hipótese.
Confirmado pelo usuário: **nenhum psicólogo jamais compartilha paciente com outro.**

Implementação em três camadas, para que o vazamento seja impossível e não apenas improvável:
1. **Modelo** — toda entidade de domínio carrega o dono (`fk_psicologo`) explicitamente.
2. **Aplicação** — `TenantManager` como manager padrão, que **levanta exceção** se a query
   rodar sem escopo de dono definido. Uma query insegura quebra em teste, não vaza em produção.
3. **Banco** — **Row-Level Security** do PostgreSQL (Neon), com a policy amarrada a uma
   variável de sessão setada por request. Mesmo SQL cru (`.raw()`, shell do Django) não
   atravessa a fronteira.

**Consequências:**
- O mecanismo de "view-as"/supervisão do original **não é portado**. É funcionalidade proibida aqui.
- RLS exige setar a variável de sessão a cada request; com pooling do Neon isso precisa de
  cuidado no middleware (ver I-01).
- Fica descartado, por ora, um schema Postgres por psicólogo (`django-tenants`): mesmo
  isolamento a um custo operacional que só se justifica em escala grande. O caminho continua
  aberto porque o dono do dado é explícito desde o primeiro modelo.

---

## ADR-002 — Modalidade de cobrança por paciente

**Status:** ✅ Aceita — Rodada 1
**Contexto:** O dashboard do Hamilton original calcula o valor devido de cada paciente como
`vlr_sessao` — o preço de **uma** sessão —, independentemente de terem ocorrido 2 ou 5 sessões
no mês (achado A-01). Ou seja, assume mensalidade fixa em silêncio, e erra em todo mês que não
tenha exatamente uma sessão.

**Decisão:** A modalidade é **explícita e configurada por paciente**, com dois valores:

| Modalidade | Como o valor a receber nasce |
|---|---|
| `MENSAL` | **Uma** cobrança por mês, de valor fixo, independente do número de sessões. Vence no **início ou no fim do mês**, conforme preferência. |
| `POR_SESSAO` | **Cada consulta registrada** gera sua própria cobrança, **cobrada logo após o atendimento**. |

Em ambos os casos, o psicólogo registra manualmente se recebeu ou não.

**Refinado na Rodada 2:** confirmado que, no modo `POR_SESSAO`, o psicólogo cobra de fato sessão
a sessão — a cobrança não espera o fechamento do mês. O agrupamento por paciente existe apenas
como **apresentação** na tela de Lembretes ("Fulano — 4 sessões — R$ 800"), nunca como fusão dos
registros, que permanecem granulares para permitir recibo por atendimento. O usuário sinalizou
que este é o fluxo financeiro **mais complexo em todos os níveis** — é ele que dita o desenho.

**Assunção adotada** (corrija se estiver errada): a preferência de vencimento do modo `MENSAL` é
um **padrão no perfil do psicólogo**, sobrescrevível por paciente — configura uma vez e ainda
atende o caso pontual.

**Consequências:**
- Surge uma entidade de **conta a receber**, separada de `Pagamento`, que o original não possui:
  no original só existe o registro do dinheiro que **entrou**, então "quem me deve" não é um dado,
  é uma conta feita na tela. Isso é o que torna possível a aba de Lembretes de cobrança. Formato
  a definir (ver P-08).
- O bug A-02 (soma vs. último pagamento do mês) deixa de existir por construção, já que o saldo
  passa a ser recebido ÷ devido sobre registros, e não sobre um único valor.
- Trocar a modalidade de um paciente no meio do mês tem efeito sobre cobranças já geradas —
  regra a definir.

---

## ADR-003 — Projeto novo, sem fork do `hamilton-api`

**Status:** ✅ Aceita — Rodada 2
**Contexto:** A tentação natural era partir de uma cópia do repositório do Hamilton e ir
adaptando. Contra isso pesavam o schema legado (`db_table` em português, PKs `pk_*`), o
`views.py` de 5.639 linhas misturando HTML e API, as migrations git-ignored e a camada
financeira (Stripe + NFS-e) inaproveitável. Mas o argumento decisivo veio da ADR-001: o
Hamilton foi construído **partindo do princípio de que um supervisor pode ver os pacientes de
outro terapeuta**, e essa suposição está espalhada por telas, filtros e permissões. Forkar
significa caçá-la por todo canto, e cada resquício não é um bug de tela — é prontuário de
paciente vazando para outro psicólogo.

**Decisão:** Projeto Django novo. O `hamilton-api` permanece clonado ao lado como referência de
leitura, e cada peça vinda dele entra por decisão explícita, nunca por herança.

**Consequências:**
- Custo maior nas primeiras semanas, em troca de não fundar o produto sobre a suposição que a
  ADR-001 proíbe.
- Regras portadas deliberadamente: cálculo de dias desde o último atendimento, limiares
  REGULAR / ATENÇÃO / CRÍTICO (7 e 30 dias), `choices` de alta e desistência.
- Convenções legadas **não** portadas: `db_table` explícito, PKs `pk_*`, colunas `fk_*`/`dat_*`/
  `vlr_*`, migrations fora do versionamento.

---

## ADR-004 — Reuso da interface, não do código

**Status:** ✅ Aceita — Rodada 2
**Contexto:** O usuário reforçou que quer "copiar a estrutura do Hamilton original porque o
template é simples e intuitivo", e ao mesmo tempo aceitou projeto novo (ADR-003). Não há
contradição — são duas coisas diferentes que a palavra "estrutura" confunde.

**Decisão:** Separar explicitamente as duas camadas:

| Camada | Origem |
|---|---|
| **Interface** — layout, navegação, densidade de informação, organização das abas | **Copiada** do Hamilton original. É requisito de produto declarado. |
| **Código e modelo de dados** — apps, models, views, permissões | **Novos**, conforme ADR-003. |

**Consequências:**
- Os templates do original (`principais/templates/`) são material de trabalho direto: partimos
  do HTML/CSS deles e trocamos o que a mudança de domínio exigir.
- Telas do original que **não** existem no Individual, por serem de clínica coletiva: match
  paciente↔terapeuta, seleção e supervisão de terapeutas, plantão, controle de novos pacientes
  e encaminhamento entre profissionais.

---

## ADR-005 — O prontuário segue a Resolução CFP nº 001/2009

**Status:** ✅ Aceita — Rodada 2 (fato levantado, não decisão do usuário)
**Contexto:** "Seguir os padrões do CRP" precisava virar especificação concreta antes de a IA
poder gerar qualquer coisa. A norma aplicável é a **Resolução CFP nº 001/2009**.

**Decisão:** A estrutura do prontuário gerado é a do **Art. 2º**, e o sistema a trata como
contrato, não como sugestão:

| Inciso | Exigência | Onde vive no sistema |
|---|---|---|
| I | Identificação do usuário | Cadastro do paciente |
| II | Avaliação de demanda e definição de objetivos do trabalho | Registro de abertura do caso |
| III | Registro da **evolução** do trabalho e dos procedimentos técnico-científicos adotados | Prontuário de sessão — **o que a IA gera** |
| IV | Registro de encaminhamento ou encerramento | Aba de Altas e Desistências |
| V | Documentos de avaliação psicológica, em pasta de **acesso exclusivo do psicólogo** | Anexos com visibilidade restrita |
| VI | Cópias de documentos emitidos, com data, finalidade e destinatário | Histórico de documentos |

Outras exigências com efeito direto no produto:
- **Art. 4º, §1º** — guarda de **no mínimo 5 anos**, ampliável por lei ou determinação judicial.
- **Art. 4º, §2º** — guarda em local que garanta sigilo e privacidade, e à disposição dos
  Conselhos para fiscalização, servindo como **meio de prova** em processo disciplinar.
- **Art. 5º, II** — o **paciente tem direito de acesso integral** ao próprio prontuário.
- **Art. 1º, §2º** — deve ser mantido permanentemente atualizado e organizado.

**Consequências:**
- O prontuário é peça de defesa legal do psicólogo. Isso eleva a régua de integridade:
  precisa de trilha de auditoria (quem escreveu, quando, o que mudou), não apenas de um campo
  de texto editável.
- A guarda mínima de 5 anos colide com o cancelamento de assinatura (ver P-10).
- O direito de acesso do paciente (Art. 5º, II) é uma funcionalidade ainda não prevista no
  escopo declarado (ver P-11).
- ⚠️ **Conflito de prazos a resolver:** a Lei nº 13.787/2018 estabelece **20 anos** para
  prontuários de paciente em saúde, contra os 5 anos do CFP. Precisa de posição definida.
## Impeditivos

| # | Impeditivo | Situação |
|---|---|---|
| I-01 | RLS + connection pooling do Neon: a variável de sessão do tenant precisa ser setada por request e **limpa** ao devolver a conexão ao pool, sob risco de uma request herdar o tenant da anterior. Exige prova de conceito antes de virar fundação. | 🔴 A validar |
| I-02 | `gh` CLI não autenticado na máquina (`gh auth status`). Git funciona via Credential Manager; só ferramentas que dependem do `gh` ficam indisponíveis. | 🟡 Contornado |
