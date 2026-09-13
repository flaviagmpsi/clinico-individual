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
## ADR-006 — O prontuário nasce do relato do psicólogo, não da sessão gravada

**Status:** ✅ Aceita — Rodada 3
**Contexto:** "Áudio gravado" era ambíguo entre duas coisas muito diferentes: o psicólogo ditando
um resumo após o atendimento, ou a sessão inteira gravada com a voz do paciente.

**Decisão:** A entrada é sempre o **relato do próprio psicólogo sobre a sessão**, em duas formas
equivalentes: **áudio ditado** ou **texto escrito**. A IA transforma esse relato em prontuário
na estrutura da Res. CFP 001/2009 (ADR-005). **A sessão nunca é gravada.**

**Consequências:**
- O único falante no áudio é o psicólogo, que consente por si. **Não existe fluxo de
  consentimento do paciente para gravação** — ele deixa de ser requisito do MVP.
- O conteúdo já chega filtrado pelo julgamento clínico: não trafega fala bruta do paciente.
- Áudios são curtos (minutos, não a sessão inteira), o que reduz custo e latência de transcrição.
- O relato é **insumo**, não documento. Só o prontuário gerado tem valor legal.
- Áudio e texto são duas portas para o mesmo pipeline — o modelo de dados deve tratá-los como
  variações de "relato de origem", não como dois fluxos separados.

---

## ADR-007 — Exportação e descarte no cancelamento da assinatura

**Status:** ✅ Aceita — Rodada 3
**Contexto:** O Art. 4º, §1º da Res. CFP 001/2009 obriga o **psicólogo** a guardar os registros
por no mínimo 5 anos. Apagar no cancelamento o colocaria em infração; guardar indefinidamente
faria a plataforma depositária de dado sensível de saúde de quem não é mais cliente.

**Decisão:** No cancelamento, o sistema **gera automaticamente** o pacote completo (todos os
prontuários em PDF/DOC, mais os dados financeiros), avisa o psicólogo, mantém por um período de
carência e então **descarta definitivamente**. A obrigação legal de guarda volta a quem a lei
cobra: o profissional.

**Consequências:**
- A exportação é **empurrada, não escondida**: pacote pronto no ato do cancelamento e avisos
  repetidos durante a carência. Um cliente que perde prontuário por não ter lido um e-mail é
  falha nossa de produto, não descuido dele.
- 🔴 **Tamanho da carência ainda não definido** (ver P-20). Assunção provisória: 90 dias.
- O descarte precisa ser real e auditável (backups incluídos), sob pena de a promessa ser falsa.
- Continua valendo avaliar "conta congelada" como **argumento de venda** futuro, já que o medo
  de perder o histórico trava a decisão de compra.

---

## ADR-008 — Não emitimos recibo: geramos a escrituração para o Receita Saúde

**Status:** ✅ Aceita — Rodada 3 (imposição legal, não escolha)
**Contexto:** O escopo inicial previa "emissão de recibos (pessoa física)" pelo sistema. Isso
**não é legalmente possível**. Desde **1º de janeiro de 2025**, psicólogos que atendem como
pessoa física emitem recibo **exclusivamente** pelo Receita Saúde (app da Receita Federal /
Portal e-CAC). O CFP alimenta mensalmente a base da Receita com os profissionais ativos.

**Decisão:** O Hamilton **não emite recibo**. Ele faz o trabalho que sobra, que é justamente o
chato: mantém os dados prontos e **gera o arquivo CSV de escrituração em lote**, que o psicólogo
importa no e-CAC em uma única operação (Carnê-Leão → Escrituração → Importar Escrituração).

Formato exigido pelo arquivo (manual Receita Saúde 2.1): CSV separado por **ponto e vírgula**,
até **1000 linhas**, todos os pagamentos do **mesmo ano**.

| Campo | Valor |
|---|---|
| Data do pagamento | `DD/MM/AAAA` — data do **efetivo pagamento** |
| Código do rendimento | fixo `R01.001.001` |
| Código da ocupação | `255` (Psicólogo) |
| Valor do pagamento | > 0, sem separador de milhares |
| Valor da dedução | vazio |
| Descrição | até 255 caracteres |
| Recebido de | fixo `PF` |
| **CPF do pagador** | 11 dígitos — quem **pagou** |
| **CPF do beneficiário** | 11 dígitos — quem **foi atendido** |
| Ind. CPF não informado / CNPJ / Indicador de IRRF / Valor IRRF | vazios |
| Indicador de recibo | fixo `S` |
| CPF do profissional | 11 dígitos |
| Registro profissional | CRP, até 15 caracteres (opcional se houver só um ativo) |

**Consequências:**
- ⚠️ **Lacuna no cadastro de paciente:** o arquivo exige **CPF do pagador e CPF do beneficiário
  como campos distintos**. O escopo declarado previa um CPF só. Pai pagando pelo filho é caso
  comum em clínica (ver P-22).
- O perfil do psicólogo precisa guardar **CPF e número do CRP** — hoje não previstos.
- O recibo emitido no Receita Saúde **alimenta automaticamente** o cálculo mensal do
  Carnê-Leão. Logo, nosso valor não está em calcular o imposto sobre a receita, e sim no
  **livro caixa das despesas** e na **previsão** (ver P-21).
- Não existe API pública. A integração é por arquivo, e a importação é ato manual do psicólogo
  no e-CAC — dependência externa que não controlamos.
- O limite de 1000 linhas por arquivo exige particionar lotes grandes.

## ADR-009 — Pagador e beneficiário são entidades distintas

**Status:** ✅ Aceita — Rodada 4
**Contexto:** O CSV do Receita Saúde (ADR-008) exige `CPF do pagador` e `CPF do beneficiário`
em campos separados — a Receita separa porque quem paga é quem deduz no próprio IRPF. O escopo
inicial do cadastro previa um CPF só. Confirmado pelo usuário que o caso existe na prática:
pai pagando pelo filho, cônjuge, empresa custeando funcionário.

**Decisão:** O **pagador** é modelado separadamente do **paciente**, com o CPF do próprio
paciente como padrão.

**Consequências:**
- Na interface o caso comum não muda: preencheu o CPF do paciente, acabou. O segundo campo só
  aparece quando o psicólogo marcar "quem paga é outra pessoa".
- A cobrança e o recibo apontam para o **pagador**; o atendimento e o prontuário, para o
  **paciente**. São eixos diferentes e não devem ser fundidos.
- Paciente menor de idade sem CPF próprio é caso a tratar: o campo `CPF do beneficiário` é
  obrigatório no arquivo.
- Evita migration sobre recibo já emitido, que seria irreversível.

---

## ADR-010 — A previsão fiscal é estimativa informativa, nunca cálculo oficial

**Status:** ✅ Aceita — Rodada 4
**Contexto:** O dashboard prevê "previsão de impostos". O recibo emitido no Receita Saúde já
alimenta automaticamente o cálculo mensal oficial do Carnê-Leão (ADR-008), então refazer essa
conta seria duplicar de graça algo que a Receita faz — assumindo o risco de errar.

**Decisão:** O número exibido é **estimativa**, rotulada explicitamente na tela e não em rodapé.
O valor oficial é sempre o do Carnê-Leão Web.

**Consequências:**
- Errar para menos faria o cliente pagar imposto a menor e cair na malha fina, com o nosso nome
  no erro. O rótulo é proteção do cliente e nossa.
- Nosso valor não está em calcular: está em **avisar em 12 de setembro** que vai haver imposto a
  pagar — algo que a Receita não faz.
- A estimativa depende de dados que hoje não estão no sistema: INSS, dependentes, pensão
  alimentícia e **outras fontes de renda** do psicólogo (ver P-25 e P-26). Sem eles, a previsão
  é estruturalmente otimista, porque o Carnê-Leão é progressivo sobre a renda **total** do mês.

---

## ADR-011 — Catálogo de despesas com marca de dedutibilidade

**Status:** 🟡 Proposta — aguardando validação (Rodada 4)
**Contexto:** A lista informada pelo usuário ("imposto, sala, anuidade, supervisão") mistura
dedutível com não dedutível, e ele não tem a lista real. Levantamento feito nas fontes da
Receita Federal.

**Decisão proposta:** Toda despesa tem um **tipo**, e todo tipo carrega a marca `dedutivel`.
Catálogo inicial:

| Tipo de despesa | Dedutível | Observação |
|---|---|---|
| Aluguel de sala / consultório | ✅ | Despesa de custeio indispensável à atividade. |
| Condomínio, água, luz, internet do consultório | ✅ | Vinculados ao espaço de atendimento. |
| Anuidade do CRP | ✅ | Contribuição a conselho profissional. |
| Material de consumo e de expediente | ✅ | |
| Serviços de terceiros (contador, secretária, recepcionista) | ✅ | Inclui encargos, se houver vínculo. |
| Software de gestão / prontuário eletrônico | ✅ | Inclui a própria assinatura do Hamilton. |
| Publicações técnicas necessárias à atividade | ✅ | |
| Benfeitorias em imóvel **alugado** | ✅ | Como compensação contratual de aluguel. |
| **Supervisão clínica** | ⚠️ | Enquadra como serviço de terceiro necessário à atividade, mas não há menção expressa nas fontes. **Confirmar com contador.** |
| **Cursos e formação** | ⚠️ | Fontes vedam "cursos genéricos". Formação diretamente ligada à atividade é zona cinzenta. |
| **Plano de saúde do profissional** | ⚠️ | Uma fonte secundária afirma que sim; a regra geral trata plano de saúde como despesa médica na declaração anual, **não** como custeio de livro caixa. **Não incluir sem parecer contábil.** |
| **Imposto pago (DARF)** | ❌ | **Não é despesa dedutível.** Lançá-lo reduziria a base indevidamente — o oposto do que o psicólogo quer. |
| Transporte, combustível, estacionamento, IPVA, seguro do carro | ❌ | Vedado, salvo representante comercial autônomo. |
| Depreciação de bens | ❌ | |
| Arrendamento mercantil (leasing) | ❌ | |
| Consertos e benfeitorias em imóvel **próprio** | ❌ | |
| Despesas pessoais (alimentação, roupas, cursos genéricos) | ❌ | |
| INSS do próprio psicólogo | ❌ no livro caixa | É dedução do Carnê-Leão, mas em **linha própria**, não como despesa de custeio. |

**Consequências:**
- Duas contas diferentes e ambas úteis: a **base de imposto** usa só as dedutíveis; o
  **faturamento líquido** do dashboard usa tudo que saiu do bolso.
- Despesa fora do catálogo é cadastrável, com o psicólogo marcando a dedutibilidade — e o
  sistema não deve afirmar o que não sabe.
- Todo lançamento exige comprovante para ser aceito pela Receita: o modelo precisa prever
  anexo desde o início.

## ADR-012 — Precisão fiscal é opcional e progressiva

**Status:** ✅ Aceita — Rodada 5
**Contexto:** As rodadas anteriores vinham empurrando o módulo fiscal para um cadastro pesado —
outras fontes de renda, INSS, dependentes, pensão alimentícia — como pré-requisito de uso. Isso
colide frontalmente com o requisito de produto declarado (ADR-004: a simplicidade do Hamilton
original) e é o tipo de tela que faz o usuário desistir no primeiro dia. O usuário levantou a
questão perguntando se o módulo não estaria ficando complexo demais.

**Diagnóstico:** havia três coisas embrulhadas numa só, com custos muito diferentes:

| Peça | Custo para o usuário | Valor | Veredito |
|---|---|---|---|
| **Registro de despesas** (livro caixa) | Baixo — escolher tipo, valor, data | Alto: sem despesa não existe "faturamento líquido", só faturamento bruto | Mantida no MVP |
| **Geração do CSV do Receita Saúde** | Nenhum — os dados já estão no sistema | Alto: substitui digitar recibo a recibo no e-CAC | Mantida no MVP |
| **Previsão de imposto** | **Alto** — exige 4 dados que o sistema não tem | Alto, mas concentrado na hora certa | Mantida, com precisão opcional |

A complexidade não estava no código. Estava no **número de perguntas feitas ao usuário antes de
ele conseguir usar o sistema**.

**Decisão:** A estimativa fiscal funciona com o que o sistema já sabe — receita registrada menos
despesas dedutíveis — e **declara na tela o que ela não sabe**: *"estimativa considerando apenas
a renda registrada aqui"*. Os dados que refinam o cálculo (outras fontes de renda, INSS,
dependentes, pensão alimentícia) são **campos opcionais** numa área de configuração, nunca
barreira de entrada. A estimativa fica mais precisa conforme forem preenchidos.

**Consequências:**
- P-25 e P-26 deixam de ser decisões de arquitetura e viram campos opcionais.
- O rótulo passa a ter duas formas: sem os dados extras, avisa que só enxerga a renda daqui;
  com eles, some o aviso. O usuário entende a diferença sem ler manual.
- Nenhuma pergunta fiscal no onboarding.
- Não cortamos a previsão: ser pego de surpresa pelo imposto é uma das dores mais fortes do
  autônomo e um motivo real de compra. Também não inventamos precisão que não temos (ADR-010).
- **Princípio geral do projeto, extraído daqui:** quando uma feature exigir dados que o usuário
  não tem à mão, o padrão é **degradar com honestidade**, não bloquear nem chutar.

## ADR-013 — Saídas fiscais fora do MVP; o núcleo financeiro serve os dois regimes

**Status:** ✅ Aceita — Rodada 6
**Contexto:** O usuário levantou se o carnê-leão dentro do sistema não seria complexidade
desnecessária, sugerindo que uma API de nota fiscal compensaria mais. A premissa trazida era de
que existiria um teto legal de R$ 5 mil, acima do qual o psicólogo seria obrigado a ter CNPJ.

**Fatos verificados:**
- **Não existe limite legal.** Nenhuma regra obriga psicólogo a abrir CNPJ por faturamento. O
  que existe é **ponto de equilíbrio econômico**, em torno de **R$ 81 mil/ano (~R$ 6.700/mês)**.
  Caso concreto de fonte: a R$ 7 mil mensais, ~R$ 2.071 de carga como PF contra ~R$ 635 como PJ.
