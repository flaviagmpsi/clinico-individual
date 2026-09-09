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

## Impeditivos

| # | Impeditivo | Situação |
|---|---|---|
| I-01 | RLS + connection pooling do Neon: a variável de sessão do tenant precisa ser setada por request e **limpa** ao devolver a conexão ao pool, sob risco de uma request herdar o tenant da anterior. Exige prova de conceito antes de virar fundação. | 🔴 A validar |
| I-03 | **Receita Saúde não tem API pública.** A escrituração entra por importação manual de CSV no e-CAC, feita pelo psicólogo. Dependência externa fora do nosso controle: se a Receita mudar o layout, a feature quebra sem aviso. | 🟡 Mitigável (validar layout a cada ano-calendário) |
| I-02 | `gh` CLI não autenticado na máquina (`gh auth status`). Git funciona via Credential Manager; só ferramentas que dependem do `gh` ficam indisponíveis. | 🟡 Contornado |
