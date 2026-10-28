# WhatsApp do Polaris

Guia para quem vai ligar o Polaris ao WhatsApp — escrito pensando na Flávia, que está programando com IA.
O que já está montado na Meta, os modelos de mensagem, os que ainda faltam criar, e como pedir isso à IA sem
cair nas armadilhas.

Decisões por trás disto: **ADR-141** (app e conta próprios), **ADR-043** (WhatsApp para aviso de descarte),
**ADR-039** (o sistema não fala com paciente), **ADR-018** (lembretes do dia a dia ficaram fora do WhatsApp).
Status e pendências: `demandas.md`, seção "Lembretes por WhatsApp".

---

## O que já existe na Meta

| O quê | Valor |
|---|---|
| Número | **+55 31 8779-6335** — nome de exibição "Polaris", `CONNECTED`, até 250 pessoas por dia |
| `WHATSAPP_PHONE_NUMBER_ID` | `1413166918549157` |
| `WHATSAPP_WABA_ID` (conta de mensagens "Polaris") | `1068509042871904` |
| App de desenvolvedor | Polaris — `1161658156725329` |
| Portfólio | Associação Allos (empresa verificada) |
| Moeda | BRL |
| Cartão | ⚠️ **ainda não cadastrado** — ver "O que o cartão muda" |

O `.env` (os valores secretos vêm do Paulo, por gerenciador de senhas — **nunca** por WhatsApp, e-mail ou commit):

```
WHATSAPP_TOKEN=                 # token permanente do usuário do sistema, gerado para o app Polaris
WHATSAPP_PHONE_NUMBER_ID=1413166918549157
WHATSAPP_WABA_ID=1068509042871904
WHATSAPP_APP_SECRET=            # app Polaris → Configurações do app → Básico → Chave secreta
WHATSAPP_WEBHOOK_VERIFY_TOKEN=  # frase aleatória: openssl rand -hex 24
WHATSAPP_API_VERSION=v26.0
```

No Render, as mesmas chaves entram em **Environment** do serviço, e no `render.yaml` com `sync: false` (como a
`OPENAI_API_KEY`), para o valor nunca ir para o Git.

⚠️ No portfólio, o token é do usuário do sistema **`Sofia_bot`**. **Nunca clique em "Anular tokens" nele**: isso
derruba também o token que a Sofia usa. O número **não tem PIN de duas etapas** (decisão do Paulo): o chip da Claro
é a única chave dele — tem de ficar guardado e recarregado.

---

## Duas regras da Meta que mandam em tudo

**1. A janela de 24 horas.** Quando uma pessoa escreve para o número, abre uma janela de 24h em que o sistema pode
responder com **texto livre**. Fora dessa janela, o sistema só pode mandar um **modelo aprovado** (template). Todo
lembrete que o sistema dispara por conta própria — agenda do dia, aviso de conta — é fora da janela, logo é modelo.

**2. Modelo é texto fixo com lacunas.** A Meta aprova o texto antes; o sistema só preenche `{{1}}`, `{{2}}`... na
hora de enviar. Mudou uma vírgula, é modelo novo e nova aprovação.

### O que o cartão muda

Responder dentro da janela de 24h é gratuito. **Modelo enviado fora da janela é cobrado**, e sem cartão a Meta
recusa o envio (erro `131042`). Ou seja: até o cartão entrar na conta Polaris, os modelos abaixo podem estar
aprovados, mas **não saem**.

---

## Os três modelos criados (2026-10-28)

Todos vão para o **psicólogo** — nunca para o paciente (ADR-039) — e **sem nome de paciente nem nada clínico**
(ADR-043): o WhatsApp passa pelos servidores da Meta, e saber que alguém faz terapia já é dado de saúde.

Onde criar: **Gerenciador do WhatsApp** → conta **Polaris** (seletor no canto superior direito) → **Modelos de
mensagem → Gerenciar modelos → Criar modelo** → categoria **Utilidade** → idioma **Português (BR)** → tipo de
variável **Número**. Copie o corpo exatamente, preencha os exemplos e envie para análise.

### 1. `aviso_exclusao_conta` — ✅ já cabe nas regras (ADR-043)