- Psicólogo **não pode ser MEI** (profissão regulamentada). PJ aqui é **ME no Simples Nacional**,
  entrando no **Anexo V (15,5%)** e só caindo para o **Anexo III (6%)** com **Fator R ≥ 28%**,
  o que exige folha ou pró-labore. Nem todo PJ paga 6%.
- Logo, o mercado **não se divide** entre "pequeno é PF, grande é PJ". A escolha de regime é
  estratégica e frequentemente movida por inércia.
- A NFS-e Nacional **tem API**, mas é tributo **municipal**, com o padrão em transição (a
  conversão de lotes de RPS por arquivo é descontinuada em **28/02/2026**). Integra-se via
  agregador (Focus NFe, TecnoSpeed, WebmaniaBR), que **cobra por nota emitida** — custo unitário
  recorrente, não apenas esforço de desenvolvimento.

**Correção de raciocínio registrada:** a exportação para o carnê-leão **não acrescenta** um passo
de trabalho, ela remove vários. O psicólogo PF é obrigado a emitir recibo no Receita Saúde a cada
pagamento recebido; com cobrança por sessão (ADR-002), 20 pacientes semanais geram ~80 recibos
por mês, hoje digitados um a um. O CSV troca 80 lançamentos por 1 importação. A diferença real
frente à NFS-e é outra: o carnê-leão automatiza ~90% (o psicólogo ainda entra no e-CAC), a NFS-e
automatiza 100%.

**Decisão:** **Carnê-leão e NFS-e ficam fora do MVP**, e a escolha entre elas não é feita agora.
Ambas são pontas de saída do mesmo cano. O que as alimenta — consultas, contas a receber,
pagamentos recebidos, despesas, líquido — é **idêntico e independe do regime**. Construído esse
núcleo, qualquer uma das duas pluga depois sem retrabalho.

**Cliente-alvo:** **PF e PJ**, sem exclusão de segmento.

**Consequências:**
- Nenhum trabalho jogado fora: ADR-008 (layout do CSV do Receita Saúde) e ADR-011 (catálogo de
  despesas) permanecem válidos como especificação pronta para quando a ponta for construída.
- ⚠️ **Consequência do cliente ser PF e PJ:** "previsão de impostos" **não é uma feature, são
  duas**. PF calcula por tabela progressiva do carnê-leão; PJ calcula por alíquota do Simples
  Nacional, com Anexo V ou III conforme o Fator R. Ver P-30.
- O **regime tributário** vira campo do perfil do psicólogo. Barato agora, caro depois.
- **Correção à documentação anterior:** estava registrado que a camada financeira do
  `hamilton-api` era integralmente inaproveitável. Falso no cenário PJ — `acessorios/webmania.py`
  é uma integração de NFS-e em funcionamento e passa a ser o único pedaço financeiro do original
  com valor de reuso.
- Decidir com clientes reais, não por dedução: conversar com **psicólogos autônomos do mercado**, que
  respondem quantos são PF e quantos são PJ hoje.

## ADR-014 — Atendimento infantil: responsável legal é entidade de primeira classe

**Status:** ✅ Aceita — Rodada 7
**Contexto:** Confirmado que haverá atendimento de público infantil. A dúvida original era
apenas o CPF do beneficiário exigido pelo CSV do Receita Saúde (ADR-008), mas a investigação
mostrou que o impacto é muito maior e recai sobre **prontuário e ética**, não sobre o fiscal.

**Fatos verificados:**
- **CPF de menor deixou de ser problema geral.** Desde **1º/01/2018** (Provimento nº 63 do CNJ),
  a inclusão do CPF na certidão de nascimento é obrigatória. Todo nascido a partir daí já tem
  CPF. **Resta uma janela:** nascidos antes de 2018 — hoje com 8 anos ou mais — podem não ter, e
  nesse caso o CPF precisa ser solicitado (é gratuito).
- **Autorização é obrigação ética.** O Código de Ética exige autorização de **ao menos um
  responsável legal** para atendimento não eventual de criança, adolescente ou interdito.
- **O tipo de guarda muda a regra.** Em guarda **unilateral**, é necessária a autorização de quem
  detém a guarda. Em guarda **compartilhada**, recomenda-se a de ambos.
- **Responsáveis legais têm direito de acesso** ao prontuário e a cópia dele, limitado às
  informações **estritamente necessárias** ao benefício da criança.
- Quando um responsável **sem a guarda** solicita informações, o detentor da guarda deve ser
  informado do repasse — feito assim, não configura quebra de sigilo.

**Decisão:** O modelo de paciente ganha três eixos distintos, hoje confundidos num só:

| Eixo | Quem é | Para quê |
|---|---|---|
| **Paciente** | quem é atendido | prontuário, consultas, CPF do beneficiário |
| **Pagador** | quem paga | cobrança e recibo (ADR-009) |
| **Responsável legal** | quem autoriza e responde | autorização de atendimento, direito de acesso |

Podem ser a mesma pessoa (adulto pagando a própria terapia), duas ou três pessoas distintas.

**Consequências:**
- `ResponsavelLegal` admite **mais de um por paciente**, com o **tipo de guarda** registrado.
- A **autorização de atendimento** vira registro com data e autor — é peça de defesa do
  psicólogo, exatamente como o prontuário (ADR-005).
- O direito de acesso do responsável é mais restrito que o do paciente adulto: **apenas o
  estritamente necessário**. Uma exportação que entregue o prontuário inteiro ao responsável
  pode configurar excesso. Ver P-32.
- Repasse de informação a responsável sem guarda exige **notificar** quem detém a guarda — ou
  seja, o sistema precisa de **registro de a quem se deu acesso, quando e do quê**.
- ⚠️ Adolescente tem expectativa de sigilo perante os próprios pais. O produto não pode assumir
  que "responsável vê tudo". Ver P-33.

## ADR-015 — Contrato terapêutico: guarda de documento, não geração nem assinatura

**Status:** ✅ Aceita — Rodada 8 (**revisa** a primeira versão desta ADR, da Rodada 7)

**O que mudou:** a Rodada 7 desenhou um app de contratos com geração de documento a partir de
modelo, marcadores e assinatura eletrônica via Autentique, portando o que o `hamilton-api` tem.
A Rodada 8 corrigiu o rumo: **o psicólogo escreve o próprio contrato, fora do sistema**. O
Hamilton oferece um **lugar para guardar** — para ele conferir que fez, buscar, alterar e apagar
quando precisar.

**Decisão:** `contratos` deixa de ser fluxo e vira **repositório**. Some do MVP: geração por
modelo, marcadores, máquina de estados de assinatura e integração com provedor externo.

**Consequências:**
- ✅ **P-35 morre.** Comparar Autentique com D4Sign/Clicksign/ZapSign deixa de ser necessário.
  Nenhum custo por documento entra na conta do produto.
- ✅ O trabalho de investigação do original não foi perdido — permanece registrado abaixo como
  **especificação pronta**, caso a assinatura eletrônica vire feature depois.
- ⚠️ **Tensão a resolver:** "alterar e apagar" colide com o princípio *contrato é histórico,
  nunca substituição*. A colisão só é aceitável porque o **original assinado é o papel**, fora do
  sistema — aqui é cópia de conferência. Se algum dia o Hamilton passar a ser a única via, apagar
  destrói prova. Ver P-38.
- Para menor de idade, a autorização dos pais continua **dentro do contrato** (ADR-014), agora
  como conteúdo do arquivo guardado, não como estado do sistema.
- O contrato guardado cai no armazenamento misto (ADR-019): é pequeno e jurídico, vai para o
  banco.


**Adendo — Rodada 9 (exclusão e alteração, decisão delegada a mim):**
- **Alterar cria versão nova**, nunca sobrescreve. Preserva a resposta a "qual condição valia
  naquele período?", que é o que se pergunta em conflito sobre valor ou falta.
- **Apagar move para lixeira**, não destrói. A exclusão definitiva existe, mas só de dentro da
  lixeira, com confirmação.
- O psicólogo tem o controle que pediu, sem conseguir destruir a própria defesa com um clique
  errado. Fecha P-38.

**Especificação preservada, para se a assinatura eletrônica voltar ao escopo:**
o `hamilton-api` tem em `principais/contratos/` uma integração com a **Autentique** já em
produção, cujo `LEIA-ME.md` documenta armadilhas caras de descobrir sozinho — entre elas que
`signatures[0]` é a conta dona do token e não o paciente (erro **silencioso**), que o
`short_link` volta nulo na criação, e a necessidade de idempotência para não gastar crédito a
cada reenvio. Junto com `acessorios/webmania.py` (ADR-013), é um dos dois pedaços do original com
valor real de reuso.

---

## ADR-016 — Todo prontuário nasce de uma consulta

**Status:** ✅ Aceita — Rodada 7
⚠️ **Corrigida pela ADR-022 (Rodada 10):** o gatilho é a consulta ficar **`REALIZADA`**, não ser cadastrada.

**Decisão:** Uma consulta realizada **cria automaticamente um prontuário pendente**. Não existe
prontuário órfão, sem consulta que o justifique.

**Consequências:**
- A consulta vira o gancho natural do lembrete "você ainda não escreveu este prontuário".
- `prontuarios` depende de `atendimentos`; nunca o contrário.
- O prontuário pendente é um estado legítimo e esperado, não um erro — é o que a Res. CFP
  001/2009 Art. 1º §2º ("permanentemente atualizado") transforma em pendência visível.

---

## ADR-017 — Dois tipos de lembrete, dois donos

**Status:** ✅ Aceita — Rodada 7
**Decisão:** Lembrete de **cobrança** pertence ao `financeiro`; lembrete de **atendimento**
pertence à `agenda`. Ambos entram no escopo. A tela pode reuni-los; a propriedade do dado não.

Um terceiro apareceu de graça na ADR-016: **prontuário pendente**, que pertence a `prontuarios`.

**Consequências:**
- Nenhum app precisa depender do outro para lembrar: cada um sabe o que está pendente no seu
  próprio domínio. `indicadores` reúne para exibir.
- A entrega (canal) é decisão separada da propriedade (ver P-36).
---

## ADR-018 — Lembretes: in-app e Google Agenda, sem agendador

**Status:** ✅ Aceita — Rodada 8
**Decisão:** Os três tipos de lembrete (cobrança, atendimento e prontuário pendente — ADR-017)
são entregues por dois canais no MVP:

| Canal | Como funciona |
|---|---|
| **In-app** | A tela pergunta ao banco o que está pendente **no momento em que carrega**. Não existe tabela de lembretes nem registro pré-computado. |
| **Google Agenda** | O lembrete vira **evento na agenda que o psicólogo já usa**, e o alarme do celular dele faz o trabalho de notificação. |

**Consequências:**
- **Custo de infraestrutura zero, e o impeditivo I-05 desaparece do MVP**: sem canal que empurra,
  não há agendador, cron job nem background worker para pagar.
- Sem tabela de lembretes, não há estado para dessincronizar. O que está pendente é sempre
  derivado do dado real — cobrança em aberto, consulta futura, prontuário não escrito.
- WhatsApp fica registrado como o canal mais eficaz e o mais caro. Só entra depois de haver
  cliente usando para dizer se faz falta.
- ⚠️ Escrever evento na agenda do psicólogo exige **permissão de escrita** no Google, não só
  leitura. Ver P-39.

---

## ADR-019 — Armazenamento misto: banco para o jurídico, object storage para o pesado

**Status:** ✅ Aceita — Rodada 8
**Contexto:** O disco do Render é efêmero (I-04): o `MEDIA_ROOT` é apagado a cada deploy.

**Decisão:**

| Vai para | O quê | Por quê |
|---|---|---|
| **Postgres (bytes)** | Contrato guardado, PDF de prontuário, comprovante de despesa | Pequenos, raros e com valor de prova. Backup e isolamento (ADR-001) saem de graça. |
| **Object storage** | Áudio dos relatos | Grande (~1 MB/min), temporário e descartável depois do prontuário aprovado. Barato por GB e trivial de apagar. |

**Consequências:**
- 🔴 O isolamento entre psicólogos (ADR-001) **precisa valer também no object storage**. RLS não
  alcança bucket: exige chave por tenant e URLs assinadas de vida curta, nunca link público.
- Provedor ainda não escolhido (S3, Cloudflare R2, storage do Neon). R2 é candidato por não
  cobrar egresso.
- A retenção do áudio passa a ser política explícita, não efeito colateral de onde ele caiu.

## ADR-020 — Agenda: o Hamilton é a fonte da verdade, o Google é projeção

**Status:** ✅ Aceita — Rodada 9
**Contexto:** O usuário descreveu o comportamento desejado: o psicólogo cadastra data e horário
de atendimento de cada paciente, e todo dia de manhã recebe um alerta com os atendimentos do dia.
Alterações são feitas por ele mesmo e devem se refletir no aviso.

**Fato verificado:** o Google Agenda tem uma notificação nativa de **"Resumo diário"** (*Daily
agenda*), enviada por e-mail no início do dia (padrão 5h), ligada uma vez pelo psicólogo nas
configurações dele. Ou seja, o alerta matinal **já existe e é gratuito** — não precisamos
construí-lo nem pagar agendador para isso (I-05).

**Decisão:** Sincronização **de mão única**. O `Hamilton` é dono da consulta; o Google Agenda
recebe uma cópia.

| Direção | O quê | Por quê |
|---|---|---|
| **Hamilton → Google** (escrita) | Cada consulta cadastrada vira evento num calendário dedicado, *"Hamilton — Atendimentos"*, dentro da conta do psicólogo | O alarme do celular e o resumo diário passam a funcionar de graça |
| **Google → Hamilton** (leitura) | Compromissos já existentes na agenda dele | Atende o pedido original — "saber quais já estou realizando no mês" — e evita marcar em cima de outro compromisso |

