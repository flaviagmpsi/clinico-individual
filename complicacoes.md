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

> ⚠️ **Substituída pela ADR-083:** a despesa é texto livre, sem catálogo. O tipo volta como campo opcional se a saída fiscal entrar.

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

> ⚠️ **Revogada em parte pela ADR-094:** passou a existir teste grátis de 7 dias, sem dado de pagamento. Os meios
> aceitos (cartão e PIX Automático, sem boleto) continuam valendo.

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

> ⚠️ **Revogada em parte pela ADR-081:** existe uma tela pública que **recebe** o cadastro do paciente por link de
> uso único. Nada sai do sistema para ele — o resto desta ADR continua valendo inteiro.

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

---

## ADR-057 — Trilha de auditoria: o que registra, e o que nunca guarda (F-05)

**Status:** ✅ Aceita — Rodada 33. Escopo e ordem por decisão do usuário; conteúdo da trilha é decisão de arquitetura.
**Contexto:** a ADR-005 exige trilha de "quem escreveu, quando, o que mudou", porque o prontuário é
meio de prova em processo disciplinar. Ela precisa existir **antes** do primeiro prontuário.

**Decisão do usuário:**
- **O que é auditado:** prontuário e dados do paciente (cadastro e responsável legal). Agenda,
  cobrança e perfil **não** — registrar tudo polui o histórico e dilui o que serve de prova.
- **Ações:** visualizar, criar, alterar, excluir e exportar.
- A **lixeira** de paciente (ADR-048) vem junto com o prontuário, que é o que ela protege.
- A verificação do Google (P-72) fica **adiada**.

**Decisões de arquitetura:**
- **A trilha guarda quais campos mudaram, nunca os valores.** Uma trilha que ninguém apaga,
  guardando CPF, medicamento ou observação, faria o paciente excluído por engano sobreviver nela —
  e a ADR-048 manda apagar de verdade. Pelo mesmo motivo não guarda nome: só tipo e número do
  registro. A prova do **conteúdo** do prontuário é a versão congelada na confirmação (R-05).
- **Só acrescenta.** O papel da requisição (`hamilton_app`) não tem `UPDATE` nem `DELETE` na tabela;
  o model recusa regravar ou apagar. Nem uma injeção de SQL apaga o rastro.
- **Cada registro sabe de quem é o dado** (o *titular*: o paciente). É o que permite ver o histórico
  de um paciente inteiro, inclusive de um responsável legal já removido.
- **Uma visualização é uma linha**, a cada abertura da ficha ou do formulário de edição. Sem agrupar:
  "abriu três vezes em dez minutos" também é informação.
- O psicólogo é o único usuário da conta, então "quem" é o dono do registro. Se um dia houver
  secretária ou supervisão, a trilha ganha o autor — hoje seria um campo sempre igual ao dono.

**Consequências:**
- Apagar a **conta** do psicólogo leva a trilha junto, pelo papel dono, no descarte da ADR-038 —
  nunca pela requisição.
- Todo model clínico novo herda `core.auditoria.Auditado` e diz quem é o titular.
- Exportar entra na trilha quando a exportação existir (R-08).

---

## ADR-058 — Construir do mais simples ao mais complexo; IA por último

**Status:** ✅ Aceita — Rodada 34 (decisão do usuário)
**Contexto:** o passo 3 previa o prontuário já com IA. Ao avaliar o protótipo `prontuario-exyo`
(P-18), ficou claro que a IA traz decisões grandes — provedor, LGPD, formato de entrada, conjunto
de teste — que não precisam travar o resto do produto.

**Decisão do usuário:** o Hamilton Individual é construído **do mais simples para o mais
complexo**. A IA de prontuário — e, pelo mesmo raciocínio, a IA de documentos — entra **no fim**,
depois de todo o sistema feito e testado. Ela é um facilitador para o psicólogo, não a base.

**Consequências:**
- O **prontuário escrito à mão** continua no escopo: registrar a evolução é obrigação do CFP
  (Res. 001/2009), com IA ou sem ela. Rascunho, confirmação, versão congelada e trilha valem para os dois.
- R-01, R-03, R-09, R-10, R-14 (IA e transcrição) e D-06, D-07 (documentos gerados) ficam para a
  etapa final. P-18 e P-19 ficam **adiadas**, com a avaliação do Exyo registrada em P-18.
- O modelo do prontuário é desenhado para receber a IA depois sem migração: ela passa a
  **preencher o rascunho** que hoje o psicólogo preenche.
- Esta ADR **não revisa** as ADRs 006, 041 e 042: elas continuam valendo como plano da etapa de IA
  e serão revisitadas quando ela chegar.

---

## ADR-059 — Vencimento da mensalidade é um dia do mês (revisa a ADR-002 no vencimento)

**Status:** ✅ Aceita — Rodada 35 (feedback de teste do usuário)
**Contexto:** o vencimento era "início do mês" ou "fim do mês". Isso não dá ao lembrete de cobrança
(ADR-017) uma data para avisar.

**Decisão do usuário:** o vencimento é **o dia em que vence** — de 1 a 31.
- Vale para a **mensalidade**, com um dia padrão no perfil do psicólogo e ajuste por paciente.
- Em mês mais curto, dia 31 (ou 30, 29) vira o **último dia do mês**.
- ~~Cobrança **por sessão** vence **no dia da sessão**~~ — revisado pela ADR-062 e **restabelecido pela ADR-063**:
  cada sessão cobrada gera o seu pagamento pendente, que vence no dia da sessão.

**Consequências:** dados existentes migram "início" → dia 1 e "fim" → dia 31. O lembrete de cobrança
e o status "precisa de atenção" (ADR-061) passam a ter uma data concreta de vencido.

---

## ADR-060 — A consulta só existe quando o psicólogo a cadastra (revisa ADR-022, 023 e 025)

**Status:** ✅ Aceita — Rodada 35 (feedback de teste do usuário)
**Contexto:** a agenda gerava consultas `AGENDADA` oito semanas à frente, com remarcação e com
comparecimento e cobrança como eixos independentes. Testando, o usuário apontou que isso não é o
trabalho do psicólogo: **ele cadastra a consulta**, e é o cadastro que diz se foi realizada ou cobrada.

**Decisão do usuário:**
- **O sistema não cria consulta.** A frequência continua mostrando no calendário as sessões
  **previstas** da semana, mas previsão não é registro.
- **Cadastrar** é o que transforma a sessão em registro. Três situações, à escolha do psicólogo:

  | Situação | Cobrada |
  |---|---|
  | **Realizada** | Sempre — "se foi realizada, obviamente foi cobrada" |
  | **Falta cobrada** | Sim |
  | **Falta remarcada** | Não. A sessão nova é cadastrada **quando acontecer** |

- Sessão prevista cuja data passou **sem cadastro** fica **pendente** (mantém a ADR-052: o sistema
  nunca cadastra sozinho).
- A consulta registra se é **da frequência** ou **avulsa**.

**Decisões de arquitetura:**
- Previsão é **calculada** da regra de frequência a cada tela, não gravada. Cadastrar a partir de uma
  previsão liga a consulta à ocorrência (regra + data prevista) — é o que tira a pendência. Cadastrar fora
  da frequência é avulsa.
- **Só se cadastra o que já aconteceu:** data e hora não podem estar no futuro.
- A colisão (ADR-024) passa a valer entre consultas cadastradas que ocupam horário (realizada e falta
  cobrada) e entre regras de frequência.

**O que sai:**
- A janela de 8 semanas, a tela de remarcar e a marca "remarcada à mão" (ADR-022).
- `contabilizada` como eixo independente (ADR-023): **cobrança deriva da situação**. Sessão de cortesia
  deixa de existir.
- "Cobro falta" do perfil (ADR-025): a escolha é feita em cada falta, então o padrão perde função.

**Consequências:** desfecho (ADR-055) só encerra a frequência — não há mais consulta futura para apagar.
Consultas `AGENDADA` e `CANCELADA` existentes são descartadas na migração (eram previsão); `FALTA`
vira falta cobrada ou falta remarcada conforme já entrava ou não na cobrança.

---

## ADR-061 — Painel: sessões, receita e situação de cada paciente no mês (detalha a ADR-027)

**Status:** ✅ Aceita — Rodada 35 (feedback de teste do usuário). Critérios por recomendação aceita.
**Contexto:** o painel provisório mostrava contagens de cadastro — sem utilidade no dia a dia.

**Decisão do usuário — o painel mostra:**
1. **Resumo do mês:** sessões feitas × sessões que faltam; receita recebida × a receber.
2. **Pacientes ativos:** situação (**regular** ou **precisa de atenção**), dias sem atividade e
   sessões no mês.
3. **Financeiro por paciente no mês:** "R$ pago / R$ devido", **pendente** embaixo quando não pagou, e
   a **forma de pagamento** (Pix, cartão, dinheiro).

**Definições:**
- **Precisa de atenção** quando houver qualquer um: pagamento vencido e não pago; sessão pendente de
  cadastro; mais de **14 dias sem sessão** (semanal) ou **21 dias** (quinzenal). Avulso não entra no
  critério de dias. Fora isso, regular.
- **Sessões que faltam:** as previstas pela frequência de hoje até o fim do mês.
- **A receber:** mensalidades do mês ainda não pagas + sessões cobradas por sessão no mês ainda não
  pagas, incluindo as previstas pela frequência. É previsão, e a tela diz isso.
- **Todo pagamento é registrado pelo psicólogo** (mantém a ADR-035).

**Consequências:** o painel depende de **registro de pagamento**, que não existe. A ordem passa a ser:
ajustes de consulta e vencimento → financeiro básico (cobrança e pagamento com forma) → painel novo →
prontuário escrito à mão.

**Definições fechadas na Rodada 39 (recomendações aceitas):**
- **Recebido no mês** são os pagamentos **referentes ao mês** — a mensalidade do mês e as sessões do mês —, ainda
  que pagos em outro mês. É o mesmo critério do "R$ pago / R$ devido" de cada paciente, e os dois números batem.
- **Dias sem atividade** contam desde a **última sessão realizada**. Falta não é atividade. Sem nenhuma sessão
  realizada, a tela diz "sem sessão ainda"; para o critério de atenção, conta-se desde o início da frequência.
- **Quem paga por sessão** aparece numa linha só, com as sessões do mês somadas; o detalhe por sessão fica no
  financeiro.
- **Sessões que faltam** e o **previsto** de quem paga por sessão contam só sessões **futuras**. A pendente de
  cadastro já tem o seu próprio aviso e não entra na previsão.

**Decisão de arquitetura:** o painel sai de `core` e vai para o app **`indicadores`** — o único que pode depender
de todos (regra 2 de dependência). `core` volta a não importar domínio (regra 1). A tela mostra uma linha por
**atendimento em curso**: o casal tem a sua, porque a cobrança é do caso (ADR-026).

---

## ADR-062 — Financeiro básico: pagamento por paciente e mês, e dia combinado para cada um (revisa ADR-059 e N-12)

**Status:** ⚠️ **Revisada em parte pela ADR-063 (Rodada 37)** — quem paga por sessão paga sessão a sessão, e o dia combinado é da mensalidade.

**Decisões do usuário:**
- **Pagamento é registrado pelo psicólogo por paciente e mês de referência** — "Marcos pagou R$ 400,
  referente a setembro, no Pix, dia 12". ~~Vale para mensalidade e para quem paga por sessão~~ — **revisado
  pela ADR-063**: por sessão, cada sessão gera o seu pagamento pendente.