| Campo | Valor |
|---|---|
| Categoria | Utilidade |
| Corpo | `Olá, {{1}}. Sua assinatura do Polaris está {{2}}. Se nada mudar, os dados da sua conta serão apagados em {{3}}. Para manter seus dados, acesse o Polaris e regularize a assinatura.` |
| Exemplos | `{{1}}` Ana · `{{2}}` cancelada · `{{3}}` 15/12/2026 |
| Rodapé | `Mensagem automática do Polaris` |

### 2. `agenda_do_dia` — 🟡 aprovar na Meta pode; **usar no código depende de decisão**

| Campo | Valor |
|---|---|
| Categoria | Utilidade |
| Corpo | `Olá, {{1}}! Hoje você tem {{2}} sessões na agenda, a primeira às {{3}}. Os detalhes estão no Polaris.` |
| Exemplos | `{{1}}` Ana · `{{2}}` 5 · `{{3}}` 08:00 |
| Rodapé | `Mensagem automática do Polaris` |

### 3. `pendencias_da_semana` — 🟡 idem

| Campo | Valor |
|---|---|
| Categoria | Utilidade |
| Corpo | `Olá, {{1}}! Resumo da sua semana no Polaris: {{2}} prontuários para escrever e {{3}} cobranças em aberto. Acesse o Polaris para ver os detalhes.` |
| Exemplos | `{{1}}` Ana · `{{2}}` 3 · `{{3}}` 2 |
| Rodapé | `Mensagem automática do Polaris` |

Por que 2 e 3 dependem de decisão: a ADR-018 deixou os lembretes do dia a dia **fora** do WhatsApp (custo e
agendador), e o `claude.md` diz "WhatsApp só para descarte de conta". Usá-los no código exige uma ADR nova que
revogue isso em parte, e resolver quem dispara o envio todo dia (impeditivo I-05: o Render não tem agendador
gratuito — a saída recomendada é um cron externo gratuito chamando uma rota protegida do Polaris).

---

## 📌 Próximos modelos — para a Flávia criar

Ficaram na conta **Sofia** (aprovados em 03/10) e **não** foram recriados no Polaris, porque cada um esbarra numa
regra do projeto. Antes de criar qualquer um, a decisão tem de estar escrita como ADR no `complicacoes.md`.

| Modelo | O que trava |
|---|---|
| Lembrete de sessão **para o paciente** | ADR-039 (o sistema nunca fala com paciente) e consentimento LGPD registrado do paciente |
| Confirmação de presença **sim/não** | Tudo do item acima, mais **webhook** no ar para receber a resposta (botões de resposta rápida) |
| Cobrança / vencimento **para o paciente** | ADR-039; e o texto não pode levar nada clínico |
| Cobrança **para o psicólogo** citando o paciente | ADR-043: o nome do paciente no WhatsApp revela tratamento — use contagem ("2 cobranças vencidas"), não nome |

### Como criar um modelo novo sem ser recusado

1. **Nome** em minúsculas com `_`: `lembrete_sessao`, não `Lembrete Sessão`. O nome não muda depois.
2. **Categoria certa.** *Utilidade* é aviso ligado à conta ou a algo que a pessoa já tem (sessão, cobrança).
   Qualquer tom de propaganda ("aproveite", "conheça") vira *Marketing*, que é mais caro e mais vigiado.
3. **Variável nunca no começo nem no fim do texto**, e nunca duas coladas (`{{1}} {{2}}`). Termine com uma frase.
4. **Exemplo para toda variável** — a Meta recusa sem.
5. **Nada que a Meta não deva ver**: nome de paciente, diagnóstico, CID, conteúdo de sessão.
6. Depois de aprovado, o código usa **o nome e o idioma exatos** (`pt_BR`). Nome ou idioma diferente dá erro
   `132001`.
7. Botões: *resposta rápida* (sim/não) só serve com webhook no ar; *link* pode apontar para o Polaris.

---

## Como mandar um modelo (o que o código vai fazer)

```bash
curl -X POST "https://graph.facebook.com/v26.0/1413166918549157/messages" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "messaging_product": "whatsapp",
    "to": "+5531999999999",
    "type": "template",
    "template": {
      "name": "agenda_do_dia",
      "language": {"code": "pt_BR"},
      "components": [{"type": "body", "parameters": [
        {"type": "text", "text": "Ana"},
        {"type": "text", "text": "5"},
        {"type": "text", "text": "08:00"}
      ]}]
    }
  }'
```