**Por que o Hamilton é a fonte da verdade, e não o Google:** a consulta é a âncora do prontuário
(ADR-016) e da cobrança (ADR-002). Uma sessão que só existe no Google não gera prontuário
pendente nem conta a receber — sumiria do sistema inteiro. O calendário pode espelhar a consulta;
a consulta não pode viver no calendário.

**Por que mão única, e não sincronização nos dois sentidos:** sincronização bidirecional exige
resolver conflito quando os dois lados mudam entre uma sincronização e outra, e é uma das fontes
clássicas de bug caro e silencioso. Mão única não tem conflito porque não tem disputa.

**Consequências:**
- ⚠️ **Exige permissão de escrita** no OAuth do Google. O psicólogo vê "gerenciar seus
  calendários" em vez de "ver seus calendários" — passo em que parte das pessoas desiste. Por
  isso a permissão é pedida **quando ele ativar o recurso**, com a explicação na tela, e não no
  primeiro minuto do cadastro.
- **Calendário dedicado, nunca o pessoal dele.** Isola nossas escritas, ele pode ocultar com um
  clique, e o descarte no cancelamento (ADR-007) vira apagar um calendário só.
- Lembrete de cada atendimento é configurável **por evento** via API. O resumo matinal é
  configuração da conta dele: o sistema deve **ensinar a ligar**, não prometer o que não controla.
- 🔴 Se ele editar o evento direto no Google, a mudança **não volta** para o Hamilton, e os dois
  lados divergem em silêncio. O produto precisa dizer isso na cara, não escondê-lo. Ver P-42.
- O pedido "que já vai estar com a data alterada porque o próprio psicólogo já reorganizou" só se
  cumpre se ele reorganizar **no Hamilton**. Isso é mudança de hábito para quem hoje vive no
  Google Agenda, e é o principal risco de adoção deste módulo.

---

## ADR-021 — App `documentos`, com contrato sendo um dos tipos

**Status:** ✅ Aceita — Rodada 9
**Contexto:** São três necessidades com a mesma forma — arquivo ligado a um paciente, com tipo e
regra de quem vê:

| Origem | O quê |
|---|---|
| Pedido do usuário | Contrato terapêutico guardado para conferência (ADR-015) |
| Res. CFP 001/2009, Art. 2º, **inciso V** | Anexos de avaliação psicológica, em pasta de **acesso exclusivo do psicólogo** |
| Res. CFP 001/2009, Art. 2º, **inciso VI** | Cópias de documentos emitidos, com **data de emissão, finalidade e destinatário** |

**Decisão:** Um app `documentos`, dono de `Documento` (arquivo, tipo, vigência, visibilidade,
versões). `contrato` é um `tipo`, não um app.

**Consequências:**
- Upload, listagem, permissão, versionamento e retenção existem **uma vez**, não três.
- A regra de **acesso exclusivo do psicólogo** (inciso V) é modelada uma vez, no lugar onde todos
  os documentos vivem — e é a mesma peça que vai servir ao sigilo do adolescente (P-33).
- O inciso VI exige campos que o contrato não tem: finalidade e destinatário. São opcionais por
  tipo, não obrigatórios em todo documento.
- Fecha P-40. O total de apps volta a **dez**.

## ADR-022 — Consulta recorrente com exceção por ocorrência

**Status:** ✅ Aceita — Rodada 10
**Contexto:** O usuário descreveu como o atendimento clínico realmente funciona: quase sempre é
**fixo** (mesmo dia e horário toda semana), mas **vez ou outra remarca**. O sistema precisa
tratar o caso comum sem atrito e o caso excepcional sem gambiarra — e lembrete, prontuário e
cobrança precisam seguir a data que **de fato** valeu.

Este é o problema clássico de *recorrência com exceções*, o mesmo que o padrão iCalendar resolve
com regra de repetição mais sobrescrita por ocorrência. Modelar errado aqui contamina agenda,
prontuário e financeiro de uma vez só.

**Decisão — duas camadas:**

| Camada | O que é | Papel |
|---|---|---|
| **Recorrência** | A combinação fixa do paciente: "toda terça, 15h" | Não é atendimento. É a **regra** que gera atendimentos. |
| **Consulta** | Uma ocorrência concreta, com data e hora próprias | É o que existe de verdade: sincroniza com o Google, recebe prontuário e gera cobrança. |

As consultas são **materializadas** a partir da regra numa janela contínua à frente (ordem de
grandeza: 8 semanas), e **cada uma é editável isoladamente**. Remarcar uma terça para quinta
altera aquela consulta e **não toca na regra** — é exatamente a flexibilidade pedida.

**Correção à ADR-016:** estava escrito que "cadastrar consulta cria o prontuário pendente".
**Errado**, e a recorrência expõe o porquê: materializando 8 semanas à frente, o psicólogo
acordaria com 8 prontuários pendentes e 8 cobranças de sessões que ainda não aconteceram.

O gatilho correto é o **acontecimento**, não o agendamento. A consulta passa a ter estado:

| Estado | Significa | Dispara |
|---|---|---|
| `AGENDADA` | marcada, ainda não aconteceu | evento no Google, lembrete de atendimento |
| `REALIZADA` | aconteceu | **prontuário pendente** e, no modo por sessão, **conta a receber** |
| `FALTA` | paciente não veio | depende de `contabilizada` — ver ADR-023 |
| `CANCELADA` | desmarcada com antecedência | nada |

Isso também dá de graça o indicador "sessões previstas × realizadas" que o dashboard do Hamilton
original já calcula.

**Consequências:**
- `prontuarios` e `financeiro` dependem do **estado** da consulta, não da sua existência.
- A materialização precisa de uma janela: gerar tudo até o infinito é inviável, gerar de menos
  esvazia a agenda. Janela contínua, empurrada para frente conforme o tempo passa — e, sem
  agendador (ADR-018), ela avança **quando o psicólogo abre a agenda**, não por processo de fundo.
- Alterar a **regra** ("agora é quinta às 16h") precisa dizer a partir de quando vale, sem
  reescrever o passado. Ver P-45.
- Pausa de férias e feriado são ausências de ocorrência, não cancelamentos individuais um a um.

---

## Adendo à ADR-020 — Edição no Google volta por confirmação

**Status:** ✅ Aceita — Rodada 10
**Decisão:** Confirmada a opção **(a)**: o Hamilton **detecta** que o evento foi movido no Google
e oferece atualizar aqui também.

Isso reconcilia a mão única (ADR-020) com o pedido de que alterar **em qualquer um dos dois
lados** mantenha lembrete, prontuário e cobrança amarrados à data certa. O Google continua sem
poder criar consulta do nada — o que evitaria o bug silencioso da sincronização bidirecional —
mas **mover** uma consulta existente volta, com um toque de confirmação.

**Consequências:**
- A detecção acontece na leitura da agenda, que já é feita para evitar marcação sobreposta
  (ADR-020). Não custa chamada nova.
- Divergência nunca é resolvida em silêncio: quem decide é o psicólogo, não uma regra nossa
  de "quem escreveu por último ganha".
- Evento apagado no Google é caso à parte de evento movido, e não deve ser tratado como
  cancelamento automático da consulta.

## ADR-023 — Comparecimento e cobrança são eixos independentes

**Status:** ✅ Aceita — Rodada 11
**Contexto:** Pergunta do usuário: "tem a possibilidade do sistema se adaptar ao estilo do
psicólogo?" — uns cobram falta, outros não. A resposta dele apontou o mecanismo certo: os dois
checks do registro de consultas do Hamilton original, **realizada** e **contabilizada**. "As
consultas contabilizadas serão cobradas."

**Fato:** o `hamilton-api` já modela exatamente isso — `Consulta.is_realizado` e
`Consulta.is_cont`. São campos **independentes**, e é essa independência que carrega a regra.

**Decisão:** Separar o que **aconteceu** do que **se cobra**:

| Eixo | Campo | Responde | Dispara |
|---|---|---|---|
| **Comparecimento** | `estado` | A sessão aconteceu? | `REALIZADA` → **prontuário pendente** |
| **Cobrança** | `contabilizada` | Esta sessão entra na conta? | verdadeiro → **conta a receber** (modo por sessão) |

A combinação cobre todos os casos sem regra escondida:

| Situação | Estado | Contabilizada | Resultado |
|---|---|---|---|
| Sessão normal | `REALIZADA` | ✅ | Prontuário pendente + cobrança |
| Falta, e o psicólogo cobra falta | `FALTA` | ✅ | Só cobrança — sem prontuário, porque não houve sessão |
| Falta, e o psicólogo não cobra | `FALTA` | ❌ | Nada |
| Desmarcada a tempo | `CANCELADA` | ❌ | Nada |
| Sessão de cortesia / devolutiva | `REALIZADA` | ❌ | Prontuário pendente, sem cobrança |

**Como o sistema se adapta ao estilo:** o valor de `contabilizada` vem de um **padrão no perfil
do psicólogo** ("cobro falta: sim/não") e é **sobrescrevível em cada consulta**. Mesmo padrão já
adotado no vencimento da mensalidade (ADR-002): configura uma vez, ajusta na exceção.

**Consequências:**
- Fecha P-44 sem inventar regra: quem cobra falta marca a falta como contabilizada e a pendência
  aparece; quem não cobra, não marca.
- A última linha da tabela — sessão realizada e não cobrada — é caso real (devolutiva, cortesia,
  sessão de acolhimento gratuita) que um único campo de estado não conseguiria representar.
- **Prontuário nunca depende de cobrança**, e vice-versa. Falta não gera prontuário mesmo quando
  gera cobrança, porque não houve atendimento a registrar.

---

## Adendo à ADR-022 — Remarcação avulsa e o que falta modelar

**Status:** ✅ Aceita — Rodada 11

**Remarcação avulsa** (paciente das terças 14h que, numa semana específica, vem na segunda):
a consulta daquela semana é uma **linha concreta** com data e hora próprias. O psicólogo abre
aquela ocorrência, muda de terça 03/11 para segunda 02/11, e pronto — a **regra permanece
intocada** e a semana seguinte volta a ser terça, sozinha.

Para isso funcionar, a ocorrência precisa **lembrar que veio da regra e que foi alterada à mão**.
Sem essa marca, uma futura mudança na regra passaria por cima da remarcação e devolveria a
consulta para a terça, desfazendo em silêncio o que o psicólogo combinou com o paciente.

**Escolha de escopo confirmada:** só existem **"só esta"** e **"esta e as próximas"**. "Todas"
não é oferecida — reescreveria consultas passadas, que são registro histórico ligado a prontuário
e cobrança, não agenda.

**Lacuna encontrada — a consulta não tem hora.** No `hamilton-api`, `Consulta.dat_consulta` é um
campo de **data**, sem horário. Para o Individual isso não serve: escrever evento no Google
Agenda (ADR-020) exige início **e** fim. A consulta passa a ter **data, hora e duração**, com
duração padrão no perfil do psicólogo (a sessão de 50 minutos é a convenção). Divergência
deliberada em relação ao original.

**Férias e feriados:** adiados a pedido do usuário. Ver P-47.

## ADR-024 — Colisão de horário bloqueia a marcação

**Status:** ✅ Aceita — Rodada 12 (decisão do usuário, **contra** a recomendação registrada)
**Decisão:** Se a nova data e hora colidirem com outra consulta ou com compromisso lido da agenda
do Google, o sistema **não deixa salvar**.

**Recomendação que havia sido feita e não acatada:** avisar e permitir salvar, sob o argumento de
que o psicólogo é o único usuário da própria agenda e sabe mais do que o sistema sobre a própria
grade. Registrado aqui para que, se o bloqueio incomodar na prática, a alternativa esteja
documentada e não precise ser redescoberta.

**Consequências:**
- Fecha P-48.
- 🔴 **Caso real que vai bater no bloqueio: atendimento de casal ou família** — duas pessoas, um
  horário. Também o encaixe curto entre sessões. Ver P-50, que é mais amplo que a colisão.
- A checagem depende da agenda do Google ter sido lida recentemente. Compromisso criado no Google
  há dois minutos pode não estar visível, e o bloqueio não vê o que não leu.

---

## ADR-025 — Princípio: configura uma vez, ajusta na exceção

**Status:** ✅ Aceita — Rodada 12
**Contexto:** O mesmo padrão emergiu sozinho em quatro decisões independentes, o que o torna
princípio e não coincidência:

| Configuração | Padrão em | Sobrescrito em |
|---|---|---|
| Vencimento da mensalidade (ADR-002) | perfil do psicólogo | paciente |
| Cobrança de falta (ADR-023) | perfil do psicólogo | consulta |
| Duração da sessão | perfil do psicólogo | paciente |
| Modalidade de cobrança (ADR-002) | — | paciente |

**Decisão:** Toda preferência de comportamento tem **padrão no perfil do psicólogo** e é
**sobrescrevível no nível mais específico** em que faça sentido. Nunca se pergunta ao usuário,
a cada cadastro, algo que ele já respondeu uma vez.

**Consequências:**
- Casa com o requisito de simplicidade (ADR-004) e com a ADR-012: menos perguntas na frente do
  usuário, sem perder capacidade.
- O cadastro de paciente fica curto por padrão, com os ajustes finos escondidos atrás de
  "personalizar".
- Toda tela de cadastro precisa deixar visível **de onde veio** o valor herdado, ou o psicólogo
  não entende por que um campo já está preenchido.

**Duração da sessão:** padrão no perfil (convenção de 50 minutos), ajustável por paciente —
terapia infantil costuma ser mais curta, casal mais longa, avaliação psicológica bem mais.
Fecha P-49.

## ADR-026 — `Caso` como unidade de atendimento (casal, família, grupo)

**Status:** ✅ Aceita — Rodada 15 (proposta na Rodada 13, esclarecida e validada na 15)
**Contexto:** Confirmado que haverá atendimento de casal. Isso quebra a premissa silenciosa de
que **uma consulta pertence a um paciente**, herdada do `hamilton-api` (`Consulta.fk_paciente`).
A Res. CFP 001/2009, Art. 5º, III exige que, em atendimento de grupo não eventual, o psicólogo
mantenha **documentação individual de cada usuário**, além dos registros do atendimento.