- **Pagou a mais:** é só **mais um registro de pagamento**. Não há crédito automático abatendo o mês
  seguinte — **revisa N-12 / ADR-040**.
- **Pagou menos:** o restante fica **pendente** no mês.
- **Mensalidade é sempre cheia:** começar no meio do mês ou faltar não muda o valor. Desconto num mês
  específico é ajuste à mão.
- **Cada paciente tem o seu dia combinado de pagamento**, personalizado — inclusive quem paga por sessão. É
  a data em que a aba de lembretes alerta o psicólogo sobre pagamento pendente. **Revisa a ADR-059**, que
  supunha que a cobrança por sessão vencesse no dia da sessão.

**Consequências:**
- O campo "dia do vencimento" passa a valer para as duas modalidades, com o padrão do perfil.
- **Devido do mês:** mensalidade vigente no mês, ou soma das consultas cobradas no mês pelo valor por sessão
  vigente na data de cada uma. **Pago do mês:** soma dos pagamentos com aquele mês de referência.
- Pagamento **não dá baixa** em cobrança individual (ADR-035 simplificada): o saldo é comparação de totais
  do mês, que é o que o painel mostra.

---

## ADR-063 — Duas formas de cobrar: mensalidade com data no mês, ou sessão a sessão (revisa a ADR-062)

**Status:** ✅ Aceita — Rodada 37, detalhes fechados na Rodada 38 (P-74, P-75, P-76). Responde a P-73.

**Decisões do usuário:**

| Modalidade | Quando vence | O que fica pendente |
|---|---|---|
| **Mensalidade** | Numa data do mês, personalizada por paciente: **dia fixo** ("todo dia 10") **ou dia útil** ("todo 5º dia útil") | O valor do mês, até os pagamentos do mês cobrirem |
| **Por sessão** | **A cada sessão**: cada sessão gera um pagamento pendente, referente **àquela única sessão** | O valor daquela sessão, até ser pago |

- **Lembrete:** aparece na data de vencimento e continua até o pagamento cobrir o devido. **Pagamento
  registrado antes da data, o lembrete não aparece.**
- **Forma de pagamento** obrigatória: Pix, cartão, dinheiro ou transferência.
- Mantém da ADR-062: pagou menos, o restante fica pendente; pagou a mais, é só mais um registro; mensalidade
  sempre cheia.

**O que revisa:**
- ADR-062: o pagamento **por sessão** não é por mês de referência — é **por sessão**. O saldo, ali, é sessão a
  sessão, e não total do mês.
- ADR-059: volta a valer que a cobrança por sessão vence **no dia da sessão**. O dia combinado é da mensalidade.

**Consequências para o modelo:** o pagamento referencia **o mês** (mensalidade) **ou a consulta** (por sessão),
nunca os dois. O vencimento da mensalidade guarda o **tipo** (dia fixo ou dia útil) e o **número**.

**Detalhes fechados na Rodada 38 (decisões do usuário):**
- **Dia útil** é segunda a sexta, **sem feriado nacional** — incluindo a Sexta-feira Santa. Feriado estadual e
  municipal fica de fora. Carnaval e Corpus Christi não entram: são ponto facultativo, não feriado nacional.
- **Quem acerta várias sessões de uma vez é mensalidade.** No por sessão, cada pagamento é de uma sessão.
- **Falta cobrada gera pagamento pendente**, como a realizada. Falta remarcada, não.

**Decisões de arquitetura:**
- **O devido não é gravado, é calculado** — da condição de cobrança (mensalidade) e das consultas cobradas (por
  sessão). Gravado é só o pagamento. Corrigir uma consulta ou uma condição muda o devido sem deixar cobrança
  órfã.
- Consulta com pagamento **não é excluída nem vira falta remarcada** até o pagamento sair: seria dinheiro
  recebido por uma sessão que deixou de ser cobrada.
- **Feriados nacionais** calculados no código (`core.calendario`): os fixos da Lei nº 662/1949 e alterações,
  **20 de novembro a partir de 2024** (Lei nº 14.759/2023) e a Sexta-feira Santa, a partir da Páscoa.
- Mensalidade cheia é da **condição vigente no fim do mês** — assim a primeira condição, que pode começar no meio
  do mês (ADR-050), já gera a mensalidade daquele mês. Mês inteiro com o atendimento encerrado não gera.

---

## ADR-064 — Prontuário escrito à mão: texto livre, rascunho, versão confirmada e correção

**Status:** ✅ Aceita — Rodada 40. Formato por decisão do usuário; o resto, recomendações aceitas.

**Decisões do usuário:**
- **Um único campo de texto livre**, por enquanto. Os quatro campos do registro de evolução ficam para depois.
- **Toda sessão realizada gera um prontuário pendente**, até ser escrito e confirmado. Falta cobrada e falta
  remarcada não geram. Num casal, **um prontuário por participante** (ADR-041).
- **Rascunho livre até confirmar.** Confirmado, o texto **não se altera**: uma correção **cria nova versão**, com
  data e motivo, e a anterior continua guardada e visível.

**Decisões de arquitetura:**
- O texto mora em **versões**. A versão sem data de confirmação é o rascunho — no máximo uma por prontuário,
  garantido no banco. Confirmar é carimbar a data.
- **Versão confirmada é imutável em três camadas:** o model recusa regravar e apagar; um **gatilho no Postgres**
  recusa `UPDATE` de linha já confirmada, por qualquer caminho, inclusive SQL cru; e a exclusão é protegida.
  Prova que depende só de Python não é prova.
- **Pendente é calculado**, não gravado: sessão realizada cujo participante ainda não tem versão confirmada.
- Prontuário e versões entram na **trilha de auditoria** (ADR-057): quem abriu, escreveu e confirmou — nunca o texto.
- **Consulta com prontuário não vira falta nem é excluída** até o prontuário sair — mesmo raciocínio do pagamento
  (ADR-063).
- A **lixeira** de paciente (ADR-048) vem logo depois deste passo, e não junto, para manter o passo pequeno.

**Consequências:** a IA (ADR-058) passará a preencher o mesmo rascunho. Os quatro campos do CFP, se voltarem,
cabem como estrutura dentro do texto ou como campos da versão, sem mexer no ciclo rascunho → confirmação → correção.

---

## ADR-065 — Cinco situações da sessão, presença presumida e modalidade (revisa a ADR-060)

**Status:** ✅ Aceita — Rodada 41 (pedidos do teste do usuário).

**Decisões do usuário:**
- **A sessão prevista é dada como confirmada.** Nada a clicar antes: o psicólogo só mexe quando o paciente
  avisa. Continua valendo a ADR-060 — previsão é cálculo, e nenhuma sessão é gravada antes de acontecer.
- **Cinco situações** no cadastro, no lugar das três da ADR-060, e a cobrança decorre de cada uma:

  | Situação | Cobra? |
  |---|---|
  | **Presente** | Sim |
  | **Faltou sem avisar** | Sim |
  | **Cliente cancelou** | Sim, por padrão — **desmarcável na hora** |
  | **Profissional cancelou** | Não |
  | **Remarcada** | Não. A sessão nova é cadastrada quando acontecer |

- **Modalidade da sessão:** online ou presencial. O padrão fica **nas informações do paciente** e é editável
  em cada sessão, como a duração.
- **Agenda:** filtro por **período** (de uma data a outra) e por **situação**, e o **percentual de online ×
  presencial** das sessões do período.

**Decisões de arquitetura:**
- "Cliente cancelou" é a única situação com escolha de cobrança, então a consulta volta a ter um campo
  `cobrada` — preenchido pelo padrão da situação e alterável só nesse caso. Não é o eixo independente que a
  ADR-060 tirou: nas outras quatro situações o valor é consequência, não pergunta.
- **Cancelamento libera o horário** para a colisão (ADR-024); presente e falta sem aviso continuam ocupando —
  o horário foi guardado e perdido.
- Gráfico de presença e gráfico de resultado do ano vão para a tela de **análise**, nunca para o painel
  (ADR-027). O do ano depende de despesas (N-05), que ainda não existem.

**Migração dos dados:** "falta cobrada" vira **faltou sem avisar**; "falta remarcada" vira **remarcada**.

## ADR-066 — Máscara é da tela; o banco guarda número puro

**Status:** ✅ Aceita — Rodada 42 (segundo teste do usuário).

**Decisão:** CPF, CNPJ, telefone e CEP aparecem formatados enquanto o psicólogo digita, e o valor da cobrança
ganha o separador de milhar e a vírgula. O CEP preenchido busca o endereço sozinho.

**Decisões de arquitetura:**
- O banco continua guardando **só dígitos**, e o valor continua `Decimal`. A máscara é apresentação: quem
  formata é o navegador, quem limpa é `core.formularios.LimpaMascara`, antes da validação.
- A limpeza acontece no `__init__` do formulário, **não** em `clean_<campo>`: o `max_length=11` do CPF roda
  no `_clean_fields`, antes de qualquer `clean_` nosso, e recusaria a máscara como "longo demais".
- A busca de CEP usa o **ViaCEP, chamado pelo navegador** do psicólogo, e leva só o CEP — nenhum dado de
  paciente sai daqui. Se a busca falhar, o endereço continua digitável à mão; nada trava.
- O valor é digitado **em centavos**, como em aplicativo de banco: 20000 vira `200,00`.

## ADR-067 — O regime (PF ou PJ) e os dados da clínica moram no perfil

**Status:** ✅ Aceita — Rodada 42.

**Decisão:** o perfil guarda a identificação completa do psicólogo, o **regime** (pessoa física ou jurídica,
com CNPJ e razão social) e os **dados da clínica**: nome, telefone e endereço.

**Decisões de arquitetura:**
- O regime não é papelada: é o eixo que decide os recursos fiscais que o sistema vai oferecer — recibo de
  pessoa física e carnê-leão de um lado (ADR-008), documentos da empresa do outro (ADR-013). A tela diz isso.
- **PJ sem CNPJ é recusado**, e PF **com** CNPJ também: um cadastro que parece completo e produz documento
  errado lá na frente é pior que um erro na hora.
- UF e validadores de CEP e telefone saíram da duplicação entre `pacientes` e `contas` para `core.enderecos`.
- Isto entrega a maior parte da **C-11 ("Minha clínica")**. O quiz de cadastro (C-10) continua esperando a
  P-77: o que se pergunta na criação da conta é decisão de produto, não de arquitetura.

## ADR-068 — Remarcada diz para quando (revisa a ADR-065)

**Status:** ✅ Aceita — Rodada 42.

**Decisão:** ao marcar uma sessão como **remarcada**, o psicólogo informa a **nova data e horário**. A sessão
remarcada guarda esse destino; a data nova aparece na agenda como **sessão a cadastrar**.

**Decisões de arquitetura:**
- A sessão nova **não é gravada** quando a remarcação é registrada: continua valendo a ADR-060 — consulta só
  existe depois de acontecer. O que existe é uma sessão prevista extra, fora da frequência, que o psicólogo
  confirma no dia.
- O destino é opcional no dado (remarcação sem data combinada existe), mas a tela pergunta sempre.
- O horário de destino **não é reservado** contra colisão enquanto não for cadastrado, pela mesma razão que a
  sessão prevista da frequência não reserva (ADR-024): previsão não é registro.

## ADR-069 — O painel é a agenda de hoje, não uma lista de pacientes (revisa a ADR-061)

**Status:** ✅ Aceita — Rodada 42.

**Decisão do usuário:** "achei péssimo o jeito que está o atendimentos em curso". O painel passa a mostrar
**as sessões de hoje**, em ordem de horário, com as **pendências de cadastro dos dias anteriores logo acima**.

