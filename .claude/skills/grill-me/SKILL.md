---
name: grill-me
description: Entrevista implacável para afiar um plano ou design. Use quando o usuário quiser estressar o raciocínio, ou usar qualquer frase-gatilho tipo "grill", "me questione", "me sabatine".
---

Entreviste o usuário implacavelmente até chegarem a um entendimento compartilhado. Mapeie isso como uma **árvore de decisão**: cada decisão ramifica nas decisões que dependem dela.

Trabalhe a árvore em **rodadas**. A **fronteira** é toda decisão cujos pré-requisitos já estão resolvidos: as perguntas que você pode fazer _agora_ sem chutar respostas que ainda não ouviu.

**Restrição deste projeto: no máximo 3 perguntas por rodada.** Se a fronteira tiver mais de 3, priorize as de maior risco arquitetural/regulatório e guarde o resto para a próxima rodada. Numere cada pergunta e dê sua resposta recomendada. Depois **pare e aguarde** as respostas do usuário antes da próxima rodada.

Formate uma rodada assim:

```
❓ **Q1** — **<título da pergunta>**: <corpo da pergunta, pode ter múltiplos parágrafos, incluindo alternativas>

➡️ <sua resposta recomendada>

---

❓ **Q2** — **<título da pergunta>**: <corpo>

➡️ <sua resposta recomendada>
```

Cada rodada de respostas remodela a árvore: decisões resolvidas empurram a fronteira para fora e desbloqueiam perguntas que dependiam delas. Recalcule a fronteira e faça a próxima rodada. Uma pergunta cuja resposta depende de outra ainda aberta nesta rodada pertence a uma rodada _posterior_, não a esta.

Descobrir **fatos** é trabalho seu, nunca do usuário. Quando uma pergunta da fronteira precisar de um fato do ambiente (sistema de arquivos, código, documentação de API, ferramentas), vá buscar você mesmo; não pergunte ao usuário nada que você poderia consultar. Não bloqueie por isso: uma investigação em andamento é um pré-requisito não resolvido, então só as perguntas dependentes dela esperam; faça o resto da fronteira agora. As **decisões** são do usuário: apresente cada uma e aguarde.

A sessão termina quando a fronteira está vazia: todo ramo da árvore visitado, nada assumido em silêncio. Não aja sobre o plano até o usuário confirmar que vocês chegaram a um entendimento compartilhado.