**O problema com as saídas óbvias:**
- *Casal como um "paciente" de nome composto* — some a documentação individual exigida pelo CFP,
  e o CPF do beneficiário (ADR-008) fica impossível.
- *Consulta ligada a vários pacientes direto* — resolve a sessão, mas deixa sem dono o que é do
  **vínculo**: o valor acordado, a modalidade de cobrança, a recorrência e o contrato. Numa
  terapia de casal, o valor é do casal, não de cada um.

**Decisão proposta:** introduzir **`Caso`** — o vínculo terapêutico, que reúne de 1 a N pacientes.

| Pertence ao `Caso` | Pertence ao `Paciente` | Pertence à `Consulta` |
|---|---|---|
| Valor acordado e modalidade de cobrança (ADR-002) | Dados pessoais, CPF, endereço | Data, hora, duração, estado |
| Recorrência (ADR-022) | Responsável legal (ADR-014) | `contabilizada` (ADR-023) |
| Contrato (ADR-015) | **Prontuário** — um por paciente, por sessão | Conta a receber |
| Pagador (ADR-009) | | |

**Por que isso é melhor do que parece:** uma mesma pessoa pode ser paciente individual **e**
integrar um casal atendido pelo mesmo psicólogo. Sem `Caso`, esses dois vínculos colidem — mesmo
paciente, dois valores, duas recorrências, dois contratos. Com `Caso`, são dois vínculos
distintos da mesma pessoa, que é exatamente a realidade clínica.

**Custo, e como pagá-lo:** é um conceito a mais. A interface **não o expõe** no caso comum:
cadastrar um paciente cria, em silêncio, um caso de um. A palavra "caso" só aparece para quem
atende casal ou família.

**Consequências:**
- `Consulta` deixa de apontar para `Paciente` e passa a apontar para `Caso`. A presença é
  registrada por participante — num casal, um pode faltar e o outro não.
- **Um prontuário por paciente por sessão** (CFP Art. 5º, III). Numa sessão de casal, o
  psicólogo escreve dois — ou um relato que a IA divide. Ver P-53.
- O bloqueio de colisão (ADR-024) deixa de disparar no caso de casal: é **uma** consulta com dois
  participantes, não duas consultas no mesmo horário. O problema que motivou esta ADR se dissolve.
- Cobrança continua sendo uma por consulta, ligada ao pagador do caso — não uma por participante.
- ⚠️ Divergência estrutural em relação ao `hamilton-api`, que é rigidamente um-paciente-por-consulta.

**Esclarecimento — Rodada 15 (pergunta do usuário: a separação só existe quando for casal?):**

**Uma forma só no banco, duas formas na tela.**

| Camada | Individual | Casal |
|---|---|---|
| **Tela** | Nenhum campo a mais. A palavra "caso" não aparece em lugar nenhum. | Aparece a seleção de participantes. |
| **Banco** | O caso **existe**, com um participante, criado em silêncio. | O mesmo caso, com dois. |

**Por que a estrutura não pode ser opcional:**
1. **Conversão em produção.** Paciente individual de oito meses que passa a fazer terapia de
   casal é caso corriqueiro. Com a estrutura sempre presente, é criar um atendimento novo. Sem
   ela, é migração de dados com o sistema no ar, arriscando histórico de sessões e pagamentos.
2. **Dois caminhos em toda parte.** Estrutura opcional obrigaria cobrança, agenda, prontuário e
   relatórios a perguntarem "isto é caso ou paciente solto?", cada um com dois ramos. É
   exatamente assim que nasce o `views.py` de 5.639 linhas do original.

A complexidade fica onde é barata — no modelo — e não onde é cara: na frente do usuário.
Mesma lógica da ADR-025.

**A pessoa é única entre atendimentos.** Maria paciente individual e Maria integrante do casal
são **o mesmo cadastro**: mesmo CPF, mesmo endereço, mesmo histórico pessoal. O que se separa por
atendimento é o **prontuário**, porque a sessão individual e a sessão de casal são sessões
distintas.

---

## ADR-027 — Painel operacional e análise são telas diferentes

**Status:** ✅ Aceita — Rodada 13
**Contexto:** "Dashboard" vinha nomeando duas coisas com ritmos e propósitos distintos.

**Decisão:**

| Tela | Pergunta que responde | Ritmo | Formato |
|---|---|---|---|
| **Painel** | "O que eu preciso fazer?" | diário | pendências e ação; curto, sem rolagem |
| **Análise** | "Como eu estou indo?" | mensal ou eventual | tendência e comparação; pode ser denso |

**Conteúdo do painel** (decisão do usuário):
- Pacientes ativos, com último atendimento e dias sem atender (herdado do original)
- Resumo por paciente: sessões do mês e pendência de pagamento
- Pendências de ação: cobranças em aberto, **prontuários não escritos** (ADR-016)
- Três indicadores de cabeçalho: **receita líquida**, **ocupação da agenda**, **entradas × saídas**

**Conteúdo da análise:** as perguntas mais profundas, para quem quiser investigar.

**Consequências:**
- Se o painel ganhar gráfico decorativo, deixa de ser ferramenta de trabalho. Densidade é
  requisito, não gosto (ADR-004).
- `indicadores` (o app) serve as duas telas, mas com consultas diferentes: o painel lê o estado
  **agora**, a análise agrega **histórico**.
- **Princípio:** a análise usa apenas dado administrativo — sessões, valores, datas, desfechos.
  **Nunca conteúdo de prontuário.** Não se faz estatística com o que o paciente falou.

## ADR-028 — Atendimento coletivo: um relato, um prontuário por paciente

**Status:** ⚠️ **Revisada pela ADR-041 (Rodada 24)** — a IA não divide mais o relato. Passa a ser um relato gravado por participante.
**Contexto:** A Res. CFP 001/2009, Art. 5º, III exige documentação individual de cada usuário em
atendimento de grupo não eventual. Cumprir isso pedindo ao psicólogo que dite um relato por
participante devolveria justamente o trabalho que o produto existe para eliminar.

**Decisão:** O psicólogo grava **um relato** sobre a sessão. A IA gera **um prontuário por
paciente participante**, com o que é pertinente a cada um. Ele revisa e confirma cada um antes de
virar registro oficial (ADR-005, rascunho obrigatório).

**Consequências:**
- Cumpre a exigência do CFP sem custo humano adicional. É um dos usos em que a IA entrega valor
  que nenhuma automação simples entregaria.
- 🔴 **Risco clínico específico:** numa sessão de casal, o que um disse sobre o outro não pode
  migrar para o prontuário do outro sem critério. O prontuário de cada um é acessível a ele
  (Art. 5º, II) — e vazar a fala de um cônjuge para o prontuário do outro é falha grave. A
  instrução da IA precisa tratar isso explicitamente, e a revisão humana deixa de ser formalidade.
- O relato original é insumo único ligado à consulta; os prontuários gerados são N, ligados a
  cada paciente.

---

## Adendo à ADR-027 — Indicadores escolhidos

**Status:** ✅ Aceita — Rodada 14

**Painel** (diário, ação):
1. Receita líquida · 2. Ocupação da agenda · 3. Entradas × saídas de pacientes
— mais pacientes ativos com dias sem atender, resumo por paciente e pendências.

**Análise** (eventual, profundidade):

| Pergunta | De onde sai |
|---|---|
| **Quanto do meu faturamento depende de um paciente só?** | Pagamentos agrupados por caso, sobre o total. Revela risco de concentração que ninguém enxerga até o paciente sair. |
| **Em que momento as pessoas desistem?** | Contagem de sessões realizadas antes do desfecho de desistência. |
| **Quantas horas trabalho por semana, e quantas tenho disponíveis?** | Soma das durações das consultas `REALIZADAS` contra a grade de horários declarada. **Definição do usuário: trabalhar = só horário de atendimento.** |
| **Quantas sessões faço por mês?** | Consultas `REALIZADAS` no período. |

**Achado que barateia tudo:** **nenhum dos quatro exige campo novo.** Todos são derivados de dado
que as ADRs anteriores já mandam guardar. Em particular, "em que momento desistem" é **calculado**
(quantas sessões houve antes da desistência), e não perguntado — o original guarda um `momento`
grosseiro por escolha, e derivar dá resposta melhor sem trabalho para o usuário.

**Excluído deliberadamente:** "de onde vêm meus pacientes". Exigiria um campo de origem no
cadastro, e o usuário não o priorizou. ⚠️ É o único da lista **impossível de preencher
retroativamente** — daqui a um ano ninguém lembra como cada paciente chegou. Reabrir custa caro.

## ADR-029 — Horários disponíveis são declarados pelo psicólogo, ocupação é derivada

**Status:** ✅ Aceita — Rodada 16
**Contexto:** O indicador "quantas horas trabalho × quantas tenho disponíveis" precisa de um
denominador. O usuário definiu como consegui-lo: na área de horários, o psicólogo registra
**quais horários da semana ele ainda tem para atender**, adicionando e apagando quando quiser.
O `hamilton-api` já tem essa peça (`HorarioDisponivel`, com dia da semana, hora de início e fim,
e a tela `gerenciar_horarios.html`) — reuso direto.

**Decisão:** O psicólogo declara sua grade. Nenhuma pergunta de configuração barra o cadastro
(ADR-012): quem não declarar perde apenas esse indicador.

**Refinamento sobre o pedido — a manutenção é automática.** Registrar manualmente "quais horários
ainda tenho livres" tem um defeito conhecido: ao marcar um paciente na terça 15h, o psicólogo
teria de lembrar de apagar aquele horário da lista de livres. Ninguém lembra, e em duas semanas a
lista mente — e o indicador de ocupação mente junto.

Por isso a grade declarada é de **disponibilidade**, não de vagas remanescentes, e o sistema
**subtrai sozinho** o que já tem paciente:

| Vem de | O quê |
|---|---|
| Declarado pelo psicólogo | A grade: "atendo terça e quinta, das 14h às 20h" |
| Derivado pelo sistema | Quais faixas dessa grade já têm consulta recorrente — marcadas como ocupadas |
| Calculado | **Ocupação** = horas com atendimento ÷ horas da grade |

Ele continua adicionando e apagando à vontade, como pediu. O que ele **não** precisa fazer é
manutenção dupla.

**Consequências:**
- A tela de horários deixa de ser uma lista morta e vira o mapa da semana — mostra o que está
  ocupado, por quem, e o que sobrou. É a mesma tela que responde "tenho vaga para paciente novo?".
- "Horas trabalhadas" usa a definição do usuário: **só horário de atendimento**, somando as
  durações das consultas `REALIZADAS`.
- A grade declarada **não** bloqueia marcação fora dela. O bloqueio existente é só o de colisão
  (ADR-024); marcar um encaixe num sábado deve continuar possível.
- Fecha P-54. **`Caso` fica como nome também na interface** — decisão do usuário. Fecha P-55.

## ADR-030 — Regime tributário no perfil, e lembrete fiscal ciente do regime

**Status:** ✅ Aceita — Rodada 17
**Decisão:** O perfil do psicólogo guarda se ele atua como **PF** ou **PJ**, ao lado de CPF, CRP e
dados fiscais opcionais (ADR-012). Era consequência já prevista na ADR-013 e agora é requisito
explícito.

**O lembrete fiscal muda conforme o regime:**

| Regime | O que o sistema lembra |
|---|---|
| **PF** | "Emita o recibo no Receita Saúde" — obrigatório desde 01/2025 (ADR-008), um por pagamento recebido |
| **PJ** | "Emita a nota fiscal" |

⚠️ **Ressalva importante ao pedido do usuário.** Foi dito que o sistema "ajuda mais quem é PJ
porque tem a API de nota fiscal". **A API de NFS-e está fora do MVP** por decisão do próprio
usuário na ADR-013, junto com o carnê-leão. O que entra aqui é apenas o **lembrete** — que é
barato, não depende de integração nenhuma e serve aos dois regimes igualmente. Quando a
integração de NFS-e for construída, o lembrete do PJ vira ação de um clique; até lá, os dois
regimes recebem aviso e emitem por fora.

Registrado para que a diferença entre *lembrar* e *emitir* não se perca.

---

## ADR-031 — Recorrência quinzenal e outras periodicidades

**Status:** ⚠️ **Revisada pela ADR-053 (Rodada 30)** — não existe sessão mensal; as frequências são semanal, quinzenal ou avulso.

**Status original:** ✅ Aceita — Rodada 17
**Contexto:** Verificação levantada pelo usuário: o sistema precisa distinguir atendimento
**semanal** de **quinzenal**.

**Decisão:** A regra de recorrência (ADR-022) carrega **periodicidade**, não apenas dia e hora:
semanal, quinzenal e mensal. A materialização das consultas respeita o intervalo.

**Consequências:**
- Quinzenal exige uma **âncora** — a data da primeira ocorrência —, porque "quinzenal" sozinho
  não diz quais semanas. Sem âncora, o sistema não sabe se é a semana par ou a ímpar.
- Afeta a **ocupação** (ADR-029): um horário quinzenal ocupa metade de uma faixa semanal, e
  tratá-lo como semanal faria a agenda parecer mais cheia do que está.
- Afeta a **previsão de receita**: paciente quinzenal a R$ 200 rende R$ 400 no mês, não R$ 800.
  O Hamilton original não tem esse conceito, então a conta dele erraria.
- Semanal permanece o padrão, por ser o caso dominante.

---

## ADR-032 — IA de documentos psicológicos, pela Resolução CFP 06/2019

**Status:** ✅ Aceita — Rodada 17
**Contexto:** Pedido do usuário: uma IA na aba de documentos que produza documentos conforme as
normas do CRP, com modelos de **todos** os documentos que um psicólogo pode emitir, para ele não
precisar caçar como se faz nem montar do zero.

**Fato levantado — a norma é a Resolução CFP nº 06/2019**, que define **seis** modalidades, cada
uma com estrutura obrigatória:

| Documento | Estrutura obrigatória | Regra que a IA **não pode** violar |
|---|---|---|
| **Declaração** | Título · nome · finalidade · local, dias, horários e duração do acompanhamento · encerramento com local, data, carimbo, CRP e assinatura | 🚫 **Vedado registrar sintomas, situações ou estados psicológicos** (Art. 9º, §1º) |
| **Atestado Psicológico** | Título · nome · solicitante · finalidade · descrição das condições psicológicas | Resulta de **avaliação psicológica**. Texto corrido **sem parágrafos**, para evitar adulteração; se houver, preencher com traços (Art. 10, §5º) |
| **Relatório Psicológico** | **5 itens**: Identificação · Descrição da demanda · Procedimento · Análise · Conclusão | — |
| **Relatório Multiprofissional** | Estrutura própria, com equipe | Fora do escopo individual — ver P-58 |
| **Laudo Psicológico** | **6 itens**: Identificação · Descrição da demanda · Procedimento · Análise · Conclusão · **Referências** | Citação de referências é **obrigatória**. É resultado de processo de avaliação psicológica |
| **Parecer Psicológico** | **5 itens**: Identificação · Descrição da demanda · Análise · Conclusão · **Referências** | Exige do autor **titulação que comprove conhecimento específico** no assunto |

**Art. 17 — prazo de validade do conteúdo** deve constar no **último parágrafo**, e se aplica a
Atestado, Laudo e Relatório.

**Decisão:** A IA de documentos é feature do app `documentos`, distinta da IA de prontuário
(ADR-006). São pipelines diferentes: prontuário **transforma um relato**; documento **preenche
uma estrutura normativa** a partir de dados do sistema mais entrada do psicólogo.

**Consequências:**
- Vale a ADR-005: **rascunho obrigatório com revisão e confirmação**. Documento que sai errado
  não é bug de tela — é o psicólogo respondendo processo no CRP com o nome dele no papel.
- As vedações são **restrições de geração**, não sugestões. Uma declaração que mencione sintoma
  viola a resolução, e a instrução da IA precisa impedir isso estruturalmente.
- Atestado, Laudo e Parecer pressupõem coisas que o sistema não tem: avaliação psicológica
  realizada, referências bibliográficas, titulação. A IA **não pode inventá-las**.
- 🔴 Os Conselhos Regionais podem exigir, em até **cinco anos**, a fundamentação técnico-científica
  de um atestado (Art. 10, §4º). O documento gerado precisa ficar amarrado ao registro que o
  fundamenta.
- Priorização sugerida: **Declaração** primeiro — é a mais simples, a mais pedida no dia a dia
  ("preciso de um documento comprovando que faço terapia") e a de menor risco.

---

## ADR-033 — Diretrizes do CRP consultáveis dentro do sistema

**Status:** ✅ Aceita — Rodada 17
**Decisão:** A aba de documentos oferece as diretrizes do CFP sobre documentos escritos, para
consulta na íntegra por quem quiser conferir.

**Consequências:**
- ⚠️ **Manter texto normativo dentro do produto cria dever de atualização.** A Res. 06/2019
  revogou a 07/2003; o CFP publicou **Manual Orientativo em novembro de 2025**. Norma exibida
  desatualizada é pior que norma ausente, porque parece autoridade.
- Direito autoral: atos oficiais não são protegidos (Lei 9.610/98, Art. 8º, IV), então reproduzir
  o texto da resolução é lícito. **Manuais e cartilhas do CFP são outra coisa** — para esses,
  o caminho seguro é link para a fonte oficial, não cópia.
- Recomendação: **exibir a resolução e linkar o manual**, com data da versão visível.

## ADR-034 — Escopo dos documentos e acesso da IA ao material clínico

**Status:** ✅ Aceita — Rodada 18 (decisão delegada a mim pelo usuário)

### 1. A IA de documentos tem acesso **por tipo**, nunca acesso geral

| Documento | O que a IA recebe |
|---|---|
| **Declaração** | Apenas nome, datas, horários e duração do acompanhamento. **Não vê o prontuário.** |
| **Relatório Psicológico** | Material clínico do caso |
| **Atestado / Laudo / Parecer** | Material clínico mais a avaliação psicológica que os fundamenta |

**Por que estrutural e não por instrução:** a Declaração é **proibida** de conter sintomas ou
estados psicológicos (Res. 06/2019, Art. 9º, §1º). Se a IA tiver o prontuário à mão e apenas for
instruída a não usá-lo, um dia ela usa — e o resultado é documento em desacordo com a resolução,
assinado pelo psicólogo. Não entregar o dado é a única garantia que não depende de comportamento.

### 2. Avaliação psicológica é módulo próprio, depois do MVP

Tem norma própria (Res. CFP 31/2022), SATEPSI, instrumentos com validade e fluxo de aplicação.
**Consequência assumida:** **Atestado e Laudo saem do MVP junto com ela**, porque ambos
"resultam de um processo de avaliação psicológica" e o CRP pode exigir a fundamentação em até
cinco anos (Art. 10, §4º). Oferecer geração de documento cuja fundamentação o sistema não sabe
registrar seria expor o psicólogo, não ajudá-lo.

### 3. Escopo final dos documentos

| Documento | Quando | Por quê |
|---|---|---|
| **Declaração** | ✅ MVP | A mais pedida no dia a dia, a mais simples e a de menor risco |
| **Relatório Psicológico** | ✅ MVP | Comum quando escola, outro profissional ou o Judiciário pede |
| **Atestado Psicológico** | ⏸️ Com o módulo de avaliação | Exige diagnóstico fundamentado |
| **Laudo Psicológico** | ⏸️ Com o módulo de avaliação | É o produto da avaliação; exige referências |
| **Parecer Psicológico** | ⏸️ Baixa prioridade | Documento de especialista; exige titulação comprovada no assunto |
| **Relatório Multiprofissional** | ❌ Fora | Pressupõe equipe. Não faz sentido em produto para quem trabalha sozinho |

Fecha P-57, P-58 e P-59. P-56 vira módulo futuro.

## ADR-035 — Registro de pagamento: herda a tela do original, ganha a baixa

**Status:** ✅ Aceita — Rodada 19 (decisão delegada a mim nas duas questões)
**Contexto:** O usuário confirmou que gosta das informações pedidas no registro de pagamentos do
Hamilton original. Levantamento do `PagamentoForm` e da listagem: o formulário pede **terapeuta,
paciente, nome de quem pagou, valor, data do pagamento e observação**; a lista mostra data,
paciente, quem pagou, terapeuta, valor e origem, com busca, filtro por mês e ordenação.

**Mapeamento para o Individual:**

| Campo do original | Destino |
|---|---|
| `fk_terapeuta` | **Removido.** Há um psicólogo só; o campo é ruído em toda tela |
| `fk_paciente` | Mantido; por baixo aponta para o **caso** (ADR-026) |
| `nome` (quem pagou) | Mantido, porém **preenchido a partir do Pagador** (ADR-009) em vez de digitado à mão a cada registro |
| `vlr_pago` | Mantido |
| `dat_pagamento` | Mantido. É o campo mais importante do fiscal — o regime é de **caixa** |
| `observacao` | Mantido |
| Origem (Stripe / manual) | Substituído por **forma de pagamento** |

Busca, filtro por mês e ordenação da listagem são portados como estão.

### 1. O pagamento dá baixa numa cobrança, com parcial permitida

No original o pagamento é **solto**: registra-se que entraram R$ 200 do Fulano e pronto. Isso
funciona lá porque não existe conta a receber. Aqui existe (ADR-002), e sem amarrar o pagamento à
cobrança o sistema nunca saberia se aqueles R$ 200 quitaram a sessão de setembro ou a de agosto
que estava atrasada — e a tela de pendências passaria a mentir.

**Baixa parcial é permitida:** paciente que deve R$ 200 e paga R$ 150 deixa saldo de R$ 50, que
continua aparecendo como devido. É o comportamento que o psicólogo espera, e o único que mantém
o lembrete de cobrança (ADR-017) correto.

### 2. Forma de pagamento, opcional

PIX, dinheiro, transferência, cartão. No original o campo "origem" existia só para separar Stripe
de manual; aqui todo pagamento do paciente é manual, então o campo é reaproveitado com outra
função: conferência de extrato e separação entre o que passou pela conta bancária e o que foi em
espécie — distinção que importa na prestação de contas ao contador.

**Opcional por decisão:** campo obrigatório que ninguém quer preencher vira lixo digitado no
automático, o que é pior do que campo vazio.

**Consequências:**
- O pagamento passa a ter dois vínculos: a **cobrança** que ele quita e o **pagador** que o fez.
- Pagamento sem cobrança correspondente (adiantamento, pacote pago à frente) é caso a tratar.
  Ver P-61.
- O bug A-02 do original (soma × último pagamento do mês) fica impossível por construção: o saldo
  é sempre devido menos baixas, sobre registros.

## ADR-036 — Assinatura: cartão e PIX Automático, sem teste gratuito

**Status:** ✅ Aceita — Rodada 20

**Meios aceitos: cartão de crédito e PIX Automático.** Ambos cobram sozinhos. Boleto fica de
fora: exigiria alguém lembrar de pagar todo mês, o que transformaria inadimplência de exceção em
rotina e nos daria o custo permanente de perseguir pagamento.

**Sem teste gratuito.** O psicólogo paga antes de usar.

**Consequências:**
- ✅ **Some o problema da conta abandonada com prontuário dentro.** Sem trial, não existe base de
  gente que testou, guardou dado clínico e sumiu — e com ela some toda a regra de retenção e
  descarte que essas contas exigiriam. É a maior simplificação desta rodada.
- ⚠️ **Barreira de entrada alta.** O público é psicólogo autônomo, que costuma desconfiar de
  software e não tem hábito de assinar o que não experimentou. Sem trial, a conversão depende
  inteiramente de confiança prévia — o que empurra o peso para demonstração, indicação e prova
  social. Ver P-62.
- O acesso é liberado no primeiro pagamento. **No cartão, isso significa `PAYMENT_CONFIRMED`, não
  `PAYMENT_RECEIVED`** (I-06), sob pena de o assinante ficar um mês bloqueado depois de pagar.
- `assinaturas` continua sem tocar dado clínico: sabe se a conta está ativa, não o que há dentro.

---

## ADR-037 — Exportação no cancelamento vai por link autenticado, nunca por anexo de e-mail

**Status:** ✅ Aceita — Rodada 20
**Contexto:** O usuário propôs que, ao cancelar, o sistema **envie por e-mail todos os prontuários
de todos os pacientes**. A intenção está correta e é a mesma da ADR-007 — entregar tudo de forma
ativa, sem o psicólogo precisar pedir. O **canal**, porém, não serve.

**Por que anexo de e-mail não pode ser o meio:**

| Problema | Consequência |
|---|---|
| E-mail não é canal seguro | Trafega entre servidores sem garantia de criptografia. Estaríamos **nós** transmitindo dado sensível de saúde (LGPD art. 11) por canal inadequado |
| Fica na caixa para sempre | O prontuário de dezenas de pacientes passa a residir no Gmail ou Outlook do psicólogo, fora de qualquer controle nosso ou dele |
| Endereço errado ou comprometido | Um e-mail digitado errado entrega prontuário de dezenas de pessoas a um estranho. Não há como recolher |
| Limite de anexo | Histórico completo de uma clínica ultrapassa com folga os 25 MB do Gmail. O envio falharia justamente para os clientes mais antigos — os que têm mais a perder |
| E-mail desatualizado | Quem cancela às vezes já trocou de e-mail, e ninguém descobre até ser tarde |

**Decisão:** O e-mail vai, mas **sem conteúdo clínico**. Ele carrega apenas o aviso e um **link de
download autenticado**, de validade curta, que exige o psicólogo entrar na conta dele. O pacote é
gerado automaticamente no ato do cancelamento (ADR-007) e fica disponível durante a carência.

**Consequências:**
- Preserva inteiramente a intenção do pedido: ele não precisa lembrar de exportar, o sistema
  entrega. Só que entrega com porta trancada.
- Se o e-mail vazar, vaza um link que sem a senha não abre nada.
- O aviso é **repetido** durante a carência, não enviado uma vez só.
- O download precisa ficar registrado na trilha de auditoria: quando foi baixado, e se não foi.

## ADR-038 — Ciclo de vida da conta: um mecanismo, dois gatilhos

**Status:** ✅ Aceita — Rodada 21
**Contexto:** Duas decisões desta rodada convergiram no mesmo mecanismo. Para **inadimplência**, o
usuário escolheu modo somente-leitura. Para **cancelamento**, propôs manter a conta em leitura
por um mês, com notificação intensa explicando os riscos legais de não baixar os prontuários.
São o mesmo comportamento, acionado por motivos diferentes.

**Decisão — uma máquina de estados só:**

| Estado | Como se chega | O que o psicólogo pode fazer |
|---|---|---|
| `ATIVA` | Pagamento confirmado | Tudo |
| `TOLERANCIA` | Pagamento falhou — **~7 dias** | Tudo. Serve só para absorver cartão recusado por bobagem |
| `SOMENTE_LEITURA` | Fim da tolerância, **ou cancelamento** — **30 dias** | Lê e baixa tudo. Não cria consulta, prontuário nem cobrança |
| `ARQUIVADA` | Fim dos 30 dias — **mais 60** | Só o pacote de exportação, por link autenticado (ADR-037) |
| `DESCARTADA` | Fim dos 90 dias totais | Nada. Apagado de verdade, backups incluídos |

**Por que 30 dias de leitura e não só o pacote:** em leitura ele navega, confere e baixa **o que
quiser, na ordem que quiser** — um pacote único obriga a aceitar tudo de uma vez e não deixa
conferir se veio completo. É melhor do que o que estava na ADR-007.

**Por que a carência total continua longa:** do outro lado dela, dado clínico é apagado **para
sempre**, e o psicólogo tem obrigação legal de guardá-lo por cinco anos (ADR-005). Quem cancela às
vezes está em crise — doença, esgotamento, mudança de carreira — e pode passar um mês sem abrir
e-mail. Errar para o lado curto aqui é irreversível; errar para o longo custa armazenamento de
texto e PDF, com o áudio já descartado (ADR-019).

