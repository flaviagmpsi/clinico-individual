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
- Decidir com clientes reais, não por dedução: os psicólogos da Allos são o público exato e
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

## Impeditivos

| # | Impeditivo | Situação |
|---|---|---|
| I-01 | RLS + connection pooling do Neon: a variável de sessão do tenant precisa ser setada por request e **limpa** ao devolver a conexão ao pool, sob risco de uma request herdar o tenant da anterior. Exige prova de conceito antes de virar fundação. | 🔴 A validar |
| I-04 | **O disco do Render é efêmero.** O `MEDIA_ROOT` é apagado a cada deploy — fato documentado no `hamilton-api`, que por isso guarda o PDF assinado em bytes no Postgres. Afeta **tudo** que planejamos armazenar: áudio dos relatos, PDFs de prontuário, comprovantes de despesa, contratos. Exige decisão de armazenamento (bytes no Postgres vs. object storage) **antes** da primeira linha de código. | ✅ Resolvido por ADR-019 (armazenamento misto). |
| I-05 | **Lembrete por canal externo exige agendador, e agendador custa.** O Render não tem instância gratuita para cron job (mín. ~US$ 1/mês) nem para background worker (~US$ 7/mês). Lembrete só in-app dispensa agendador por completo. | ✅ Eliminado do MVP por ADR-018 (só in-app e Google Agenda). |
| I-03 | **Receita Saúde não tem API pública.** A escrituração entra por importação manual de CSV no e-CAC, feita pelo psicólogo. Dependência externa fora do nosso controle: se a Receita mudar o layout, a feature quebra sem aviso. | 🟡 Mitigável (validar layout a cada ano-calendário) |
| I-02 | `gh` CLI não autenticado na máquina (`gh auth status`). Git funciona via Credential Manager; só ferramentas que dependem do `gh` ficam indisponíveis. | 🟡 Contornado |