**Decisões de arquitetura:**
- Cada linha traz horário, paciente, modalidade, situação da sessão e os avisos que mudam o que o psicólogo
  faz agora: pagamento em aberto e prontuário por escrever.
- **"Dias sem sessão" sai da linha** e vira alerta: com a sessão sempre cadastrada, o número já está na
  agenda. Ele só reaparece quando o paciente passa do intervalo da própria frequência (semanal, 14 dias;
  quinzenal, 21) — o caso em que ninguém cadastrou nada e o atendimento pode estar morrendo em silêncio.
- A semana continua na Agenda, a um clique. O painel responde "o que eu faço agora"; a agenda, "como está a
  minha semana".

## ADR-070 — O valor desta sessão (revisa a ADR-063)

**Status:** ✅ Aceita — Rodada 43.

**Decisão do usuário:** a sessão extra de quem paga mensalidade **não** cobra por padrão, mas a tela oferece
cobrá-la à parte, com o valor digitado na hora. Vale também para quem atende de forma **infrequente**, marcando
sessão de tempos em tempos.

**Decisões de arquitetura:**
- A consulta ganha um `valor` **opcional**. Vazio é o caso normal: vale a condição de cobrança do paciente —
  mensalidade ou valor por sessão. Preenchido, ele manda, e a sessão vira uma cobrança própria.
- Isso resolve dois buracos com um campo só: a **sessão extra do mensalista** (antes não gerava nada) e a
  sessão de quem ainda **não tem valor combinado** (ADR-012, antes idem).
- Quem paga **por sessão** e marca de forma aleatória já estava resolvido: a consulta avulsa gera a cobrança
  pelo valor vigente. O campo só entra quando esta sessão foge do combinado.
- Sessão que não entra na cobrança não tem valor: o model recusa, e corrigir a situação para uma que não cobra
  apaga o valor junto — dinheiro sem sessão correspondente é o erro que a ADR-063 já evitava do outro lado.

## ADR-071 — Quiz de cadastro: a conta nasce completa (fecha a P-77)

> ⚠️ **Refeita pela ADR-094:** a conta nasce só com login e CRP, o quiz vem depois da escolha do plano, ganhou a
> pergunta "quem é você" e a abordagem passou a ser escrita à mão. O mecanismo daqui continua o mesmo.

**Status:** ✅ Aceita — Rodada 43.

**Decisão do usuário:** quiz **completo** na criação da conta, e as mesmas informações ficam no perfil do
psicólogo: nome completo, telefone, endereço da clínica, CPF e/ou CNPJ, se atende como PF ou PJ, **abordagem**,
**se atende online e/ou presencial**, e CRP.

**Decisões de arquitetura:**
- **Quatro passos.** O primeiro cria a conta e já loga: e-mail, senha, nome, CPF, telefone e CRP — não é
  escolha de produto, é o que `Psicologo` exige desde a ADR-044, e a validação roda em toda gravação (P-69).
  Os outros três são regime, abordagem e formas de atendimento, e clínica.
- **Cada passo grava o que coletou.** Quem larga no meio volta de onde parou, em vez de recomeçar — e o
  sistema já tem o que foi respondido até ali.
- `quiz_concluido_em` marca o fim. Enquanto estiver vazio, `CadastroCompletoMiddleware` leva qualquer tela de
  volta ao quiz: sem regime e sem forma de atendimento, metade do que o sistema propõe sai errado. Passam só o
  próprio quiz, o login e a saída — senão a conta recém-criada ficaria presa sem conseguir nem sair.
- **Endereço só é obrigatório para quem atende presencialmente.** Exigir consultório de quem só atende online
  seria inventar uma exigência que a profissão não faz.
- **Abordagem é lista com "outra"** e campo livre ao lado: é o campo do psicólogo, não uma taxonomia oficial,
  e nenhuma lista fechada daria conta.
- A assinatura (ADR-038) continua no passo 7: hoje a conta se cria e entra. Quando houver cobrança, ela entra
  **entre** o passo 1 e o painel, sem mexer no quiz.

## ADR-072 — O painel diz cada coisa uma vez (revisa a ADR-069)

**Status:** ✅ Aceita — Rodada 44 (terceiro teste do usuário).

**Decisões do usuário:**
- As pendências apareciam em **três lugares** — um card-resumo, um bloco de pagamentos, um bloco de prontuários,
  mais o aviso de sessões atrasadas. Passa a ser **um bloco só**, direto, com o necessário para agir.
- **"Dias sem sessão" sai por completo**, inclusive o alerta de ritmo que a ADR-069 tinha mantido. O recurso não
  é relevante: com a sessão sempre cadastrada, esse número já é a própria agenda.
- A agenda do painel mostra **só os atendimentos do dia**.

**Decisões de arquitetura:**
- O painel tem três blocos e nada mais: **Hoje** (a agenda do dia), **Pendências** (sessão de dia anterior sem
  cadastro, pagamento vencido, prontuário por escrever — cada item com o link que o resolve) e o **resumo do mês**.
- **Cada informação aparece uma vez.** A sessão de hoje que já passou sem cadastro fica no "Hoje" como "a
  cadastrar" e não se repete nas pendências; os avisos por linha que a ADR-069 pôs na agenda do dia saem, porque
  o bloco de pendências já os carrega.
- Sai o `LIMITE_DE_DIAS_SEM_SESSAO` e tudo o que derivava dele, inclusive "precisa de atenção" no resumo.

## ADR-073 — A agenda no desenho da planilha do psicólogo (revisa a ADR-065)

**Status:** ✅ Aceita — Rodada 44.

**Decisão do usuário:** a agenda deixa de ser lista e passa a ter **estética de agenda**, como a planilha que
ele usa hoje: colunas por dia da semana, cada uma uma pilha de cartões em ordem de horário — `NOME - 14H` —,
com os **horários livres visíveis** (`LIVRE - 8H`). Semana por padrão; dia e mês a um clique. Compromissos
pessoais (academia, supervisão) **não entram**. "Livre" só existe onde há horário cadastrado na aba de
Horários — e essa aba fica como está.

**Decisões de arquitetura:**
- **Livre é derivado**, nunca gravado: cada faixa de uma sessão (a duração padrão do psicólogo, de hora em hora)
  dentro da grade que não tenha consulta ocupando nem sessão esperada. Cancelada e remarcada não ocupam
  (ADR-024), então o horário delas volta a ser livre. Dia sem grade não tem livre nenhum.
- **Segunda a sexta**; sábado e domingo entram só quando têm grade, sessão ou espera. Coluna vazia é largura
  jogada fora.
- As cores são as da planilha — amarelo sessão, verde livre — e falta, cancelamento e remarcação ganham a
  própria cor para saltarem aos olhos.
- O **mês** mostra até quatro cartões por dia e "+N"; sem livres, que ali seriam ruído. O **dia** é uma coluna
  com tudo.
- `de`/`ate` e `semana` continuam valendo como período (ADR-065), e o filtro de situação vale para a visão
  aberta. Com filtro, nem previsão nem livre aparecem: a pergunta é "onde estão as faltas?".
- O cálculo mora em `atendimentos.servicos.calendario`; a view só escolhe o período e navega.

## ADR-074 — A tela só mostra o que a escolha pede (refina as ADRs 068, 070, 072 e 073)

**Status:** ✅ Aceita — Rodada 44 (terceiro teste do usuário, continuação).

**Decisões do usuário:**
- **Valor desta sessão** só aparece na sessão **avulsa** ou para quem **paga por sessão**. Quem paga mensalidade,
  cadastrando uma sessão da frequência, não vê o campo.
- **"Remarcada para"** só aparece depois de marcar *Remarcada*. Pelo mesmo raciocínio, **"Cobrar esta sessão"**
  só aparece depois de marcar *Cliente cancelou* — era a única situação em que ele tinha efeito.
- No calendário, a sessão **cadastrada muda de cor**: amarelo é só o que ainda vai acontecer. Presente é verde;
  falta, vermelho; cancelada e remarcada, cinza riscado. **Horário livre é cinza**.
- No painel, o bloco "Hoje" tem o **tamanho do dia**, e as **pendências cabem na tela**: a lista é inteira e
  rola por dentro do bloco.
- No **financeiro**, sai o alerta amarelo que repetia a tabela do mês: o "Pendente" já está na linha da
  cobrança. Só o que a tabela não alcança — cobrança vencida de **mês anterior** — aparece à parte.

**Decisões de arquitetura:**
- O valor some **na view**, que tira o campo do formulário quando a condição vigente é mensalidade; o serviço
  continua aceitando o valor por qualquer caminho (ADR-070). A avulsa mostra sempre: é justamente onde a extra
  do mensalista entra.
- Os blocos condicionais são JavaScript de conveniência. Sem ele, ficam visíveis — e o servidor já ignorava o
  que não se aplica à situação escolhida.

## ADR-075 — No prontuário, "Editar" — e a versão anterior continua guardada (revisa a ADR-064)

**Status:** ✅ Aceita — Rodada 45.

**Decisão do usuário:** sai a função de "corrigir e explicar o motivo". O prontuário salvo tem um botão **Editar**
e nada mais.

**Decisões de arquitetura:**
- A tela não fala em versão nem pede motivo. **Por baixo, nada mudou:** cada edição grava uma versão nova, a
  anterior fica congelada pelo model e pelo gatilho do banco, e o histórico aparece recolhido no fim da página.
- O campo `motivo` continua existindo, para as versões gravadas antes desta decisão.
- Por que não editar em cima: o Manual do CFP (2025) trata o registro como prova idônea em processo ético, manda
  evitar o que permita adulteração e pede que plataforma eletrônica assegure a **autenticidade do conteúdo**.
  Histórico apagado não volta; histórico invisível não incomoda ninguém.

## ADR-076 — Aba de documentos psicológicos: modelos em branco, no formato do CFP (revisa as ADRs 032 e 034)

**Status:** ✅ Aceita — Rodada 45. O usuário enviou o Manual Orientativo do CFP (1ª ed., 2025), lido na íntegra.

**Decisão do usuário:** uma aba com **modelos prontos** de documento psicológico, o mais fiéis possível às
orientações do conselho. Os campos chegam **em branco**, cada um com a explicação do que se espera ali, e cada
sub-aba explica **como o CFP espera o documento e por quê**. O documento preenchido **fica guardado** (rascunho →
emitido), e o sistema sugere só o que é administrativo: a identificação do paciente escolhido e a assinatura.

**O que entra:** as cinco modalidades da Res. CFP nº 06/2019 — **declaração, atestado, relatório psicológico,
laudo e parecer** — e três termos de apoio: **termo de entrega**, **autorização para atender criança ou
adolescente** (Res. CFP nº 13/2022, Anexo I) e **encaminhamento**. Ficam de fora o relatório multiprofissional
(pressupõe equipe), os termos de serviço-escola e de acolhimento institucional, e a ficha SINAN, que é formulário
do Ministério da Saúde.

**Por que isto revisa a ADR-034.** Ela adiou atestado, laudo e parecer porque a **IA** os geraria sem a avaliação
que os fundamenta. Modelo em branco não gera nada: quem escreve é o psicólogo, e a sub-aba diz o pré-requisito no
topo — atestado e laudo só depois de avaliação psicológica (Res. 31/2022); parecer exige titulação. A geração
por IA continua para o fim (ADR-058), e o Manual a baliza: apoio à redação, nunca ao conteúdo clínico.