**Notificação intensa, e por que ela se justifica:** aviso repetido durante os 90 dias, dizendo o
que acontece e **por quê** — que o CFP obriga a guarda por cinco anos e que, sem esses arquivos,
ele fica sem a própria defesa. Insistência assim normalmente seria abusiva; aqui é o contrário,
porque o silêncio é que causaria o dano.

**Consequências:**
- Um mecanismo, duas portas de entrada. Menos código e menos chance de os dois caminhos
  divergirem com o tempo.
- Inadimplente que regulariza volta para `ATIVA` sem perder nada — o dado nunca saiu do lugar.
- 🔴 **E se o e-mail não chegar?** Endereço trocado ou caixa cheia fazem o aviso falhar em
  silêncio, e o descarte acontece com o psicólogo sem saber. Ver P-64.
- O descarte precisa ser real e auditável, sob pena de a promessa ser falsa (ADR-007).

## ADR-039 — O sistema não se comunica com pacientes. Nunca.

**Status:** ✅ Aceita — Rodada 22
**Contexto:** Discutia-se como o sistema entregaria prontuário ou documento ao paciente ou ao
responsável legal, e como limitar isso ao "estritamente necessário". O usuário cortou a premissa:
**não é papel do sistema enviar nada a paciente ou responsável.** O psicólogo baixa o documento e
decide, por fora, se envia e como envia. A responsabilidade é inteiramente dele.

**Decisão:** O Hamilton **não tem superfície voltada ao paciente**. Sem portal do paciente, sem
login do paciente, sem envio automático, sem link compartilhável de prontuário ou documento. O
único destinatário de qualquer coisa que sai do sistema é **o próprio psicólogo**.

**Consequências — e são grandes:**
- ✅ **P-11, P-32 e P-33 desaparecem.** Direito de acesso do paciente, limite do acesso do
  responsável e sigilo do adolescente deixam de ser problema de arquitetura. Continuam sendo
  obrigações éticas **do psicólogo**, exercidas fora do sistema, onde sempre estiveram. As
  histórias R-11, R-12 e R-13 saem do escopo.
- ✅ **A superfície de ataque cai drasticamente.** Não existe rota autenticável por terceiro, nem
  link público, nem fluxo de compartilhamento — as três origens mais comuns de vazamento em
  sistema de saúde. O isolamento da ADR-001 passa a ter só uma porta para defender.
- ✅ Nenhum fluxo de consentimento de envio, nenhuma decisão automática sobre o que um pai pode
  ver. O sistema não toma decisão clínica no lugar de quem é responsável por ela.
- ⚠️ **Reforça a importância da ADR-038.** Se o sistema nunca envia, o modo somente-leitura de 30
  dias no cancelamento é a **única** via pela qual o conteúdo sai daqui. Ela não pode falhar.
- ⚠️ O psicólogo provavelmente enviará por WhatsApp ou e-mail, que não são canais seguros. Está
  fora do nosso alcance e da nossa responsabilidade — mas é oportunidade futura de ajudá-lo, por
  exemplo exportando em formato protegido por senha. Não entra no MVP.

**Princípio derivado:** *o Hamilton é ferramenta de trabalho do psicólogo, não canal de
relacionamento com o paciente.* Toda feature futura que proponha falar com o paciente — lembrete
de sessão por WhatsApp, confirmação de presença, portal de agendamento — colide com esta ADR e
precisa revogá-la explicitamente antes de existir.

## ADR-040 — Três pendências menores, resolvidas por recomendação

**Status:** ✅ Aceita — Rodada 23 (decididas por mim, sujeitas a objeção)

### P-29 — Comprovante de despesa entra no MVP

A Receita só aceita despesa dedutível **comprovada**. Sem anexo, a marca de dedutibilidade
(ADR-011) é uma promessa que o psicólogo não consegue cumprir quando for questionado — e ele
descobre isso justamente na fiscalização.

**Decisão:** anexo **opcional** por despesa, guardado em bytes no Postgres (ADR-019 — comprovante
é pequeno e tem valor de prova). Opcional porque despesa não dedutível não precisa de comprovante,
e obrigar geraria upload de qualquer coisa só para passar da tela.

### P-34 — Paciente sem CPF: avisar, nunca bloquear

Nascidos antes de 01/2018 podem não ter CPF (ADR-014). É uma janela estreita e real.

**Decisão:** o cadastro **aceita** paciente sem CPF, com aviso explicando que ele será necessário
para emitir recibo, e que é gratuito solicitar. Bloquear o cadastro puniria o psicólogo por um
dado que não é dele e que ele consegue depois. Degradar com honestidade (ADR-012).

### P-61 — Pagamento adiantado vira crédito do caso

Adiantamento, pacote pago à frente e dinheiro recebido antes da sessão são casos reais.

**Decisão:** o pagamento pode ser registrado **sem cobrança correspondente** e fica como
**crédito do caso**, que **quita automaticamente** as próximas cobranças conforme elas nascem.

**Por que crédito e não pagamento solto:** solto, o valor sumiria da conta de "quem me deve" e o
paciente apareceria devendo algo que já pagou. Como crédito, o saldo é visível dos dois lados —
quanto ele tem a favor e quanto ainda deve. Também é o que faz a modalidade `POR_SESSAO` (ADR-002)
funcionar com quem paga um pacote de dez sessões adiantado.

## ADR-041 — Um relato por prontuário (revisa a ADR-028)

**Status:** ✅ Aceita — Rodada 24. **Revisa a ADR-028.**
**Contexto:** A ADR-028 decidiu "um relato, um prontuário por participante" — a IA dividiria o
relato de casal. Isso trouxe o risco P-53: a fala de um cônjuge migrar para o prontuário do outro,
que tem direito de lê-lo. A tentativa de mitigar era instruir a IA e reforçar a revisão humana.

O usuário propôs a saída melhor: **um áudio para cada prontuário**.

**Decisão:** `Relato` passa a ser **1:1 com `Prontuario`**. Em sessão de casal, o psicólogo grava
um relato por participante.

**Por que isto é superior:**
- **Elimina o risco em vez de mitigá-lo.** A IA nunca tem material dos dois em mãos, então não
  existe o que vazar. É o princípio 5 do produto: restrição estrutural vence instrução. Confiar
  no modelo para julgar o que é sensível seria delegar juízo clínico a software.
- **Some a lógica de divisão**, a revisão lado a lado e toda a instrução de atribuição. Menos
  código, e menos código no lugar mais perigoso do sistema.
- O modelo fica simples: um relato, um prontuário, um paciente.

**Custo assumido:** o psicólogo dita duas vezes numa sessão de casal, e parte do conteúdo — o
processo do casal — se repete. É trabalho a mais, contra o objetivo do produto. Aceitável porque
casal é minoria da prática clínica típica, e porque o segundo relato tende a ser curto: ele acabou
de organizar o pensamento no primeiro.

**Consequências:**
- **P-53 morre.** Não é mais mitigado: deixa de existir.
- A história R-06 muda de "a IA divide" para "um relato por participante".
- Se um dia a repetição incomodar na prática, a alternativa registrada é ditar em blocos rotulados
  ("sobre a Maria… sobre o João…") — mas ela reintroduz o risco e não deve ser adotada sem motivo
  forte.

---

## ADR-042 — O áudio é apagado; a transcrição fica

**Status:** ✅ Aceita — Rodada 24
**Correção de redação (Rodada 25):** a versão original desta ADR descreveu só o caminho do áudio,
dando a impressão de que gravar seria a única entrada. **Não é.** Continuam valendo as duas portas
da ADR-006: **áudio ditado** e **texto escrito**. O texto **não passa por transcrição** — entra
direto na geração. A transcrição existe apenas no caminho do áudio.

**Decisão do usuário:** no caminho do áudio, o fluxo é **áudio gravado → texto transcrito → IA produz o prontuário nos
moldes do CFP**. O áudio é descartado; **a transcrição permanece**, ligada ao prontuário.

**O que isso resolve:** responde "o psicólogo escreveu isso, ou a máquina escreveu por ele?" — a
pergunta que aparece se o CRP questionar um registro. Com a transcrição guardada, existe prova de
que o conteúdo partiu dele, e não de invenção do modelo. Reforça diretamente a ADR-005, que trata
o prontuário como meio de defesa.

**O que isso custa, e precisa estar claro:** a transcrição é **conteúdo clínico bruto, não
revisado**. Pode conter erro de transcrição — nome de medicamento trocado é o caso clássico — e
pode conter o que o psicólogo deliberadamente **não** levou ao prontuário. Guardá-la é uma segunda
cópia de material sensível.

**Guardas que tornam isso aceitável:**
1. A transcrição é **insumo**, nunca documento. O registro oficial é o prontuário confirmado.
2. Vive sob a mesma proteção do prontuário: mesmo isolamento, mesma trilha de auditoria, mesma
   exportação e mesmo descarte (ADR-038).
3. O áudio é apagado **assim que a transcrição existe** — não espera a confirmação do prontuário,
   porque a transcrição já permite refazer a geração.

---

## ADR-043 — Aviso de descarte por WhatsApp, e o relógio que congela

**Status:** ✅ Aceita — Rodada 24
**Decisão do usuário:** o aviso do descarte pode e deve ser feito **intensamente por WhatsApp**.

**Por que aqui faz sentido, tendo sido recusado na ADR-018:** lá o WhatsApp foi descartado para
lembretes do dia a dia, por custo por mensagem e volume alto. Aqui o volume é **mínimo** — só
contas canceladas ou inadimplentes — e o que está em jogo é dado clínico apagado para sempre. O
custo por conversa some diante disso.

**Vantagem que não é óbvia:** o WhatsApp devolve **confirmação de entrega e de leitura**. É
justamente a prova que o item seguinte exige, e que o e-mail não dá com confiabilidade.

**Decisão complementar — o relógio do descarte só corre com prova de aviso:** se não houver
entrega confirmada em nenhum canal, nem acesso do psicólogo à conta no período, o prazo
**congela** em vez de correr, e a conta fica pendente de revisão manual. Apagar em silêncio o que
alguém precisava e não sabia que ia perder é o pior desfecho possível; guardar demais custa
armazenamento.

**Consequências:**
- Reintroduz dependência de **Meta Cloud API** e de provedor, com template aprovado previamente.
  Volume baixo, mas é integração a construir.
- O perfil do psicólogo passa a precisar de **telefone**, hoje não previsto.
- Canais em camadas: **in-app** (ele ainda entra em modo leitura), **e-mail** (com link
  autenticado, ADR-037) e **WhatsApp**. Nenhum sozinho é suficiente.
- ⚠️ O WhatsApp **nunca** carrega conteúdo clínico — vale a mesma regra da ADR-037. Só aviso e
  instrução de entrar na conta.
- Fecha P-64.

## ADR-044 — Perfil do psicólogo e o CRP como porta de entrada

**Status:** ✅ Aceita — Rodada 25

### Campos do perfil

| Campo | Obrigatório | Observação |
|---|---|---|
| Nome completo | ✅ | Vai impresso em todo documento emitido (Res. CFP 06/2019) |
| CPF | ✅ | Exigido na escrituração do Receita Saúde (ADR-008) |
| **CRP** | ✅ **Obrigatório para se cadastrar** | Ver abaixo |
| Telefone | ✅ | Necessário para o aviso de descarte por WhatsApp (ADR-043) |
| E-mail | ✅ | Login e avisos |
| Regime: PF ou PJ | ✅ | Muda o lembrete fiscal (ADR-030) |
| CNPJ | ✅ **se PJ** | |

### Sem CRP, não há cadastro

**Decisão:** o CRP é condição de entrada. Quem não tem registro ativo não pode criar conta.

**Por que isso é coerente com o produto:** o CRP aparece impresso em **todo** documento que o
sistema gera — declaração, relatório, prontuário. Um cadastro sem CRP produziria documento
inválido desde o primeiro dia. E o produto inteiro é construído em torno de obrigações que só
existem para quem tem registro: guarda de cinco anos, estrutura do Art. 2º, Receita Saúde.

### Fato levantado — a validação é possível

O CFP mantém o **Cadastro Nacional de Profissionais da Psicologia** em `cadastro.cfp.org.br`,
com consulta pública em tempo real por **CRP, nome ou CPF**, devolvendo a situação do registro:
**Ativo**, **Cancelado** ou **Transferido**. A consulta atende tanto pessoa física quanto
**pessoa jurídica** — clínicas têm registro próprio no CRP.

⚠️ **O CFP não publica API oficial.** Existem intermediários comerciais (Infosimples e outros)
que oferecem consulta automatizada, com custo por chamada.

**Consequências:**
- O campo de CRP guarda **região e número** separados (o formato usual é `NN/NNNNN`, com a região
  de 01 a 24), não uma string livre — senão relatório e busca não funcionam depois.
- Validação de **formato** é obrigatória e gratuita. Validação de **existência** depende de
  terceiro pago (ver P-65).
- Risco de não validar é menor do que parece: quem se cadastrasse com CRP inventado teria acesso
  apenas à **própria** conta vazia (ADR-001). O motivo real de validar é integridade do produto,
  não contenção de vazamento.
- Psicólogo que atua como PJ tem, além do próprio registro, o **registro da empresa no CRP**.

**Adendo — Rodada 26 (validação do CRP e registro da empresa):**

| Decisão | Estado |
|---|---|
| **CRP é campo obrigatório** no cadastro, com validação de **formato** | ✅ MVP |
| **Verificação no cadastro do CFP** (se o registro existe e está ativo) | ⏸️ **Adiada, deliberadamente reversível** — o usuário pode retomar |
| **CRP da empresa (PJ)** | 🟡 Campo **opcional**, não exigido |