Os parâmetros vão **na ordem** de `{{1}}`, `{{2}}`, `{{3}}`. Sempre com `+55` e DDD no número de destino.

### Erros que vão aparecer

| Código | O que é | O que fazer |
|---|---|---|
| `190` | Token inválido ou anulado | Pedir token novo ao Paulo; conferir o `.env` |
| `131042` | Problema de pagamento | Falta cartão na conta Polaris |
| `131047` | Passaram as 24h da janela | Mandar um modelo em vez de texto livre |
| `132001` | Modelo não existe nesse nome/idioma | Conferir nome exato e `pt_BR`; ver se já foi aprovado |
| `131026` | Não deu para entregar | O número de destino não tem WhatsApp, ou bloqueou o Polaris |

---

## Webhook (quando houver resposta para receber)

Só é preciso para **receber**: resposta "sim/não", status de entrega e leitura (a ADR-043 quer a prova de entrega do
aviso de descarte). Para só **enviar**, não precisa.

1. Uma rota pública do Polaris (por exemplo `/whatsapp/webhook/`) que:
   - no **GET**, compara `hub.verify_token` com `WHATSAPP_WEBHOOK_VERIFY_TOKEN` e devolve `hub.challenge`;
   - no **POST**, confere a assinatura `X-Hub-Signature-256` com o `WHATSAPP_APP_SECRET` antes de acreditar em
     qualquer coisa, e responde **200 rápido** (a Meta reenvia o que demora).
2. Ignore o que não for do Polaris: confira `metadata.phone_number_id == WHATSAPP_PHONE_NUMBER_ID`.
3. ⚠️ **Celular brasileiro e o 9º dígito:** o número que chega no webhook (`wa_id`) às vezes vem **sem o 9**. Normalize
   antes de comparar com o telefone cadastrado, senão a resposta não casa com ninguém.
4. Com a rota no ar: o Paulo (ou o Claude, pelo MCP da Meta) aponta o app Polaris para a URL. A assinatura do app na
   conta (`POST /1068509042871904/subscribed_apps`) já tem de estar feita.

---

## Dicas para programar isto com IA

**Antes de pedir código**
- Peça à IA para ler `claude.md`, este arquivo e as ADRs citadas no topo. O projeto tem regras que a IA não adivinha
  — a principal aqui é "nada clínico no WhatsApp e nada para o paciente".
- Comece pedindo um **plano**, não código: "Proponha como implementar o envio do `aviso_exclusao_conta`: que
  arquivos, que funções, que testes. Não escreva código ainda." Leia, pergunte o que não entendeu, só então peça o
  código.
- Uma coisa de cada vez: primeiro **enviar** um modelo; depois agendar; por último webhook.

**Enquanto programa**
- Toda chamada à Meta num só lugar — um adaptador, como `prontuarios/ia.py` faz com a OpenAI. O resto do sistema
  chama "avisar exclusão de conta", e não sabe que existe WhatsApp.
- `requests` com **timeout**, e erro da Meta **nunca derruba a tela**: registre, avise em português, siga.
- Peça **testes** que não chamem a Meta de verdade (com a chamada simulada). Rode `python manage.py test` antes de
  cada commit.
- Peça à IA para **explicar** o código que ela escreveu, linha a linha, até fazer sentido. Se não fizer, não suba.

**Segredo**
- Token e App Secret só no `.env` local e no Environment do Render. Nunca no código, no chat com a IA, num print ou
  no Git. Se vazou, avise o Paulo: o token se anula e se gera outro.
- Antes de cada commit, olhe o `git diff` procurando `EAA` (todo token da Meta começa assim).

**Testando**
- Para o primeiro teste, mande "oi" do seu celular para o +55 31 8779-6335 e responda com texto livre (janela de
  24h). Só depois parta para modelo.
- Teste com o seu número, nunca com o de um psicólogo real.

**Prompt de partida, para copiar**

> Leia `claude.md`, `WHATSAPP.md` e as ADRs 018, 039, 043 e 141 do `complicacoes.md`. Quero implementar o envio do
> modelo `aviso_exclusao_conta` pela WhatsApp Cloud API, com as variáveis de ambiente do `WHATSAPP.md`. Antes de
> qualquer código, me proponha um plano curto: onde fica o adaptador, como o resto do sistema chama, como tratar
> erro sem derrubar a tela e quais testes escrever. Explique como se eu estivesse aprendendo.