**Decisões de arquitetura:**
- **Direito autoral (ADR-033).** A estrutura dos documentos vem da resolução, que é ato oficial e pode ser
  reproduzida. O Manual é obra protegida: é **fonte e link**, nunca cópia — as orientações e as ajudas de campo
  são escritas com palavras nossas. A aba mostra em que versão da norma os modelos se apoiam.
- **O catálogo é código** (`documentos.modelos`), não tabela: muda quando a norma muda, com teste e revisão.
- **Nada clínico chega ao documento pelo sistema.** A origem de uma sugestão é o paciente (nome, CPF,
  nascimento), o perfil ou a data de hoje — e um teste garante que nenhuma outra existe. É a ADR-034 aplicada ao
  modelo em branco: a declaração é proibida de conter sintoma, e a garantia é o dado nem estar à mão.
- **Rascunho → emitido.** Emitir exige os campos obrigatórios e **congela**: a cópia guardada é a que foi
  entregue (Res. 01/2009, Art. 2º, VI — a D-05). Model e gatilho de banco recusam alterar, como no prontuário.
  Corrigir é "Novo a partir deste". Paciente com documento emitido não é excluído; rascunho sai junto.
- **A forma é do sistema; o conteúdo é de quem assina.** Texto corrido ou itens conforme a modalidade; atestado
  fechado com traços (Art. 10, §5º); validade no último parágrafo de atestado, relatório e laudo (Art. 17);
  data por extenso; laudas numeradas na impressão; segunda assinatura no termo de entrega e na autorização.
- Impressão e PDF são do navegador. Assinatura eletrônica ICP-Brasil fica para depois.

## ADR-077 — O documento se preenche dentro dele (refina a ADR-076)

**Status:** ✅ Aceita — Rodada 45 (mesmo dia).

**Decisão do usuário:** a primeira versão da sub-aba — formulário para preencher, documento só depois de emitir —
"ficou muito ruim porque não dá pra ver o modelo final". O que fica como estava: as opções de documento no topo, o
card de explicação do CFP, o preenchimento automático e o seletor de paciente. O que muda: **o design final do
documento já está na tela, e preenche-se dentro dele.**

**Decisões de arquitetura:**
- A tela à direita é **a folha** — timbre, título, texto, local e data, assinatura —, e cada espaço dela é um
  campo do formulário, com a letra do próprio documento e um sublinhado tracejado no lugar da caixa. Espaço
  exigido e ainda vazio fica amarelo. Não existe mais formulário separado.
- **Gabarito.** Cada documento em texto corrido é descrito por um texto com `{campo}` onde o valor cai e `[[…]]` em
  volta do trecho opcional. A folha de preencher e a folha impressa saem **do mesmo gabarito**: o que se vê
  enquanto escreve é o que sai no papel, e não há segunda composição para divergir. Um teste garante que todo
  campo tem lugar no texto, e que nenhum lugar fica sem campo.
- Documento em itens (relatório, laudo, parecer) traz os títulos da resolução na folha, com o campo de texto
  embaixo de cada um e a explicação logo abaixo.
- **A explicação de cada campo continua** (ADR-076): aparece numa faixa fixa acima da folha quando o campo recebe
  o foco — sem poluir o documento — e embaixo dos campos de texto longo.
- A idade, no atestado, virou campo próprio e opcional: como aposto, entra com as duas vírgulas ou não entra. É o
  que o gabarito sabe fazer sem adivinhar pontuação.
- Descartada no caminho: uma prévia ao lado do formulário, atualizada pelo servidor. Resolvia "ver antes de
  emitir", mas não "preencher dentro" — e era uma tela a mais para o mesmo trabalho.

## ADR-078 — Salvar em PDF e em DOCX, da mesma composição da folha

**Contexto.** Rodada 46. O documento só saía pela impressão do navegador. O usuário pediu "a opção de salvar em
pdf e docs": PDF para entregar, DOCX para quem precisa ajustar no Word ou mandar a quem só aceita Word.

**Decisões de arquitetura:**
- **Um módulo, `core.exportacao`**, que recebe a folha já composta — título, blocos, local e data, assinaturas,
  timbre — e devolve bytes. Ele não conhece documento nem prontuário; quem compõe é o app de origem
  (`documentos.modelos.compor`, `prontuarios.servicos.folha_para_arquivo`). A tela, a impressão e os dois arquivos
  saem da mesma composição: não há segunda redação para divergir (ADR-077).
- **Bibliotecas em Python puro**: `reportlab` (PDF) e `python-docx` (DOCX). Descartado WeasyPrint, que reaproveitaria
  o HTML da folha mas exige GTK/Pango no sistema — instalação frágil no Windows de desenvolvimento e peso no
  Render. Descartado também converter DOCX em PDF via LibreOffice, pelo mesmo motivo.
- **A forma que o CFP pede vai para o arquivo**: laudas numeradas "1/N" no rodapé (no DOCX, campos `PAGE` e
  `NUMPAGES`, que o Word atualiza sozinho); traços fechando o espaço do atestado; traço de assinatura do tamanho de
  uma assinatura. No PDF, o último parágrafo — e o título do item, se for o único parágrafo dele — vai junto com a
  assinatura: **lauda só com assinatura** é o que permite trocar o conteúdo que veio antes.
- **Rascunho pode ser baixado, mas sai marcado**: marca d'água no PDF, cabeçalho no DOCX e `rascunho-` no nome do
  arquivo. Arquivo solto não pode se passar por documento emitido.
- **Exportar entra na trilha de auditoria** (`Acao.EXPORTAR`, ADR-057): é o momento em que o conteúdo deixa o
  sistema. Nada é guardado em disco — o arquivo é gerado na hora, e o disco do Render é efêmero (I-04).
- **"PDF" e "DOCX" na folha salvam antes de baixar**: o arquivo sai com o que está escrito agora. Em documento
  ainda não salvo os botões não aparecem — cada clique criaria outro rascunho.
- **Limite conhecido:** o DOCX é editável por natureza. A cópia que vale como registro documental continua sendo
  a emitida e congelada no sistema (ADR-076), não o arquivo.

## ADR-079 — O prontuário na forma da Res. CFP nº 001/2009, preenchido dentro da folha (fecha a P-80)

> ⚠️ **Refinada pela ADR-080:** a folha mora na aba **Documentos**, e a evolução é só leitura — vem dos registros de sessão.

**Contexto.** Rodada 46. O prontuário era um texto livre por sessão — só a *evolução*. A Res. CFP nº 001/2009,
Art. 2º, pede quatro partes, e o Manual de 2025 avisa que plataforma sem essa estrutura "necessita realizar
adequações" numa fiscalização (P-80). O usuário pediu, para a aba de prontuários, "a mesma coisa" da aba de
documentos: explicação das orientações, coisas pré-preenchidas e a visualização do documento.

**Decisões de arquitetura:**
- **Uma folha por paciente** (`/prontuarios/paciente/<pk>/`), no desenho das ADR-076 e ADR-077: à esquerda, o que
  o CFP espera do prontuário e por quê (`prontuarios/orientacoes.py`); à direita, a folha "PRONTUÁRIO PSICOLÓGICO"
  com as quatro partes, e cada espaço dela é um campo, com a explicação na faixa de ajuda.
  1. **Identificação** — vem do cadastro e não se edita na folha: uma verdade só, com link para a ficha.
  2. **Avaliação da demanda e objetivos do trabalho** — texto por paciente.
  3. **Evolução** — uma entrada datada por sessão **realizada**, da mais antiga para a mais recente. É o mesmo
     registro de sessão da ADR-064: a folha é outra porta para ele, não outro dado.
  4. **Encaminhamento ou encerramento** — texto por paciente, em branco enquanto o trabalho segue.
- **Pré-preenchido só com o que é administrativo** (ADR-034): a demanda chega com modalidade, frequência, duração
  e data de início; o encerramento, com o desfecho registrado (ADR-055), se houver. Motivo da busca, objetivos e
  tudo o que é clínico o sistema não supõe. A sugestão é marcada na tela como sugestão e **não vai para o
  arquivo** enquanto não for salva.
- **`FichaDoProntuario` só se acrescenta.** Demanda e encerramento ficam num model próprio, por paciente; cada
  mudança grava uma linha nova e a anterior fica guardada — vale a mais recente. O model recusa alterar e apagar,
  e um gatilho recusa `UPDATE` até para o dono do banco, como na versão confirmada (ADR-064). RLS em migração
  própria. Descartado: `OneToOne` editável, que perderia a redação anterior de um texto que é prova.
- **A folha não tem rascunho.** "Salvar prontuário" confirma cada evolução que mudou, como versão nova da sessão
  (ADR-075). Texto igual ao que vale não gera versão; texto apagado é ignorado — registro feito não se apaga. A
  tela de uma sessão só, com rascunho e histórico, continua existindo: é para onde levam as pendências do painel.
- **PDF e DOCX** pela ADR-078, com `Acao.EXPORTAR` na trilha. O arquivo leva só o que está **confirmado**; parte
  sem texto sai como "Sem registro até esta data", e não em branco — o Manual pede que não fiquem espaços vazios.
  É a cópia a que a pessoa atendida tem direito.
- **Paciente com ficha escrita não é apagado** (ADR-048): a avaliação da demanda pode nascer na entrevista inicial,
  antes de qualquer sessão realizada, e já é prontuário.
- **Direito autoral** (ADR-033): a resolução é ato oficial e é citada; o Manual do CFP é fonte e link — os textos
  de orientação são redação nossa.
- **O que a folha diz que ainda não temos:** o *registro documental* de uso exclusivo da psicóloga (hipóteses não
  compartilhadas, protocolos de teste — Art. 2º, V). A orientação avisa que ele deve ser guardado à parte. Virou
  a P-84.
- O estilo e o script da folha preenchível saíram de `documentos/modelo.html` para `templates/_folha_preenchivel_*`,
  usados pelas duas abas.

## ADR-080 — Registro de sessão em Prontuários; prontuário geral em Documentos (refina a ADR-079)

**Contexto.** Rodada 47. A ADR-079 pôs a folha do prontuário na aba Prontuários e deixava editar a evolução por ela.
O usuário testou e corrigiu: existem **dois prontuários** na cabeça do psicólogo — o do dia a dia, sessão a sessão,
e o **geral**, "que pode ser enviado pro paciente ou pra quem solicitar". Juntos na mesma aba, e com dois lugares
para escrever a mesma evolução, confundem sobre qual deles se está fazendo.

**Decisões de arquitetura:**
- **Aba Prontuários = registros de sessão**, e só. Ganhou um filtro por paciente; perdeu o cartão e o botão da
  folha. Um parágrafo diz o que ela é e aponta para o prontuário geral.
- **Aba Documentos = prontuário geral**, como primeiro cartão ("Prontuário do paciente") e como sub-aba ao lado das
  modalidades da Res. 06/2019, em `/documentos/prontuario/<paciente>/`. Aqui o paciente é obrigatório: sem ele, a
  tela mostra a orientação do CFP e o seletor.
- **A evolução é montada, não escrita.** O prontuário geral reúne **todos** os registros de sessão confirmados do
  paciente, do mais antigo para o mais recente, com a redação que vale. Nesta tela ela é **somente leitura**:
  sessão sem registro confirmado aparece como aviso, com link para escrever o registro na aba Prontuários, e não
  entra no arquivo. Uma verdade só, um lugar só para escrevê-la. Descartado manter a edição pelos dois lados, que
  era justamente a confusão.
- No prontuário geral **se escrevem** só a avaliação da demanda e o encerramento (`FichaDoProntuario`, que não
  muda: só-acréscimo, gatilho e RLS). `salvar_folha` deixou de receber evoluções.