**Consequência de projeto — deixar o caminho aberto sem construí-lo:** como a verificação pode
voltar, o modelo já nasce com o lugar para guardar **situação do registro** (não verificado /
ativo / cancelado / transferido) e **data da última verificação**, ambos vazios por ora. Campo
vazio custa nada; adicioná-lo depois, com base em produção, custa migration. Não construir a
integração — só não fechar a porta.

**Sobre o CRP da empresa:** não está claro se o registro no CRP é exigido de um psicólogo autônomo
que abriu ME apenas por razão tributária, ou apenas de quem presta serviço como clínica. É questão
para contador ou para o próprio CRP, não para pesquisa. Campo opcional resolve os dois cenários
sem apostar em nenhum.
  Ver P-66.

## ADR-045 — A aplicação roda sob papel sem `BYPASSRLS`

**Status:** ✅ Aceita — Rodada 27 (**achado de execução**, não de planejamento)

**Contexto:** O passo 0 foi escrito e executado contra um Postgres real no Neon. Dos 11 testes
iniciais, **os 5 de RLS falharam**. A policy estava criada, `FORCE ROW LEVEL SECURITY` estava
ligado, e mesmo assim a consulta devolvia os pacientes dos dois psicólogos.

**A causa:** o papel dono do banco no Neon (`hamilton_owner`) tem o atributo **`BYPASSRLS`**.

```
PAPEL:  ('hamilton_owner', rolsuper=False, rolbypassrls=True)
TABELA: ('pacientes_paciente', rowsecurity=True, forcerowsecurity=True)
POLICY: isolamento_por_psicologo  ← existia e estava correta
```

`BYPASSRLS` é atributo **de papel** e passa por cima de tudo — inclusive do
`FORCE ROW LEVEL SECURITY`, que só resolve o bypass do **dono da tabela**, um problema
diferente. Eu havia tratado o segundo e não sabia do primeiro.

⚠️ **Por que este é o pior tipo de falha:** nada dava erro. Sem os testes, a aplicação teria ido
para produção com a terceira camada da ADR-001 puramente decorativa — policy escrita, migração
aplicada, documentação dizendo que o dado estava protegido, e o vazamento acontecendo em silêncio.

**Decisão:** as migrações continuam rodando como dono (DDL exige), mas **cada requisição desce
para `hamilton_app`**, papel `NOLOGIN NOBYPASSRLS` criado por migração, com apenas SELECT,
INSERT, UPDATE e DELETE.

A troca usa `SET LOCAL ROLE`, e não `SET ROLE`, pela mesma razão do `set_config(is_local => true)`:
o Postgres devolve o papel original ao fim da transação, sem depender de alguém lembrar de
resetar. No middleware, a ordem é **descer de papel antes de definir o escopo** — o contrário
deixaria uma janela rodando como dono do banco.

**Verificado, não presumido** (13 testes passando):
- `hamilton_app` tem `rolbypassrls = false` e `rolsuper = false`.
- Sem variável de sessão, a consulta devolve **zero** linhas — nega por omissão.
- SQL cru e `.raw()` do ORM respeitam a fronteira.
- `INSERT` para outro psicólogo é barrado pelo `WITH CHECK`.
- A variável de sessão e o papel **morrem no fim da transação** — I-01 resolvido e medido.

**Descoberta secundária, registrada para ninguém "consertar" errado:** o teste de I-01 precisa
ser `TransactionTestCase`. O `TestCase` do Django envolve cada teste numa transação externa, e ali
`transaction.atomic()` vira apenas um *savepoint* — `SET LOCAL` se prende à transação **externa**,
não ao savepoint, e o valor parece vazar. Não é o que acontece em produção, onde cada requisição
é uma transação de verdade.

**Endurecimento pendente para produção:** o ideal é a aplicação **conectar** com um papel de login
sem `BYPASSRLS`, em vez de conectar como dono e descer de papel. `SET LOCAL ROLE` protege o
caminho da requisição; não protege comando de management nem shell, que continuam rodando como
dono. A camada 2 (o `TenantManager`) cobre esses casos no ORM, mas não SQL cru. Ver P-67.

**Consequências:**
- I-01 sai da lista de impeditivos: resolvido e com teste que prova.
- Toda tabela nova precisa da migração de RLS. O `ALTER DEFAULT PRIVILEGES` da migração
  `core.0001` cuida dos privilégios automaticamente; a **policy** continua sendo por tabela.
- O ambiente de desenvolvimento passa a exigir PostgreSQL de verdade. SQLite pularia justamente
  os testes que importam.

## ADR-046 — Três papéis de banco: o RLS passa a valer fora da requisição

**Contexto:** a ADR-045 rebaixava a requisição autenticada para `hamilton_app` e considerava o
isolamento fechado. Uma bateria de testes adversariais (`core/tests/test_seguranca.py`, 21 testes
escritos para *atravessar* a fronteira) mostrou que faltavam quatro coisas, e que as quatro tinham
a mesma raiz: **a aplicação continuava conectada como dono do banco.**

1. **A requisição anônima nunca descia de papel.** O middleware devolvia cedo quando não havia
   usuário. Login, cadastro, healthcheck e — no futuro — o webhook do Asaas rodavam como dono,
   com `BYPASSRLS`. Um `SELECT` cru numa view pública devolveu a tabela de pacientes inteira.
2. **`SET LOCAL ROLE` é reversível.** A conexão seguia *autenticada* como dono; um `RESET ROLE`
   emendado numa injeção de SQL devolvia tudo. Rebaixar o papel corrente não adianta enquanto o
   papel de origem for privilegiado.
3. **`contas_psicologo` não tinha policy.** Ela não tem coluna de dono — ela *é* o dono —, então
   ficou de fora da migração de RLS. Sob o escopo de um psicólogo, um `SELECT` devolvia e-mail,
   CPF, telefone e **hash de senha** de todos os assinantes. A tabela mais sensível do sistema era
   a única sem a terceira camada.
4. **`django_session` guarda o `session_key` em claro.** Lê-la é se passar por qualquer psicólogo
   logado. Policy não resolve: a tabela não tem dono.

**Decisão:** separar **papel de conexão** de **papel de requisição**.

| Papel | Usado quando | Alcança |
|---|---|---|
| `hamilton_owner` | só migração (DDL exige) | tudo |
| `hamilton_web` | **conexão da aplicação** e requisição anônima | login e sessão. Nada de clínico |
| `hamilton_app` | `SET LOCAL ROLE` na requisição autenticada | domínio, filtrado pelo RLS |

`hamilton_web` é **`NOINHERIT`**: ele pode *virar* `hamilton_app`, mas não *é* `hamilton_app`. É
o que transforma a fuga de proibida em impossível — `RESET ROLE` agora cai num papel sem grant
nenhum nas tabelas clínicas, e o erro é `permission denied`, não uma lista de pacientes alheios.

`contas_psicologo` ganhou policy endereçada a papel: `hamilton_app` enxerga a própria linha,
`hamilton_web` enxerga a tabela toda. A exceção é o preço do login — autenticar é, por definição,
procurar um usuário que ainda não se sabe qual é —, e é o motivo de `hamilton_web` não ter
permissão em mais nada. `django_session` foi **revogada** de `hamilton_app` pelo mesmo raciocínio.

**Duas armadilhas descobertas ao implementar, registradas para não voltarem:**
- **Papéis são globais ao cluster, não ao banco.** Um `CREATE ROLE ... IF NOT EXISTS` pula a
  criação quando o papel sobrou de outro banco, e a migração reporta sucesso com os atributos
  errados. Declarar com `ALTER ROLE` é mais barato que confiar no histórico.
- **Desde o PG16 a concessão de membro carrega a própria opção de herança**, fixada quando foi
  criada. Uma concessão emitida enquanto o papel ainda era `INHERIT` continua herdando depois do
  `ALTER ROLE ... NOINHERIT`. Só refazer a concessão resolve. Foi assim que o primeiro
  `NOINHERIT` passou em falso.

**`manage.py check --deploy` vira gate obrigatório** (`core/checks.py`): ele reprova o arranque se
a `DATABASE_URL` apontar para um papel com `BYPASSRLS`. O erro que a ADR-046 previne não está no
código, está no ambiente — nenhum teste de repositório pega uma variável errada no Render. O check
**avisa** quando não consegue verificar, em vez de aprovar em silêncio: uma primeira versão
devolvia "nenhum problema" com o banco fora do ar, e foi exatamente assim que ela passou em falso.

**Consequências:**
- P-67 sai do backlog: resolvido.
- O deploy tem dois segredos de banco, não um: aplicação e migração.
- `SET LOCAL ROLE` vira redundância defensiva em vez de única linha de defesa.
- 38 testes verdes, 3 pulados de propósito (dependem de P-69).

---

## ADR-047 — A camada Python é cinto de segurança, não blindagem

**Contexto:** a ADR-001 promete três camadas. A do meio — `TenantManager` — tinha buracos que os
testes adversariais abriram: `bulk_create`, `.update()` e `QuerySet.delete()` não passam por
`Model.save()`, e a camada 1 some sem aviso nesses caminhos.

A pergunta não é como tapar cada um. É **o que a camada promete**.

**Decisão:** ela é cinto de segurança do desenvolvedor — existe para o erro aparecer no teste, com
stack trace. Quem protege de verdade é o RLS. Perseguir cada saída do ORM é uma corrida que o
Django sempre ganha, e a cada versão nova haveria um método a mais para cobrir.

O que **não** é aceitável é a camada prometer mais do que entrega. Três correções:

- **`sem_escopo()` foi removido.** Era `return self` sobre um queryset já filtrado: não escapava
  de nada. Pior, a mensagem de `EscopoNaoDefinido` mandava usá-lo — quem seguisse a instrução
  continuaria tomando exceção e concluiria que a fundação estava quebrada. O caminho deliberado é
  `objetos_todos`, que já existia, tem nome próprio e é visível na revisão de código.
- **A checagem do `save()` parou de se desligar sozinha.** O `elif` antigo terminava em
  `and contexto.atual() is not None`, o que pulava a comparação justamente **fora de requisição** —
  comando de management, tarefa agendada, shell —, que é onde não há middleware para corrigir o
  engano. Gravar registro de outro psicólogo passava em silêncio. Agora usa `contexto.exigir()`.
- **`core/db.py` recusa rodar fora de transação.** `SET LOCAL` e `set_config(is_local => true)` não
  existem em autocommit: o efeito morre no ponto e vírgula. A docstring de `limpar_escopo` prometia
  ser "o que impede o vazamento no dia em que alguém rodar código fora de transação" — era
  exatamente o cenário em que ela não fazia nada. Levantar `ForaDeTransacao` é honesto; devolver
  `None` era uma rede de segurança pintada na parede.

**Consequência:** `bulk_create` sem escopo falha com `IntegrityError`, e há teste garantindo que a
falha continue barulhenta. Se `psicologo_id` um dia virar nulável, esse caminho passa a gravar
paciente órfão em silêncio — o teste é o que avisa.

---

## ADR-048 — Exclusão de paciente: o sistema guarda, o psicólogo decide

**Status:** ✅ Aceita — Rodada 28
**Contexto:** Apagar um paciente levava junto, pelo `CASCADE`, tudo o que pende dele — e quando
existirem prontuários, eles iriam embora no mesmo clique, apesar da guarda mínima de 5 anos
(Res. CFP 001/2009, Art. 4º). A pergunta foi o que o sistema deve fazer nesse caso.

**Decisão do usuário:**
- **Cadastro feito por engano** — paciente **sem atendimento** — é apagado de verdade.
- **Paciente com atendimento** (alta, desistência, em curso) permanece no histórico, com os
  prontuários, **por tempo indeterminado**. Baixar ou excluir é ação **manual** do psicólogo;
  o sistema nunca faz isso sozinho. É o psicólogo quem responde por ter ou não o prontuário —
  mesma linha da ADR-039: o sistema não toma decisão clínica ou legal no lugar dele.

**Proteção contra o clique errado** (proposta aceita na mesma rodada): excluir um paciente com
atendimento **manda para a lixeira**; a exclusão definitiva é um segundo passo, de dentro dela, com
o aviso de que prontuário apagado não se recupera. É o mesmo mecanismo já decidido para documentos
(adendo à ADR-015). Paciente sem atendimento continua sendo apagado direto — ali não há nada a perder.

**Implementado agora** (`pacientes.servicos.excluir_paciente`):
- A exclusão leva junto o **caso individual** do paciente. Sem isso, o `PROTECT` do pagador
  impediria excluir qualquer paciente, já que todo paciente paga o próprio caso (ADR-009).
- **Recusa** excluir quem participa de atendimento de casal ou família: apagá-lo ali mudaria em
  silêncio o vínculo de outra pessoa.

**Ainda não implementado:** a lixeira. O critério dela é "tem atendimento", e atendimento não existe
no código. Pela própria regra, todo paciente de hoje é um cadastro sem atendimento — então a
exclusão direta atual está correta, e a lixeira entra junto com o app `atendimentos`.

**Consequências:**
- **Fecha P-12** (5 anos do CFP × 20 anos da Lei nº 13.787/2018): o sistema não impõe prazo
  nenhum, logo não precisa escolher entre os dois. Quem cumpre o prazo é o psicólogo.
- **Resolve em parte P-70**: a exclusão do **paciente** deixa de ser `CASCADE` silencioso. O
  `CASCADE` a partir do **psicólogo** continua, e fecha com o descarte explícito do app
  `assinaturas` (ADR-038).

---

## ADR-049 — Desfecho do atendimento no contexto individual

**Status:** ✅ Aceita — Rodada 28
**Contexto:** No `hamilton-api` os desfechos são alta, desistência, "paciente não responde" e
"solicitação de reencaminhamento" — este último pensado para trocar de terapeuta **dentro** da
clínica, o que aqui não existe. A Res. CFP 001/2009, Art. 2º, IV pede registro de "encaminhamento
ou encerramento".

**Decisão:** ao registrar o desfecho, o psicólogo **escolhe um de quatro tipos**:

| Tipo | Quando |
|---|---|
| Alta | Encerramento por conclusão do processo |
| Desistência | O paciente interrompe — inclui o antigo "não responde", com o motivo por escrito |
| Encaminhamento | Para outro profissional, **fora do sistema** (ADR-039) |
| Interrupção pelo psicólogo | O encerramento parte do profissional |

- Campo de **motivo** em texto livre, junto do tipo.
- O **momento** não é perguntado: o sistema conta quantas sessões houve (ADR-027).
- Registrar o desfecho **encerra o caso**: para de gerar consultas futuras e cobranças.
- Num casal ou família, o desfecho é **do caso inteiro**.

**Consequências:**
- Fecha P-05. Implementação no app `atendimentos`, que ainda não existe.
- Paciente com desfecho é "paciente com atendimento" para a ADR-048: fica no histórico e só vai
  para a lixeira por ação do psicólogo.

---

## ADR-050 — Trocar a forma de cobrança vale no dia 1º do mês seguinte

**Status:** ✅ Aceita — Rodada 28
**Contexto:** A ADR-002 deixou em aberto o efeito de trocar a modalidade no meio do mês (P-09). A
decisão foi tomada sobre dois exemplos concretos:

| Troca no dia 15 | Se valesse na hora |
|---|---|
| Por sessão → mensalidade | Setembro não tem mensalidade gerada: as sessões da segunda quinzena ficariam **sem cobrança**. O psicólogo atende de graça. |
| Mensalidade → por sessão | A mensalidade de setembro já foi gerada: as sessões restantes seriam cobradas **de novo**. O paciente paga em dobro. |

**Decisão:** a troca passa a valer **sempre no dia 1º do mês seguinte**, e a tela mostra as datas
concretas **antes** de gravar: *"a cobrança atual continua até 30/09, e a nova começa em 01/10"*.

**Regras que decorrem disso** (`pacientes.servicos.trocar_condicao`):
- **A condição anterior nunca é alterada.** O que já foi cobrado por ela pode ter pagamento.
- **Quem nunca teve valor combinado começa hoje** — não há condição anterior com que conflitar.
- **Trocar duas vezes no mesmo mês substitui a troca agendada**: ela ainda não valeu, então
  nenhuma cobrança depende dela.
- Ajuste fora do padrão — desconto proporcional num mês específico — é feito na **cobrança**
  individual, como exceção, e não na regra.

**Consequências:**
- Fecha P-09.
- Só foi possível sem migração porque as condições de cobrança já nasceram com **data de
  vigência** (`CondicaoCobranca.vigente_desde`), escolhida enquanto esta pergunta ainda estava aberta
  justamente para que qualquer resposta coubesse no mesmo modelo.

## ADR-051 — Agenda própria primeiro; Google Agenda depois

**Status:** ✅ Aceita — Rodada 30

**Fatos levantados antes da decisão:**
- Ler e escrever eventos do Google Agenda são **escopos sensíveis** de OAuth. Pedir só leitura não
  evita a regra: ler eventos também é sensível.
- Sem verificação, quem conecta vê a tela de "app não verificado", e o aplicativo fica limitado a
  **100 usuários — teto vitalício, que não reinicia**.
- A verificação é **revisão manual, de 4 a 6 semanas**, e exige um projeto no Google Cloud com
  credenciais criadas pelo dono do produto.

**Decisão:** construir primeiro a **agenda própria** — frequência, remarcação, colisão e estados da
consulta. A integração com o Google vem depois.

**Por que nessa ordem:** é a agenda própria que dispara prontuário pendente e cobrança (ADR-023); ela
funciona sozinha. O Google é espelho — pela ADR-020 ele só recebe cópia, e a consulta mora no
Hamilton. Construí-lo agora daria uma integração que só funcionaria para 100 pessoas até a
verificação sair.

**Consequências:**
- ADR-020 e as histórias A-12 a A-16 ficam para depois da agenda própria. Nada nelas é revogado.
- O **alarme matinal** da ADR-018 dependia do "Resumo diário" do Google. Até a integração existir,
  lembrete de atendimento é **só in-app**.
- A **colisão de horário** (ADR-024) confere só as consultas do próprio Hamilton; compromissos do
  Google entram na checagem quando a leitura da agenda existir.
- ⚠️ A verificação do Google pode ser **pedida em paralelo**, para o prazo de 4 a 6 semanas correr
  enquanto a agenda própria é construída. Decisão do usuário (ver P-72).

---

## ADR-052 — Consulta passada sem registro nunca é marcada sozinha

**Status:** ✅ Aceita — Rodada 30 (recomendação aceita pelo usuário)
**Contexto:** a consulta nasce `AGENDADA`. O que dispara prontuário pendente e cobrança é o
psicólogo marcá-la como `REALIZADA` ou `FALTA` (ADR-023). Se ele esquecer, a sessão continua
agendada para sempre: sem prontuário pendente, sem cobrança, e a receita do mês sai errada.

**Decisão:** o sistema **nunca** muda o estado de uma consulta passada por conta própria. Consulta
cuja hora já passou e segue `AGENDADA` aparece como **pendência no painel** — "3 consultas passadas
sem registro" —, com acesso direto a cada uma.

**Por que não marcar automaticamente:**
- Marcar como `REALIZADA` geraria cobrança de sessão que pode não ter acontecido.
- Marcar como `FALTA` geraria cobrança de falta que pode não ser devida.

Os dois erros vão parar no dinheiro do paciente, e só o psicólogo sabe o que aconteceu. É o mesmo
princípio da ADR-048: o sistema lembra, o psicólogo decide.

**Consequências:**
- Nenhum agendador é necessário: a pendência é uma consulta ao banco feita quando o painel abre,
  coerente com a ADR-018.
- "Sessões previstas" e "sessões realizadas" (ADR-027) só divergem de verdade quando há consulta
  sem registro — o painel deve deixar essa diferença visível, e não escondê-la no total.

---

## ADR-053 — Frequência de atendimento: semanal, quinzenal ou avulso (revisa a ADR-031)

**Status:** ✅ Aceita — Rodada 30. **Revisa a ADR-031.**
**Contexto:** a ADR-031 previa recorrência semanal, quinzenal e mensal. Ao discutir o que
"mensal" significaria, o usuário corrigiu a premissa: **não existe sessão mensal** na prática
clínica que o produto atende.

**Decisão do usuário:** cada paciente tem **um** tipo de atendimento, entre três:

| Frequência | O que significa | O que o sistema faz |
|---|---|---|
| **Semanal** | Toda semana, mesmo dia e horário | Prevê as consultas da janela à frente |
| **Quinzenal** | **Semana sim, semana não** | Prevê em semanas alternadas, a partir da primeira sessão da série |
| **Avulso** | Sem sessão prevista | **Não prevê nada.** O psicólogo registra cada consulta quando ela acontece |

- A frequência aparece **nas informações do paciente** e é **editável** se mudar.
- Por baixo, fica no **caso** (ADR-026): o atendimento de casal tem sua própria frequência, e a
  palavra "caso" continua sem aparecer no atendimento individual.

**Consequências:**
- **Mensal sai; avulso entra.** A âncora da ADR-031 continua valendo para a quinzenal: é a data da
  primeira sessão que define quais semanas são "sim".
- **Trocar a frequência** segue a ADR-022: vale para "esta e as próximas". Consultas futuras ainda
  `AGENDADA` são refeitas pela regra nova; passadas e já registradas não são tocadas.
- **Paciente avulso não ocupa a grade** (ADR-029) nem entra na previsão de sessões do mês — não há
  o que prever. Aparece em "sessões realizadas" quando a consulta é registrada.
- Consulta avulsa também existe para paciente semanal ou quinzenal: uma sessão extra, fora da
  regra, sem alterá-la.

---

## ADR-054 — Consulta de casal não registra presença por participante (revisa a ADR-026)

**Status:** ✅ Aceita — Rodada 32. **Revisa a ADR-026** no ponto "a presença é registrada por participante".
**Contexto:** a ADR-026 previa que, num casal, um participante pudesse faltar e o outro não, com a
presença marcada pessoa a pessoa. Ao chegar a hora de construir, a pergunta foi se isso vale o
trabalho de marcar quem veio a cada sessão.

**Decisão do usuário:** não vale. A consulta de casal ou família é registrada **uma vez**, e
`REALIZADA` significa que o atendimento aconteceu — considera-se que os participantes vieram. Se
alguém não veio, **o psicólogo relata isso no prontuário**, que já é individual por participante
(ADR-041). Se ninguém veio, é `FALTA`.

**Consequências:**
- T-03 sai do escopo. Nenhum campo novo na consulta.
- A cobrança já era uma por consulta, do caso (ADR-026) — nada muda nela.
- O prontuário continua **um por participante** (CFP Art. 5º, III). A ausência de um deles vira
  informação clínica escrita, e não um dado estruturado que a análise conte.

---

## ADR-055 — O que o desfecho faz na agenda, e como o atendimento é retomado (complementa a ADR-049)

**Status:** ✅ Aceita — Rodada 32 (recomendação aceita pelo usuário)

**Ao registrar o desfecho:**
- A frequência **termina no dia do registro**. Consultas futuras ainda `AGENDADA` são removidas —
  inclusive as remarcadas e as avulsas: o atendimento acabou, não sobra sessão para proteger.
- **Tudo o que já passou fica**, inclusive consulta passada sem registro, que continua pendência
  (ADR-052). O desfecho não registra nada no lugar do psicólogo.
- O atendimento encerrado **não aceita** frequência nem consulta nova até ser retomado.
- O paciente **sai da lista de ativos** quando nenhum atendimento dele está em curso. Não é
  apagado (ADR-048): fica em "Encerrados". Quem terminou o individual e segue no casal continua ativo.

**O registro guarda** o tipo (os quatro da ADR-049), a data, o motivo e **quem tomou a
iniciativa** — paciente ou psicólogo. Na desistência a iniciativa é sempre do paciente, e na
interrupção sempre do psicólogo; só alta e encaminhamento perguntam. O **momento** continua
calculado: sessões realizadas no período (ADR-027).

**Retomar:** o paciente que volta retoma **o mesmo atendimento**. O desfecho anterior fica no
histórico com a data da retomada, e o psicólogo define a frequência nova em seguida. As sessões
contadas no próximo desfecho são as posteriores à retomada.

**Consequências:**
- Um atendimento pode ter vários desfechos ao longo dos anos, mas **só um em aberto** —
  garantido por restrição no banco.
- Desfecho é atendimento para a ADR-048: paciente com desfecho não é apagado direto. A lixeira
  continua pendente.
- Quando o financeiro existir, atendimento encerrado não gera cobrança nova (ADR-049).

---

## ADR-056 — Grade de horários: avisa, nunca bloqueia (complementa a ADR-029)

**Status:** ✅ Aceita — Rodada 32 (recomendação aceita pelo usuário)

**Decisão:** marcar consulta ou definir frequência **fora da grade declarada** grava normalmente e
mostra um **aviso**. O único bloqueio da agenda continua sendo a colisão (ADR-024).

**Regras que decorrem disso:**
- **Sem grade declarada, não há aviso.** Quem não quis declarar não pode ser lembrado a cada
  consulta de algo que escolheu não usar (ADR-012).
- Blocos **encostados** ("8h–12h" e "12h–14h") valem como um só; blocos **sobrepostos** no mesmo
  dia são recusados, porque contariam a mesma hora duas vezes na ocupação.
- **Ocupação** conta a frequência em vigor de cada atendimento: semanal ocupa a faixa inteira;
  quinzenal, **metade** — a outra semana está livre. Avulso não ocupa (ADR-053).
- O mapa mostra também as sessões fixas **fora da grade**, para o encaixe não sumir da vista.

## Impeditivos

| # | Impeditivo | Situação |
|---|---|---|
| I-01 | RLS + connection pooling do Neon: a variável de sessão do tenant precisa ser setada por request e **limpa** ao devolver a conexão ao pool, sob risco de uma request herdar o tenant da anterior. Exige prova de conceito antes de virar fundação. | ✅ **Resolvido e testado** (ADR-045): `set_config(is_local)` morre com a transação. |
| I-04 | **O disco do Render é efêmero.** O `MEDIA_ROOT` é apagado a cada deploy — fato documentado no `hamilton-api`, que por isso guarda o PDF assinado em bytes no Postgres. Afeta **tudo** que planejamos armazenar: áudio dos relatos, PDFs de prontuário, comprovantes de despesa, contratos. Exige decisão de armazenamento (bytes no Postgres vs. object storage) **antes** da primeira linha de código. | ✅ Resolvido por ADR-019 (armazenamento misto). |
| I-05 | **Lembrete por canal externo exige agendador, e agendador custa.** O Render não tem instância gratuita para cron job (mín. ~US$ 1/mês) nem para background worker (~US$ 7/mês). Lembrete só in-app dispensa agendador por completo. | ✅ Eliminado do MVP por ADR-018 (só in-app e Google Agenda). |
| I-07 | **`BYPASSRLS` no papel dono do Neon** torna a policy decorativa, sem erro nenhum. Resolvido pela ADR-045; fica registrado porque é armadilha silenciosa que pode voltar se alguém trocar o papel de conexão. | ✅ Resolvido, com teste que falha se voltar |
| I-06 | **Cartão de crédito no Asaas só emite `PAYMENT_RECEIVED` 32 dias após `PAYMENT_CONFIRMED`.** Liberar acesso apenas em `RECEIVED` deixaria todo assinante de cartão bloqueado por um mês depois de pagar. O acesso tem de ser liberado em `CONFIRMED`. | 🔴 Armadilha conhecida |
| I-03 | **Receita Saúde não tem API pública.** A escrituração entra por importação manual de CSV no e-CAC, feita pelo psicólogo. Dependência externa fora do nosso controle: se a Receita mudar o layout, a feature quebra sem aviso. | 🟡 Mitigável (validar layout a cada ano-calendário) |
| I-02 | `gh` CLI não autenticado na máquina. | ✅ **Resolvido**: `gh auth status` confirma login como `PauloHenriqueL`, e o remote `origin` aponta para `github.com/PauloHenriqueL/clinico-individual`. |