- **Dependência entre apps:** as telas saíram de `prontuarios` e foram para `documentos`, que passa a **ler**
  `prontuarios` (serviços, orientações e o formulário da ficha). O contrário não existe — `prontuarios` não importa
  `documentos` —, então não há ciclo (regra 5). A proibição da ADR-034 continua valendo e é outra coisa: a **IA de
  declaração** não recebe conteúdo de prontuário.
- **Continua "vivo", sem emitir.** O prontuário geral é sempre o estado atual; cada PDF ou DOCX baixado entra na
  trilha como exportação (ADR-078). Se a entrega de uma cópia deve ficar registrada com data, finalidade e
  destinatário, como pede o inciso VI para documentos entregues, é a P-85.

## ADR-081 — Duas portas para o cadastro: o psicólogo escreve, ou o paciente preenche por um link

**Contexto.** Rodada 48. O usuário quer continuar cadastrando à mão e, além disso, **gerar um link** para o paciente
preencher os próprios dados; o que faltar, o psicólogo completa. Mandou a lista do que o link pode pedir: criança ou
adolescente, nome e nome social, raça/cor, CPF ou documento estrangeiro, nascimento, estado civil, telefone, e-mail,
responsável financeiro, até dois contatos de emergência, endereço com país, gênero, profissão e medicamento.

É a **primeira tela pública do produto que recebe dado de paciente** — e boa parte dele é dado sensível (LGPD,
Art. 5º, II: saúde, raça/cor, e o próprio fato de estar em psicoterapia). A arquitetura inteira foi desenhada para
o anônimo não alcançar tabela clínica (ADR-046); esta decisão não abre mão disso.

**Relação com a ADR-039 — esta ADR abre nela uma exceção, e só uma.** A ADR-039 diz que o Hamilton não tem
superfície voltada ao paciente, "sem link compartilhável", e que toda feature que fale com o paciente precisa
revogá-la antes de existir. O usuário, que é quem decide, pediu o link: a ADR-039 fica **revogada em parte**, no
menor pedaço possível.
- O que muda: existe **uma** tela que o paciente abre — e ela só **recebe**. É formulário em branco, de uso único.
- O que continua valendo, inteiro: **nada sai do sistema para o paciente.** Sem portal, sem login de paciente, sem
  envio automático (quem manda o link é o psicólogo, pelo canal dele), sem link de prontuário ou documento. A tela
  pública não mostra dado nenhum de paciente — nem o que ele mesmo acabou de enviar.
- As consequências boas da ADR-039 se mantêm por isso: P-11, P-32 e P-33 (acesso do paciente, do responsável e sigilo
  do adolescente) continuam fora da arquitetura, porque não há o que o paciente possa **ver**. O custo real é a
  superfície de ataque, que deixa de ter "uma porta só": as decisões de segurança abaixo existem para que a porta
  nova dê para uma sala vazia.

**Decisões de arquitetura:**
- **O convite é uma sala de espera.** `ConviteDeCadastro` guarda o que o paciente respondeu, em JSON. Nada vira
  `Paciente` até o psicólogo — autenticado, no escopo dele — **revisar e salvar**. Link vazado, repassado ou
  preenchido por engano não cria paciente, não lê paciente e não revela nada além do nome e do CRP de quem convidou.
  Descartado: criar o paciente direto da tela pública, que exigiria dar a `hamilton_web` permissão de escrita em
  tabela clínica.
- **A revisão é o próprio "Novo paciente"**, aberto com as respostas já preenchidas (`?convite=<id>`). O psicólogo
  confere e completa o que só ele sabe — cobrança, modalidade, primeira sessão. Ao salvar entram junto os contatos
  de emergência, o responsável legal (cadastro de criança ou adolescente) e o responsável financeiro (pagador de
  fora, ADR-009); o convite é marcado como cadastrado e **as respostas são apagadas dele** — o dado passa a existir
  num lugar só.
- **As duas portas chegam ao mesmo cadastro.** O formulário do psicólogo ganhou os mesmos dados: nome social,
  documento estrangeiro, estado civil, gênero, raça/cor, profissão, país e até dois contatos de emergência
  (`ContatoDeEmergencia`, com RLS). Gênero é texto com sugestões, e não lista fechada; raça/cor usa as categorias do
  IBGE mais "prefiro não informar".
- **Segurança do link:**
  - Token de 256 bits (`secrets.token_urlsafe(32)`); **no banco fica só o SHA-256**. O link aparece uma vez, na hora
    de gerar, com botões de copiar e de WhatsApp; perdeu, cancela e gera outro.
  - **Uso único e validade de 7 dias.** A condição vai no próprio `UPDATE`: dois envios simultâneos não passam os dois.
  - **No banco, o visitante enxerga uma linha.** `hamilton_web` ganhou `SELECT` e `UPDATE` **por coluna**
    (`respostas`, `respondido_em`) só nesta tabela, atrás de duas policies endereçadas a ele: a linha cujo hash foi
    apresentado na transação (`core.db.aplicar_convite`, mesma mecânica do escopo), e `UPDATE` só enquanto não houver
    resposta. Sem apresentar token, um `SELECT *` não devolve nada. Ele não troca dono, prazo nem hash, não cria nem
    apaga convite, e continua sem grant em `pacientes_paciente`.
  - A resposta sai com `Referrer-Policy: no-referrer` (o token está na URL, e a página carrega CDN e ViaCEP),
    `Cache-Control: no-store` e `noindex`. Link inexistente dá 404; vencido, 410; usado, uma página que não diz nada.
- **LGPD na tela pública:** pedir o mínimo. Obrigatórios são nome, nascimento, um telefone, um contato de
  emergência e o **endereço** (decisão do usuário, Rodada 49 — é o que vai no recibo e no contrato; para quem mora
  fora do Brasil, CEP, bairro e estado ficam livres); raça/cor, gênero e medicamento são sempre opcionais, e os dois primeiros ficam atrás de "Adicionar…".
  Antes do envio há um **aviso de privacidade** — quem recebe, para quê, sigilo, como pedir correção ou exclusão —
  e um aceite obrigatório, cuja data fica registrada na resposta. Em cadastro de criança ou adolescente quem preenche
  e aceita é o responsável (LGPD, Art. 14), e nome e telefone dele passam a ser obrigatórios; o telefone da criança
  deixa de ser.
- **Campo só aparece quando a escolha pede** (ADR-074): responsável legal, responsável financeiro, segundo contato,
  passaporte. O JavaScript só esconde; a regra está no formulário, no servidor — idade conferida pela data de
  nascimento nos dois sentidos.
- **Achado no caminho:** CPF repetido derrubava o "Novo paciente" com erro de servidor — a unicidade por psicólogo
  está no banco, mas `psicologo` não é campo do formulário e o Django não a validava. Virou erro no campo, com o
  nome de quem já tem o CPF. Com o link isso deixa de ser raro: paciente antigo preenche de novo.
- **Fora desta rodada, de propósito:** link para paciente **já cadastrado** atualizar os próprios dados (P-86);
  aviso ao psicólogo quando a resposta chega — hoje é um contador no botão "Link de cadastro" da lista de pacientes;
  limite de tentativas por IP, desnecessário com token de 256 bits e sem nada a enumerar.

## ADR-082 — Endereço é obrigatório no link; fora do Brasil, tudo se escreve à mão

**Contexto.** Rodada 49, duas correções do usuário sobre a ADR-081. Primeira: "o endereço é obrigatório sim" — a
tela pública o tratava como opcional. Segunda: "se por acaso a pessoa for de outro país, todos os outros campos de
preenchimento não podem ter opção de lista automática, a pessoa vai ter que escrever tudo à mão". O atendimento
online alcança brasileiro morando fora e estrangeiro; o cadastro, até aqui, só sabia o formato brasileiro — CEP de
oito números, telefone com DDD, estado escolhido numa lista de UF. Quem mora fora **não conseguia se cadastrar**.

**Decisões de arquitetura:**
- **Endereço obrigatório na tela do paciente**: país, rua, número e cidade, sempre; CEP, bairro e estado, para quem
  mora no Brasil. No cadastro feito pelo psicólogo continua opcional (ADR-012): ele nem sempre tem o endereço à mão,
  e é para isso que o link existe.
- **O formato é do país.** `core.enderecos.no_brasil(pais)` decide — país em branco conta como Brasil, que é o que
  todo cadastro antigo tem. A validação de telefone e CEP saiu do campo e foi para `Paciente.clean()`:
  - **no Brasil**, as regras de sempre: DDD + número (10 ou 11), CEP de oito números, UF da lista;
  - **fora**, nada brasileiro: código postal é texto de até 12 letras e números (o britânico tem letra e espaço),
    telefone vai de 6 a 15 números com o código do país (o teto do E.164), e o estado ou província é **texto
    livre** num campo próprio, `estado_exterior`. O `clean()` zera a UF de quem mora fora, e o estado de fora de
    quem mora aqui — os dois nunca convivem.
  - Responsável legal e contato de emergência aceitam telefone de qualquer país **sempre**: a mãe pode morar fora
    mesmo quando o paciente mora aqui.
- **Na tela, nada automático para quem é de fora.** Uma peça só (`components/_endereco_por_pais.html`), usada nas
  duas portas do cadastro: trocou o país, somem a máscara e a busca do CEP (o `base.html` agora pergunta na hora se a
  busca está ligada), a máscara de telefone e a lista de estados; aparece o campo livre de estado ou província, e o
  rótulo vira "Código postal". É conforto de tela — a regra está no servidor, e o `LimpaMascara` aprendeu a não
  arrancar as letras do código postal de fora (`campos_numericos()` passou a poder depender do que chegou).
- **País continua texto livre**, com "Brasil" de padrão. Lista de países seria mais uma lista automática, que é o
  que o usuário pediu para não ter.

## ADR-083 — Despesas da clínica em texto livre, e o fluxo de caixa do mês (substitui o catálogo da ADR-011)

**Contexto.** Rodada 50. As três perguntas de despesas que estavam abertas foram respondidas pelo usuário de uma vez:
"você mesmo digita qual é a despesa. ela pode ou não aparecer todo mês, vai ter a opção de colocar isso e a data de
vencimento dessa despesa e o valor dela. aí quando você pagar você marca como pago". E pediu o fluxo de caixa dentro
do financeiro, com sete números: receitas recebidas, a receber e total; despesas pagas, a pagar e total; resultado.

**Decisões de arquitetura:**
- **Sem catálogo.** A despesa é descrita por quem a tem. A ADR-011 propunha tipos com marca de dedutibilidade; a
  saída fiscal está fora do MVP, e classificar o que ninguém vai usar é atrito. Se o Carnê-Leão entrar, o tipo
  volta como campo **opcional** sobre a despesa que já existe — nada do que se grava hoje precisa mudar.
- **Despesa mensal é uma linha só; a ocorrência é cálculo.** `Despesa(descricao, valor, vencimento, mensal, fim)`.
  "Aluguel, todo dia 5" não vira doze registros: `financeiro.despesas.despesas_do_mes` calcula o que vence em cada
  mês, como a sessão prevista e a cobrança. Dia 31 em mês curto cai no último dia.
- **"Paguei" é a única coisa gravada por mês**: `BaixaDeDespesa(despesa, mes, pago_em, valor)`, uma por despesa por
  mês. O **valor fica na baixa** — reajustar o aluguel muda os meses em aberto, e não o que já saiu do caixa.
- Parar de pagar é **encerrar** ("este é o último mês"); excluir só serve a cadastro por engano, e é recusado se já
  houver mês pago — baixa é histórico financeiro, `PROTECT` como o pagamento.
- **Fluxo de caixa por competência**, como o resto do financeiro (ADR-062): a receita do mês é a das cobranças
  dele, recebida ou não; a despesa, a que vence nele. Mês fechado não muda quando o atrasado paga depois — só passa
  de "a receber" para "recebida". "A receber" inclui a **previsão** das sessões que a frequência ainda prevê
  (ADR-061), e a tela diz quanto é previsão. O resultado aparece duas vezes, com nomes diferentes: o **do mês**
  (tudo se cumprindo) e o **já realizado** (recebido menos pago).
- O financeiro virou três abas sobre o mesmo mês: **Receitas** (a tela que já existia), **Despesas** e **Fluxo de
  caixa**. Trocar de aba mantém o mês.
- Fora desta rodada: despesa em atraso **não** entrou no bloco de pendências do painel (ADR-072) — é decisão do
  usuário se conta do consultório é pendência clínica (P-88); comprovante anexo (N-06) segue adiado.

## ADR-084 — Estatísticas numa aba própria; frequência e situação financeira na ficha; aniversariantes no painel

**Contexto.** Rodada 50. O usuário pediu gráficos — resultado previsto do ano, horário mais usado, dia com mais
sessões, presença ("26 de 26 sessões realizadas"), quantos semanais, quinzenais e avulsos — e disse estar em dúvida:
"se as estatísticas vão dentro de uma aba de cada tema ou se eu crio uma aba à parte". Pediu também, na ficha do
paciente, sessões presentes, ausentes e canceladas, e o status "em dia"; e um quadro de aniversariantes no painel.

**Decisões de arquitetura:**
- **Aba à parte, "Estatísticas"** — recomendação nossa diante da dúvida, fácil de desfazer. Razões: (1) o painel
  responde "o que eu faço agora" e as abas de tema são de **trabalho**; estatística é de **leitura**, e misturar as
  duas põe gráfico onde se quer botão (ADR-027 já dizia: gráfico na tela de análise, nunca no painel); (2) o
  retrato da clínica cruza temas — presença é agenda, resultado é financeiro —, e só `indicadores` pode olhar
  todos (regra 2); (3) um lugar só para procurar. O que é de **um** paciente fica na ficha dele.
- **Resultado previsto do ano**: doze fluxos de caixa (ADR-083) num gráfico — barras empilhadas de receita
  (recebida + a receber) e de despesa (paga + a pagar), e a linha do resultado. Cor cheia é o que aconteceu; cor
  clara, o previsto. Os meses à frente saem das mensalidades, das sessões previstas e das despesas mensais.
- **A conta da presença**, a mesma na aba e na ficha: presentes ÷ (presentes + faltas sem aviso + canceladas pelo
  paciente). O que **o profissional** cancelou e o que foi **remarcado** ficam fora — não dizem nada sobre a
  frequência do paciente, e a remarcada vira outra sessão, que aí conta. A tela mostra os cinco números e explica a
  conta: percentual sem denominador à vista engana.
- **Composição por frequência** é a foto de **hoje** (quem está em atendimento agora), e a tela diz isso; o resto é
  do ano escolhido.
- **Só dado administrativo** (I-10), e **nenhum nome de paciente vai para o JavaScript**: os gráficos recebem
  números e rótulos; a tabela de presença por paciente é HTML do servidor. Chart.js vem de CDN; sem internet, os
  números continuam na tela.
- **Na ficha do paciente**: quadro de frequência (presentes, ausentes, canceladas, remarcadas e o percentual) e a
  **situação financeira** — "Em dia" quando nada vencido está em aberto, a lista do que venceu quando há pendência,
  "sem cobrança combinada" quando não há o que acompanhar. A ficha é do app `pacientes`, que não pode importar
  agenda nem financeiro (regra 5): os números chegam por **template tag de `indicadores`**.
- **Aniversariantes do mês** no painel, por último — é lembrança, não tarefa (ADR-072). Só pacientes em
  atendimento; quem faz hoje vem destacado.

## ADR-085 — Anamnese: sub-aba opcional na ficha do paciente

**Contexto.** Rodada 50. "Quero que dentro do perfil de cada paciente também tenha um formulário de anamnese a ser
preenchido pelo psicólogo, mas isso é opção [...] é um recurso do sistema pra caso o psicólogo queira fazer anamnese."

**Decisões de arquitetura:**
- **Opcional de verdade.** Sub-aba "Anamnese" na ficha; enquanto ninguém escreve, **nada é gravado** — salvar em
  branco não cria registro. Nenhum campo é obrigatório e nada no sistema cobra a anamnese: não é pendência.
- **Doze temas em texto livre**, cada um com uma linha de roteiro: queixa principal, história da queixa,
  tratamentos anteriores, saúde geral, sono/alimentação/substâncias, história familiar, desenvolvimento e infância,
  escolaridade e trabalho, relacionamentos e rede de apoio, rotina e lazer, expectativas, observações. Um formulário
  só para adulto e criança: o tema "desenvolvimento" diz o que cabe em cada caso. Descartada a lista de opções
  fechadas — anamnese é entrevista, e o sistema não decide o que importa nela.
- **Edita-se**, ao contrário do registro de sessão (ADR-064): é roteiro de trabalho que se completa ao longo das
  primeiras sessões. `Anamnese` (uma por paciente) é `Auditado` — a trilha guarda *que* temas mudaram, nunca o
  conteúdo —, tem RLS e **protege o paciente contra exclusão** (ADR-048).
- Mora no app `prontuarios`: é dado clínico, e depende de `pacientes`, nunca o contrário.
- **Não entra no prontuário geral** que se entrega ao paciente (ADR-080), e a tela avisa. É o primeiro pedaço do
  registro de uso do psicólogo de que fala a P-84.

## ADR-086 — O financeiro lê em lote: uma carga por tela, e não uma consulta por cobrança

**Contexto.** Rodada 50. O usuário pediu muito mais dado fictício, e a semente passou a gerar meses de história —
cerca de 150 sessões, 100 pagamentos, 100 registros. Com isso o painel levou **43 segundos** e a aba de estatísticas,
**98**: 222 e 552 consultas ao banco. Não era defeito da semente; era o que qualquer clínica encontraria depois de
alguns meses de uso. O devido é cálculo (ADR-062), e o cálculo era feito cobrança a cobrança — cada uma perguntava ao
banco pela condição vigente do caso e pelos pagamentos dela. A latência daqui até o Neon (~0,2 s por consulta) só
tornou visível cedo um problema que em produção apareceria com volume.

**Decisões de arquitetura:**
- **`financeiro.servicos.carregar(de, ate)`** lê de uma vez casos (com pacientes, condições, desfechos e
  frequências), consultas cobradas do período (com pagamentos) e pagamentos de mensalidade. `cobrancas_do_mes`,
  `pagamentos_pendentes`, o fluxo do mês e o do ano calculam sobre essa `Carga`; quem pede doze meses carrega uma vez.
  As despesas têm a carga delas (`carregar_despesas`).
- **Os atalhos do caso aproveitam o que já veio**: `condicao_vigente`, `regra_aberta` e `desfecho_aberto` respondem
  da memória quando a relação foi trazida com `prefetch_related`, e continuam consultando o banco quando não foi —
  nenhuma chamada existente mudou de comportamento.
- **A previsão por sessão** (ADR-061) virou uma função só, `previsto_por_mes`, usada pelo painel e pelo fluxo: uma
  chamada a `sessoes_previstas` para o período inteiro, com a condição de cobrança saindo da carga.
- **Resultado medido** na mesma base: painel de 222 para 44 consultas (43 s → 8 s); estatísticas de 552 para 26
  (98 s → 5 s); fluxo de caixa de 58 para 19. O que resta é latência de rede do ambiente de desenvolvimento.
- **Não virou cache nem tabela de totais.** Continua valendo a regra de que o devido é derivado: nada novo é
  gravado, não há o que invalidar. Se um dia o volume pedir, o próximo passo é agregar no banco — não guardar saldo.
- A semente fica como **teste de carga de bolso**: rodar `semear --limpar` e abrir o painel mostra, em segundos, se
  alguma tela voltou a consultar o banco item a item.

## ADR-087 — Estatísticas abrem no mês; o ano é uma opção no topo (refina a ADR-084)

**Contexto.** Rodada 51. O usuário: "não seria melhor aparecer de cara a estatística do mês e ter a opção de ver a
do ano em algum botão em cima?" — e, sobre o que mostrar, "quero a opção que mostra as informações reais da clínica".

**Decisões de arquitetura:**
- **O mês é o padrão.** É a pergunta do dia a dia; o ano é a pergunta de quem parou para planejar. Um seletor
  "Mês · Ano" no topo, com setas para andar no período escolhido.
- **O retrato dos atendimentos segue o período** (presença, horário, dia, presença por paciente). A composição por
  frequência não segue: é a foto de hoje, e a tela continua dizendo isso.
- **O gráfico de dinheiro é sempre do ano** — doze barras e uma linha não cabem num mês — e fica embaixo do retrato
  nos dois modos (mesma ordem sempre, correção do usuário na Rodada 52); no modo mês, o mês escolhido vem em cor
  cheia e os outros esmaecidos. Os três cartões de dinheiro (receitas,
  despesas, resultado) só aparecem no modo ano: no mês esse número é o do fluxo de caixa, e um link leva até ele.
  Nada é repetido entre as duas abas (ADR-072).
- **"Informação real", não lista limpa:** no modo mês, a presença por paciente lista **todos** os pacientes em
  atendimento, e quem não teve sessão vem por último como "sem sessão no mês". Quem está encerrado não entra. No
  modo ano entra só quem teve sessão — o ano de quem começou em dezembro não é zero.

## ADR-088 — Navegação: a barra diz o nome, o topo diz o caminho, e as sub-abas acompanham o paciente

**Contexto.** Rodada 52. "Vamos deixar o modo de usar do sistema mais agradável": o usuário pediu o nome das abas ao
passar o mouse, e que entrar, sair e voltar — a uma aba ou a uma sub-aba — fosse fácil e lógico. Levantado o que
existia: barra só de ícones com tooltip; o nome da seção no topo sem link; a ficha do paciente com sub-abas que
levavam a telas de outras seções e lá **sumiam**, então voltar de "Documentos do Marcos" para "Anamnese do Marcos"
exigia passar pela lista de pacientes; e, no celular, a barra simplesmente não existia.

**Decisões de arquitetura:**
- **A barra abre ao passar o mouse** (ou ao receber foco pelo teclado) e mostra o nome ao lado de cada ícone; fecha
  ao sair. Abre por cima do conteúdo, que não se mexe — nada pula na tela. A aba da seção corrente fica marcada, e
  clicar nela é o "sair": volta à raiz da seção. No celular a barra vira uma faixa horizontal abaixo do topo, com
  rolagem, em vez de sumir.
- **O topo mostra o caminho**: a seção, como link para a raiz dela (`core.templatetags.navegacao.raiz_da_secao`,
  resolvido pelo nome do app — coisa de navegação, sem importar domínio), e depois o nome da página, que cada
  template declara em `{% block pagina %}`. É o "voltar um nível" que sempre está no mesmo lugar.
- **As sub-abas do paciente acompanham o paciente.** A mesma barra — Cadastro · Anamnese · Registros de sessão ·
  Prontuário geral · Documentos — aparece na ficha, na anamnese, nos registros de sessão dele, no prontuário geral
  e nos documentos dele. De qualquer uma se vai a qualquer outra, sem passar pela lista. É só navegação: os
  registros continuam na seção Prontuários e o prontuário geral, em Documentos (P-90 segue aberta); as sub-abas
  levam até lá com o paciente já escolhido.
- **Nomes que dizem o que a tela contém**: na ficha, a sub-aba chama-se "Registros de sessão", e o prontuário geral,
  "Prontuário geral". O nome da seção na barra lateral ("Prontuários") não mudou — é decisão do usuário (P-90).
- Botões "Voltar" e "Cancelar" foram conferidos: cada um leva ao lugar de onde se veio (a ficha, a agenda na
  semana da sessão, a lista); o "Ficha" avulso da lista de registros saiu, porque a sub-aba Cadastro faz isso.
- Fora desta rodada: lembrar a última sub-aba aberta por paciente (exige estado por navegador) e atalhos de teclado.

## ADR-089 — O visual do sistema: direção "Prancheta", num tema único

**Contexto.** Rodada 53. "O sistema está funcional, mas o visual está básico demais." O usuário pediu duas etapas antes
de mudar qualquer coisa: um **diagnóstico** do frontend e uma **exploração de quatro direções** estéticas da tela mais
usada (o painel), isolada do app (`../design-exploration/direcoes.html`, com screenshots). O diagnóstico: aparência
inteira de fábrica do Bootstrap, três variáveis de CSS, estilo espalhado em oito blocos e 64 atributos `style`;
hierarquia achatada (tudo é cartão de mesmo peso), tipografia sem voz, espaçamento uniforme, semáforo saturado de
etiquetas, três estilos de abas. As direções — Consultório (quente, serifada, arejada), Prancheta (fria, técnica,
densa), Noite (escura, hierarquia por luz) e Cartaz (alto contraste, letra grande) — usavam o **mesmo HTML**, para a
diferença vir só de hierarquia, tipografia e espaçamento. **O usuário escolheu a Prancheta.**

**Decisões de arquitetura:**
- **Um tema, num lugar só:** `templates/components/_tema.html`, incluído pelo `base.html` e pelo login. A regra é
  **variável primeiro, componente depois, tela nunca** — cor, fonte, raio e espaçamento saem de variáveis; os
  componentes do Bootstrap são ajustados uma vez; template nenhum deve precisar de cor ou fonte própria. É peça de
  template, e não arquivo estático, pelo mesmo motivo de `_folha_estilo`: sem build e sem `collectstatic` no caminho.
- **A direção, em regras:** IBM Plex Sans no texto e **IBM Plex Mono em horas, datas e valores**; base de 13 px,
  linhas de 28–34 px; marinho `#101a2b` na moldura, fundo `#eef1f5`, superfície branca, **um acento só** (cobalto
  `#1f57c9`) para link, ação principal e foco; borda de 1 px, raio de 2 px, **nenhuma sombra** — a única é a da barra
  lateral aberta, que flutua sobre o conteúdo.
- **Hierarquia por peso e posição, não por caixa colorida.** A etiqueta de situação virou contorno em mono, sem bloco
  de cor; só "atenção" tem fundo. Em lista, o nome é tinta e só a ação é azul. No painel, **a próxima sessão do dia**
  é a única linha destacada, e a que já passou recua — coisa que a tela antiga não fazia.
- **O que tem cor por significado continua tendo:** a agenda mantém amarelo (esperada), verde (realizada), azul
  (remarcada) e cinza (livre), como o usuário definiu (ADR-073, ADR-074), agora em tons do tema e com filete à
  esquerda. A **folha** de documentos e do prontuário continua serifada, de propósito: é papel, não é tela.
- **Aplicação em duas etapas.** Esta rodada troca o tema global — moldura, cartões, botões, etiquetas, tabelas,
  listas, abas, formulários, avisos — e ajusta painel, agenda e login. Fica para a próxima: tirar os `style` soltos
  dos templates, unificar os três estilos de abas e o navegador de período numa peça só, agrupar milhar nos valores
  em reais, e rever tela a tela o que ainda depende de classe utilitária de cor.
- **Dependência nova:** Google Fonts (IBM Plex). A tela pública de cadastro já sai com `Referrer-Policy:
  no-referrer` (ADR-081), então o token do link não vaza para lá. Sem internet, cai na fonte do sistema.

## ADR-090 — A Prancheta com mais cor e com resposta ao toque (refina a ADR-089)

**Contexto.** Rodada 54. Aplicado o tema, o usuário achou o resultado pálido e parado: "quero saturar mais as cores,
tá tudo muito claro, as ações também poderiam ser mais agradáveis na hora de clicar, talvez aumentar de tamanho,
brilhar mais [...] tá muito sem graça". A direção continua; o que muda é a intensidade e o comportamento.

**Decisões de arquitetura:**
- **Mais saturação, menos branco.** Acento de `#1f57c9` para `#1558f0`; verde, âmbar e vermelho de situação mais
  vivos; fundo da página um tom mais fundo (`#e3e9f2`) e bordas mais firmes, para os cartões brancos se destacarem.
  A etiqueta de situação deixou de ser só contorno: ganhou o fundo da própria cor. As cores de situação da agenda
  subiram de tom — amarelo, verde, vermelho e azul cheios, e não pastéis.
- **Alvo maior.** Botão comum com 36 px de altura e o pequeno com 30 px (eram ~28 e ~24); abas e campos também
  cresceram. Peso 600 no rótulo do botão.
- **Toda ação responde.** Ao passar o mouse, o botão sobe 1 px e acende (brilho da cor dele); ao clicar, afunda. O
  botão principal tem brilho permanente, e é o único. Linhas de lista e de tabela, cartões da agenda, abas e itens
  da barra lateral acendem ao passar; o item ativo da barra e a marca têm um halo. O foco pelo teclado virou um anel
  luminoso. Tudo em 120 ms, e desligado para quem pede menos movimento (`prefers-reduced-motion`).
- **Revisa a ADR-089 num ponto:** lá a regra era "nenhuma sombra". Fica assim: **sombra não separa blocos** — quem
  separa é borda e espaço —, **mas brilho é resposta a gesto e marca a ação principal**.
- Continua tudo em `components/_tema.html`: foram trocadas variáveis e regras de componente, e nenhuma tela.

## ADR-091 — Três refinamentos de interação, todos globais: card de navegação, entrada de página, linha inteira

**Contexto.** Rodada 55. O usuário pediu três refinamentos "aplicados de forma global (nos componentes ou classes
compartilhadas), nunca tela por tela", com requisitos de tempo, acessibilidade e robustez, e pediu que o resultado
fosse conferido com Playwright antes de ser mostrado.

**O caminho da transição de página, e por quê.** Verificado antes de implementar: a navegação **recarrega a página
inteira** — Django renderiza no servidor, não há htmx, Turbo nem troca de conteúdo por JavaScript (o único `fetch` é o
do ViaCEP). Logo não há "saída" a animar: a página antiga simplesmente some. Escolhida **animação CSS de entrada** no
conteúdo novo. A View Transitions API entre documentos foi descartada: só existe em Chromium e Safari recentes, faria
um crossfade da página inteira — moldura incluída — e, somada à entrada, animaria duas vezes.

**Decisões de arquitetura:**
- **Entrada:** `.conteudo > *` sobe 10 px e vai de opacidade 0 a 1 em **220 ms, ease-out**, só `opacity` e
  `transform`. Três regiões, **40 ms** entre elas — cabeçalho da página, primeiro bloco, e o resto junto; nunca item a
  item. `animation-fill-mode: backwards`, e não `both`: terminado o movimento o `transform` some, e `sticky` e menus
  voltam ao normal. **Sem JavaScript**: o estado normal do conteúdo é visível, então se a animação não rodar a página
  está lá. **A moldura não anima**: topo e barra são os mesmos em toda página, e animá-los faria o sistema piscar.
- **Card de navegação** é todo card cujo link cobre o card inteiro (`.stretched-link`) — `.card:has(.stretched-link)`,
  sem classe nova para lembrar. No hover e no `:focus-visible`: borda de 2 px na cor de ação, nítida (1 px de borda +
  1 px de `box-shadow` sólido, **sem desfoque**, nada de halo); título um degrau mais pesado e texto de apoio um
  degrau mais contrastado; `scale(1.02)` por `transform`, que não empurra vizinho; **180 ms ease-out**; no `:active`
  recua a `.99`. Dentro dele o botão perde o brilho e só se enche da cor: quem responde é o card.
- **Linha que leva a algum lugar** — a de paciente entre elas — é toda linha de tabela, item de lista ou de grupo que
  tenha um link (`:has(a[href])`). A linha inteira ganha o fundo `--tinta-fundo-leve` (7% da cor principal sobre a
  superfície, por `color-mix` dos tokens existentes — cor cheia cansa numa lista longa) e a cor cheia aparece num
  detalhe só, o **filete de 3 px à esquerda**. **130 ms ease-out**, cursor `pointer`, o mesmo no foco pelo teclado
  (o anel vai para a linha). Um script de 15 linhas no `base.html` torna a área toda clicável; sem ele o link
  continua funcionando. Não intercepta link, botão, campo, menu, tecla modificadora nem seleção de texto.
- **Estado próprio não some:** a próxima sessão do painel mantém o fundo e o filete mais largo dela no hover;
  etiquetas de situação têm fundo próprio e não são tocadas.
- **Contraste medido sobre o fundo do hover** (WCAG AA pede 4,5:1): nome 16,5 · texto de apoio 6,5 · azul de ação
  5,1 · verde 6,1 · vermelho 4,5. O **âmbar reprovava** (3,5 — e 3,8 já sobre branco, defeito da ADR-090): o token
  `--atencao` foi de `#c46a00` para `#a05200`, que passa nos três fundos em que aparece.
- **Achado:** o Bootstrap pinta o hover de `.table-hover` com uma sombra interna cinza por baixo da célula, que
  brigava com o fundo do tema. Neutralizado no tema, uma vez.
- **`prefers-reduced-motion`:** sem animação de entrada, sem escala e sem transição — fica só a troca de cor,
  instantânea. Conferido por Playwright: animação `none`, escala 1,000, transição 0 s.

## ADR-092 — O financeiro do mês numa tabela só

**Contexto.** Rodada 56. O usuário: "no financeiro as informações dos pagamentos do mês repetem informações que estão
em cobranças do mês [...] faça de um jeito que continue visível e fácil de entender quais atendimentos estão pagos e
quais estão pendentes". As duas tabelas mostravam o mesmo pagamento duas vezes, de ângulos diferentes — a de cima por
cobrança, a de baixo por data de recebimento. É a regra da ADR-072 (cada coisa uma vez) aplicada ao financeiro.

**Decisões de arquitetura:**
- **Sai a tabela "Pagamentos recebidos no mês".** O que só ela tinha foi para dentro da linha da cobrança: **quando
  e como foi pago** (coluna "Pagamento": data e forma; valor de cada um quando há mais de um; observação), e o
  **desfazer** de um lançamento por engano, num menu "⋯" da própria linha, com confirmação.
- **Pago e pendente se separam por posição, peso e filete — não só pela etiqueta.** A ordem é: pendente (venceu e
  não foi quitado), a vencer, pago. A linha pendente tem filete âmbar à esquerda, que o hover não apaga (ADR-091); a
  paga recua para o tom de apoio. Pagamento parcial diz quanto falta.
- **Filtros com contagem** no cabeçalho — Todas · Pendentes · A vencer · Pagas —, para saber o tamanho de cada grupo
  antes de abrir. Os três números do topo continuam sendo do mês inteiro, qualquer que seja o filtro.
- **O que a tabela antiga mostrava e a nova não alcança**: dinheiro que entrou neste mês por cobrança de **outro**
  mês. Não volta como tabela: uma linha no rodapé diz de que meses veio e quanto, com link para cada um. Cada
  pagamento aparece na cobrança a que se refere — num lugar só.
- Excluir um pagamento volta ao mês **da cobrança**, e não ao mês em que ele foi pago: é lá que a linha está.
- A linha pendente é clicável por inteiro e leva a "registrar pagamento" (ADR-091); a paga não leva a lugar nenhum,
  e por isso não tem cursor de mão.

## ADR-093 — O valor só se pergunta na sessão avulsa (refina a ADR-070 e a ADR-074)

**Contexto.** Rodada 57. Pela ADR-074, o campo "valor desta sessão" sumia para quem paga mensalidade, mas continuava
aparecendo na sessão da frequência de quem paga **por sessão**. O usuário corrigiu: "isso só deveria acontecer com
sessões avulsas, pois sessões que já estão previamente combinadas já se sabe o valor, tanto em regime de mensalidade
quanto em regime de pagamento sessão a sessão. Cadastrar a de sessão a sessão só gera uma nova pendência de cobrança
na aba do financeiro. Quando cadastro sessão em regime de mensalidade não gera nova cobrança, pois já tem a cobrança
lá no financeiro, pago ou não."

**Decisões de arquitetura:**
- **O campo de valor existe só na sessão avulsa** — a marcada fora da frequência, que é onde o valor pode ser outro
  (a extra do mensalista, a de quem marca sem regularidade). É o que a ADR-070 quis desde o começo.
- **Sessão que já estava combinada não pergunta nada:** a da frequência e a **data nova de uma remarcação**, que é a
  mesma sessão em outro dia. O motor não muda — o devido já era cálculo (ADR-062, ADR-063): por sessão, a cobrança
  nasce da condição vigente no dia; na mensalidade, a sessão não gera cobrança porque a do mês já existe.
- **No lugar do campo, a tela diz o que vai acontecer no financeiro:** "Valor combinado: R$ 200,00 por sessão. Sendo
  cobrada, ela entra no financeiro como pagamento pendente" ou "Mensalidade de R$ 700,00: esta sessão já está na
  mensalidade do mês e não gera cobrança nova". É a pergunta que o psicólogo tem na cabeça ao cadastrar.
- **Sem valor combinado, a tela avisa** que a sessão não gera cobrança e manda combinar o valor na ficha. Descartado
  manter o campo como remendo para esse caso: o valor combinado tem um lugar só, a condição de cobrança do paciente.
- Na tela de corrigir uma sessão já cadastrada vale a mesma regra: o campo só aparece se ela for avulsa de verdade.

## ADR-094 — Cadastro do psicólogo: conta curta, assinar ou testar 7 dias, e o quiz já dentro (revoga parte da ADR-036, refaz a ADR-071)

**Status:** ✅ Aceita — Rodada 58.

**Decisão do usuário:** o psicólogo cria a conta "com informações de login e CRP logo no início"; em seguida, "se
quiser assinar de uma vez, com informações de pagamento; se não, com possibilidade de **teste grátis de 7 dias**".
Ao entrar na plataforma, "surge um quiz para ele responder e personalizar a experiência": PF ou PJ ("pra ele ter
acesso à API de nota fiscal caso seja PJ"), a abordagem — "ele vai escrever à mão", podendo ter **mais de uma** —,
outra área em que atue ("avaliação neuropsicológica, por exemplo"), nome completo, CPF, CNPJ se tiver, telefone,
se atende presencial e/ou online e, atendendo presencial, o endereço.

**O que isto revoga.** A ADR-036 dizia "sem teste gratuito", e o ganho dela era não existir conta abandonada com
prontuário dentro. Com o teste, esse problema **volta** — ver P-91. Os meios de pagamento da ADR-036 (cartão e PIX
Automático, sem boleto) continuam valendo. Da ADR-071 ficam o mecanismo (cada pergunta grava o que coletou,
`quiz_concluido_em`, o sistema trancado até o fim); mudam a ordem, as perguntas e a abordagem.

**Decisões de arquitetura:**
- **Três tempos, nesta ordem:** criar conta (e-mail, senha, CRP) → escolher entre assinar e testar → quiz. O CRP
  continua na porta porque é condição de entrada (ADR-044). Nome, CPF e telefone saíram para o quiz: pedir documento
  antes de a pessoa ver o produto era o maior atrito do cadastro.
- **Nome, CPF e telefone são vazios no banco até o quiz** — e obrigatórios nas duas telas que os gravam (quiz e
  perfil). CPF vazio é `NULL`, não `""`: a coluna é única, e duas contas a meio caminho colidiriam. Como o sistema só
  abre depois do quiz, nenhum documento sai sem eles. Ninguém conclui o quiz pulando pergunta pela barra de endereço.
- **CPF repetido é recusado pelo banco, e a tela traduz** (`contas.views.GravaSemRepetir`). O formulário não tem
  como conferir antes: dentro do sistema o RLS esconde as outras contas (ADR-046), e a consulta responderia sempre
  "não existe". Foi o teste que mostrou — a primeira versão conferia no formulário e dava erro 500.
- **Abordagem escrita à mão, quantas forem** (`abordagens`, lista em JSON), e **outras áreas de atuação**
  (`outras_areas`). A lista fechada da ADR-071 saiu; a resposta antiga foi levada para a lista nova na migração. O
  campo compartilhado é `core.formularios.ListaDeTextos` + `components/_lista_de_textos.html`: uma caixa por item,
  sem lista pronta, funciona sem JavaScript.
- **O endereço só é perguntado a quem atende presencialmente.** Quem atende só online termina uma pergunta antes.
  Nenhuma forma de atendimento vem marcada: o "presencial" que o banco tem por padrão não é resposta de ninguém.
- **PJ é a chave da nota fiscal** (`Psicologo.emite_nota_fiscal`). A integração de NFS-e ainda não existe; quando
  existir, é por essa propriedade que ela se abre. PJ sem CNPJ e PF com CNPJ continuam recusados (ADR-067).
- **Novo app `assinaturas`**, que não toca dado clínico (S-03) e depende só de `core` e `contas`. `Assinatura` é uma
  por psicólogo, com RLS. Estados no ar: `TESTE` e `ATIVA`; os demais da ADR-038 entram com a cobrança de verdade.
- **O fim do teste é calculado**, não gravado por tarefa agendada: passado o prazo, a conta já está com o teste
  encerrado, sem depender de nada ter rodado. O teste é **um por conta** — e conta é um CRP, que é único.
- **Teste encerrado tranca tudo, menos a tela da assinatura e a saída. O dado fica onde está.** O que acontece com
  ele depois é a P-91; até lá, nada é apagado.
- **`AssinaturaMiddleware`** vem depois do escopo e antes do quiz. Conta sem assinatura e com o quiz respondido
  passa: é a conta criada por código (semente, teste), que `create_user` já entrega completa pela mesma razão. A tela
  de criar conta nunca produz uma conta assim.
- **Dado de cartão nunca é digitado no Hamilton.** Fato levantado: o Asaas tem checkout hospedado para assinatura
  recorrente (`POST /v3/checkouts`, `chargeTypes: RECURRENT`, cartão e PIX, com `successUrl`/`cancelUrl`) e PIX
  Automático com cobrança recorrente. A tela de pagamento só pergunta o **meio**; com o Asaas ligado (S-01), o botão
  leva à página deles e quem ativa a assinatura é o webhook de pagamento confirmado.
- **Hoje o pagamento é simulado**, e só fora de produção: `ASSINATURA_SIMULADA` nasce de `DEBUG`, então não há `.env`
  que ligue no ar um botão que ativa a assinatura sem cobrar. Com a simulação desligada, o `POST` responde 404.
- **O preço não é inventado.** `ASSINATURA_VALOR_MENSAL` vazio: a tela diz "cobrança mensal" e mais nada (P-92).
- Durante o teste, o prazo fica à vista no alto de toda tela, com o link para assinar.
- ⚠️ Pendência técnica para a S-01b: o webhook do Asaas atualiza a assinatura **sem** psicólogo autenticado. Isso
  pede uma policy endereçada ao papel da web, como a do convite de cadastro (ADR-081) — não o afrouxamento do RLS.

## ADR-095 — O horário de atendimento se escolhe no cadastro do paciente

**Status:** ✅ Aceita — Rodada 60.

**Decisão do usuário:** "Quando eu cadastro um paciente eu não consigo escolher o horário que vou atender esse
paciente e portanto não aparece na agenda. O que deve acontecer é que eu devo cadastrar meus horários livres na aba
de horário e, quando eu cadastrar um paciente, eu ter que preencher um horário livre meu com o horário do paciente.
Aí na hora de cadastrar o paciente vai ter o quadrado pra colocar a informação do horário, mostrando meus horários
livres ou a possibilidade de um novo horário não cadastrado enquanto livre, para aquele paciente."

**O que havia.** A frequência (ADR-053) já existia, com colisão e grade — mas numa tela à parte, aonde só se chegava
pela ficha, **depois** de cadastrar. Quem cadastrava e parava ali ficava com um paciente sem sessão prevista, fora
da agenda, sem nada na tela dizendo por quê.

**Decisões de arquitetura:**
- **O bloco "Horário de atendimento" mora dentro de "Novo paciente"** e é **obrigatório responder**: toda semana, a
  cada duas semanas, ou "sem horário fixo — marco cada sessão à parte" (o avulso da ADR-053 continua existindo, mas
  passa a ser uma escolha dita, não um esquecimento). Nada vem marcado.
- **Os horários livres são os da aba Horários, menos o que já tem paciente fixo** (`agenda.grade.vagas_da_semana`),
  de hora em hora a partir do começo de cada bloco — o mesmo desenho dos horários livres do calendário (ADR-073) —
  e só onde cabe uma sessão da duração padrão do perfil. Escolher um deles o **preenche**: ele some da lista.
- **"Outro horário, fora dos meus livres"** aceita dia e hora digitados, para o paciente que só pode num horário que
  o psicólogo não tinha declarado. A grade continua sem bloquear nada (ADR-056); quem recusa é a colisão.
- **Horário já ocupado é recusado e nem o paciente é gravado**: cadastro, cobrança, contatos e frequência são uma
  transação só. A tela volta com o que foi digitado e o nome de quem ocupa o horário.
- **Vaga que a tela não ofereceu não é aceita** — o `POST` editado à mão com o horário de outro paciente é recusado
  pelo formulário, antes de chegar à colisão.
- **A regra vale da data da primeira sessão em diante** — ou de hoje, se ela já passou (ADR-022: o passado não
  ganha previsão).
- **Horário meio livre de quinzenal não é oferecido.** A semana alternada existe, mas oferecê-la pediria escolher
  também *qual* semana. Esse caso segue por "outro horário", onde a checagem de colisão decide.
- **A seta de dependência não se inverte.** `atendimentos` depende de `pacientes`, nunca o contrário — então
  `pacientes.cadastro` só define o **encaixe** (um registro de blocos: template, `is_valid`, `salvar`, `recusar`), e
  `atendimentos` se registra nele no `ready()`. A tela do paciente não importa nada de agenda.
- Trocar o horário depois continua na ficha, na tela de frequência — que ainda pede dia e hora digitados. Levar os
  horários livres também para lá é melhoria natural, não feita nesta rodada.

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
