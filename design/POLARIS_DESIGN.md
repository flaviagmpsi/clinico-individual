# Polaris · guia do redesign

Outubro de 2026. Desenho fechado no canvas de design, sem tocar no sistema. Este guia é o que o código precisa
seguir, e `tokens.css` tem os valores. Os nomes `telas/...` e `fontes/...` que aparecem aqui são as imagens e as
pranchetas do canvas de design: quem implementa não as recebe. A usuária compara as capturas de cada etapa com o
canvas, e o que ela apontar vale.

Quando o canvas e o guia discordarem, vale o guia. Quando o guia discordar de uma ADR em vigor, a seção 12 diz qual
ADR muda; o que não estiver lá é pergunta para a usuária, não decisão de quem implementa.

Canvas interativo (dá para clicar, abrir painéis e trocar Claro/Noturno nos Tweaks de cada prancheta):
https://claude.ai/code/artifact/5ff57f4c-12ea-4e83-a3f8-c94626b69446

---

## 1. As decisões que guiam tudo

1. **Céu claro com luz índigo no topo.** Toda tela logada tem o mesmo fundo: degradê lavanda que clareia até
   quase branco, com uma luz índigo vinda de cima. O fundo rola com a página (no Noturno, fica fixo).
2. **Cartões brancos com sombra suave**, sobre o céu. Textura de grão por cima de tudo, quase invisível.
3. **Índigo é a marca.** Cor forte só no que pede ação (botão principal, item ativo) ou no que tem significado
   (situação da sessão, do pagamento, do prontuário). O resto é tinta e cinza azulado.
4. **Cadastrar e registrar acontece num painel lateral**, por cima da tela onde a pessoa está. Ao salvar, o painel
   fecha, a tela continua a mesma e um aviso no canto confirma, com **Desfazer**. O sistema nunca muda de tela
   sozinho: cadastrar sessão pelo Painel não leva para a Agenda.
5. **Não existe atalho de presença.** Todo registro de sessão passa pelo painel "Cadastrar sessão", porque o
   paciente pode ter faltado, remarcado ou cancelado.
6. **Confortável por padrão** (letra de 15px), com a opção Compacta em Configurações.
7. **Claro, Noturno e Seguir o computador**, escolhidos em Configurações.
8. **Movimento curto e sem quique.** Uma celebração só: a estrela brilha quando as pendências chegam a zero.
9. **O CRP nunca é fixo.** Região e número saem sempre da conta de cada psicóloga. Nas imagens aparece
   "CRP 00/00000" como marcador; no código, é o CRP da conta (e, na criação de conta, a região escolhida).
10. **Nada de identidade Allos.** O Polaris tem marca própria: a estrela de oito pontas e o índigo.

---

## 2. Cor

Os valores completos, com o Noturno, estão em `tokens.css`. Os nomes seguem os de `_tema.html`; o papel de cada
um não mudou (`--tinta` continua sendo o acento, e a cor do texto continua sendo `--texto`).

### 2.1 Base (Claro)

| Papel | Variável | Valor |
|---|---|---|
| Fundo de toda tela | `--ceu` | degradê, ver tokens |
| Cartão | `--superficie` | #FFFFFF |
| Cabeçalho de tabela, rodapé de cartão | `--superficie-2` | #F8F8FC |
| Texto principal (nomes, títulos, valores) | `--texto` | #15123F |
| Texto corrido e clínico | `--texto-corrido` | #2A2750 |
| Texto secundário | `--suave` | #5E617A |
| Borda de cartão | `--linha` | #E3E2EF |
| Divisória | `--linha-fina` | #EEEDF6 |
| Borda de campo e botão secundário | `--linha-campo` | #D6D5E6 |
| Acento | `--tinta` | #544CE8 |
| Link | `--link` | #450CB0 |
| Lavado de seleção | `--tinta-fundo` | #F0F0FF |
| Dock | `--dock` | degradê #2C2386 → #1B1560 |

### 2.2 Situação

Cada situação aparece sempre com **ícone e palavra**, nunca só com cor.

| Situação | Fundo | Texto | Borda | Ícone | Onde |
|---|---|---|---|---|---|
| Presente, pago, ativa | #DDEFE2 | #2C5A3C | igual ao fundo | ✓ | agenda, painel, financeiro, assinatura |
| A cadastrar, pendente | #FFE9D6 | #7A3A0C | #F0C29C | relógio/alerta #C2581A | agenda, painel, financeiro |
| Faltou | #FAD9DA | #8A2D2D | #F3CACA | × | agenda, painel |
| Vencido | #FDECEA | #8A2D2D | barra de 3px #A8281E à esquerda | triângulo | painel, financeiro |
| Vence hoje | sem fundo | #15123F | barra de 3px #C2581A à esquerda | relógio | financeiro |
| Cancelada | transparente | #66647A riscado | #E3E2EF | nenhum | agenda |
| Prevista | #FFFFFF | #15123F | #DCDDF3 | nenhum | agenda |
| Próxima | #F0F0FF | #15123F | #C9CDF7 (no Painel, barra de 3px #544CE8 à esquerda) | palavra "próxima" em #450CB0 | agenda, painel |
| Remarcada | #FFFFFF | #15123F | #DCDDF3 | círculo, "remarcada de dd/mm" | agenda |
| Agendada (consulta avulsa marcada antes, ADR-139) | #C9E1F7 | #18507F | #9EC5EC | calendário com ✓, palavra "agendada" | agenda, cadastro avulso |
| Agendada que passou sem atualizar | igual a "A cadastrar" | igual a "A cadastrar" | igual a "A cadastrar" | relógio, "agendada · atualizar" | agenda; no Painel, pendência "sessões agendadas para atualizar" |
| Livre | transparente | #66647A | tracejado 1,5px #CFCDE0 | nenhum | agenda, novo paciente |
| Outro compromisso | #E0DFE8 | #4A4760 | igual ao fundo | nenhum | agenda, meus horários |
| Não escrito (prontuário) | #FBEFC9 | #5C4209 | #EBCF86 | nenhum | prontuários |
| Selo neutro | transparente | #5E617A | #DDDCEB | conforme o caso | geral |

**Medido como pede a regra do `claude.md` (seção 3.2b, que veio da ADR-110):** estados que precisam se distinguir de
relance ficam a ΔE de pelo menos 10. Entre os preenchimentos da agenda (prevista, a cadastrar, presente, faltou,
outro compromisso, agendada), a menor distância é **ΔE 10,6** no Claro (agendada e outro compromisso) e **ΔE 11,0**
no Noturno (Lab, distância euclidiana;
no Noturno, a cor já composta sobre o cartão). Presente e prevista ficam a 11,8: perto do 11,1 que a ADR-110 achou
pouco para a paleta antiga. Aqui elas também se separam pela borda (prevista tem, presente não), pelo ícone ✓ e pela
palavra; a usuária decidiu manter assim (seção 12, item 7). "Próxima" fica fora da conta de propósito: é uma prevista
destacada, e se separa pela borda índigo e pela palavra. Para chegar nisso, três fundos mudaram em relação ao que
estava no canvas antes deste pacote: presente (#EAF3EC → #DDEFE2), faltou (#FBE4E4 → #FAD9DA) e outro compromisso
(#EEEDF4 → #E0DFE8); no Noturno, faltou (16% → 20%, mais rosado) e outro compromisso (6% → 14% de branco).

### 2.3 Frequência do paciente (ADR-109)

| Frequência | Traço (faixa no bloco, gráfico) | Texto | Fundo da inicial |
|---|---|---|---|
| Semanal | #544CE8 | #3F37C4 | #ECEBFD |
| Quinzenal | #C98A2B | #7A5410 | #FBF0DC |
| Avulso | #3E8FD9 | #1F5F96 | #E6F1FB |

### 2.4 Gráficos

Categórico, sempre nesta ordem: #544CE8, #C98A2B, #3E8FD9 (Noturno: #747AED, #C0851F, #248FCC).
Presença: presentes #2B7A4B, canceladas pelo paciente #9A948A, faltas sem avisar #DA4A3D
(Noturno: #3D9C5E, #67635C, #E06255). Fundo de barra #EEEDF6. Barras com canto de 3px, sem grade pesada,
rótulo de valor direto na barra quando couber, dica ao passar o mouse.

### 2.5 Contraste medido

| Par | Contraste |
|---|---|
| Texto #15123F sobre cartão | 17,6:1 |
| Texto corrido #2A2750 sobre cartão | 14,0:1 |
| Suave #5E617A sobre cartão / sobre o topo do céu | 6,1:1 / 5,1:1 |
| Link #450CB0 sobre cartão | 10,9:1 |
| Branco sobre botão #544CE8 | 5,9:1 |
| Placeholder #6B6D85 sobre campo | 5,1:1 |
| Presente / a cadastrar / faltou / vencido | 6,7 / 7,3 / 6,4 / 7,4:1 |
| Não escrito / outro compromisso / cancelada | 8,2 / 6,7 / 5,7:1 |
| Semanal / quinzenal / avulso (texto sobre fundo) | 7,0 / 6,0 / 5,9:1 |
| Ícone do dock / item ativo | 9,2 / 9,7:1 |
| Aviso flutuante / "Desfazer" | 17,6 / 9,6:1 |
| Noturno: texto / suave / link sobre cartão | 15,3 / 8,5 / 9,9:1 |
| Noturno: texto escuro sobre botão #929BF5 | 7,4:1 |

A borda de campo (#D6D5E6, 1,45:1) não passa dos 3:1 sozinha; o campo se reconhece também pela sombra interna
e pelo rótulo acima. Se a regra de 3:1 para borda de controle for mantida à risca, escurecer para #8E8CA4 (3,3:1 sobre
o cartão, 3,0:1 sobre o fundo).

---

## 3. Letra

Duas famílias, carregadas do Google Fonts (link no topo de `tokens.css`). A Bitter sai.

- **Figtree** em toda a interface: texto, botões, rótulos, números. Números com `font-variant-numeric: tabular-nums`
  (horas, datas, valores, contagens), na mesma letra, como já é a regra do `--f-num`.
- **Newsreader** só em dois lugares: títulos de página e de seção grande, e o que a psicóloga escreve (prontuário,
  anamnese, notas, a folha dos documentos).

| Uso | Família | Tamanho | Peso | Outros |
|---|---|---|---|---|
| Título de página ("Olá, Marina", "Financeiro · outubro de 2026") | Newsreader | 38 a 40px | 500 | entrelinha 1,1; −0,01em |
| Título de seção grande ("Como a clínica funcionou em outubro") | Newsreader | 26 a 28px | 500 | |
| Título de painel lateral e de modal | Newsreader | 26px | 500 | |
| Título de cartão ("Hoje", "Pendências") | Figtree | 17px | 600 | |
| Número de destaque (R$ 6.880,00, 87%) | Figtree | 32 a 44px | 600 | −0,02em, tabular |
| Corpo | Figtree | 15px | 400 | entrelinha 1,5 |
| Nome em lista | Figtree | 15px | 500 | |
| Botão | Figtree | 15px (14px no compacto) | 600 | |
| Secundário, meta | Figtree | 13,5 a 14px | 400 | `--suave` |
| Legenda, rótulo de campo | Figtree | 13px | 500 | `--suave` |
| Texto clínico (campo de escrita) | Newsreader | 18px | 400 | entrelinha 1,6 |

Sem caixa alta na interface nova. A classe `.rotulo` do tema atual (caixa alta, 11px) deixa de ser usada nas telas
redesenhadas; os rótulos viram frase normal em 13px. **Cuidado com o nome:** no HTML das pranchetas, o balão com o
nome do ícone do dock usa a classe `rotulo`; no código, dar outro nome (por exemplo `.dock-nome`) para não colidir
com a `.rotulo` que já existe.

---

## 4. Espaço, cantos, sombra

- Conteúdo com largura máxima de **1240px**, alinhado à esquerda do espaço que sobra depois do dock.
- Respiro: 24px entre cartões, 20 a 24px de preenchimento dentro do cartão, linhas de lista com 56 a 64px de altura.
- Cantos em escala: 8px chip · **10px campo e botão** · 12px aviso e cartão interno · **14px cartão** ·
  18 a 20px painel lateral e modal · 22px dock · pílula para selos.
- Sombra só em quatro coisas: cartão (bem leve), cartão clicável sob o mouse, o que flutua (painel lateral, modal,
  menu, aviso) e o botão principal. Borda de 1px continua em todo cartão.

---

## 5. Moldura

Vale para todas as telas logadas. Ver `telas/01-painel.jpg`.

**Dock (a barra lateral).** Coluna de 96px; dentro dela, uma barra flutuante de 64px de largura, a 16px da borda,
que acompanha a rolagem (`position: sticky; top: 16px`). Fundo em degradê índigo, cantos de 22px, sombra própria.
De cima para baixo: a estrela do Polaris (leva ao Painel), separador, Painel e Pacientes, separador, Agenda,
Prontuários e Financeiro. Cinco entradas, como na ADR-105.

- Cada item é um quadrado de 48px com canto de 14px e ícone de 22px (traço 1,75, pontas redondas).
- **Não expande.** Ao passar o mouse ou receber foco pelo teclado, aparece ao lado do ícone um balão com o nome
  (fundo #15123F, texto branco, 13,5px peso 600, canto 9px, com uma pontinha). Entra em 120ms, deslizando 4px.
- Item da seção atual: fundo #3A30A8, ícone branco, `aria-current="page"`.
- Os SVGs dos ícones e da estrela estão em `fontes/Painel.dc.html`, no `<nav aria-label="Seções">`, prontos para
  copiar para `_barra.html`.
- No celular, o dock deita e vai para baixo da tela, com o nome sempre visível (seção 14).

**Topo.** 48px de altura, sem fundo próprio (é o céu). À esquerda, o caminho: seção como link, depois a página
(ADR-088). À direita, a conta (ADR-105): avatar com as iniciais (fundo #E9E8FD, letra #3F37C4), nome em peso 600 e
"CRP rr/nnnnn" em `--suave`, saído da conta. Ao passar o mouse, balão "Meu perfil" abaixo, fora do fluxo. Ao lado,
o ícone de ajustes leva a Configurações.

**Faixa da rodada de testes** (ADR-114). Logo abaixo do topo, em toda tela: fundo #F0F0FF, borda #E1E0F5,
canto 12px, ícone de frasco, texto 14px. A faixa do prazo do teste grátis (ADR-094) não foi desenhada à parte:
usar o mesmo componente, com o link "Assinar".

---

## 6. Componentes

Folhas de referência: `telas/20-componentes-botoes-campos.png` e `telas/21-componentes-tabela-calendario-avisos.png`.

### Botões

| Tipo | Aparência | Uso |
|---|---|---|
| Principal | fundo #544CE8, texto branco, sombra de botão | uma por área: Salvar, Cadastrar sessão, Registrar pagamento |
| Secundário | fundo branco, borda #D6D5E6, texto #15123F | Cancelar, Remarcar ou cancelar, Escrever |
| Discreto | só texto #450CB0 | Ver agenda, Corrigir, Ver pacientes |
| Perigo | fundo branco, borda #EBC3BE, texto #A8281E; confirmado: fundo #A8281E | Excluir |
| Só ícone | 44×44, secundário, com `aria-label` | menu de mais opções |

Altura 44px (36 a 40px no compacto ou dentro de lista), preenchimento lateral 18 a 20px, canto 10px, peso 600.
Estados: mouse em cima #4A42DA e sobe 1px com sombra maior; pressionado #3F37C4 e escala 0,98; foco pelo teclado
com anel duplo (2px branco + 2px índigo); desativado #ECE9F2 com texto #8E8BA3; carregando #6C65EC com
indicador girando e o texto no gerúndio ("Salvando").

### Campos

44px de altura, canto 10px, borda 1px #D6D5E6, sombra interna leve, texto 15px. Rótulo acima, 13px peso 500.
Foco: borda 2px #544CE8 e anel de 4px em índigo a 14%. Erro: borda #A8281E e mensagem abaixo com ícone, dizendo
o que fazer ("O CPF tem 11 números. Faltou um."). Campo que pode ficar vazio leva "(opcional)" ao lado do rótulo;
**sem asterisco**. Campo de escrita clínica: Newsreader 18px, canto 12px, preenchimento 14px 16px.

### Escolhas

- Caixa de seleção e opção única: 20px, índigo quando marcadas.
- Interruptor: 44×26, índigo ligado, #DCD8E4 desligado. Usado em Configurações.
- Segmentado: trilho #EEEDF6, opção ativa em cartão branco com sombra leve (Online/Presencial, Mês/Ano, tema).
- Opção grande (painel lateral): cartão com borda #DDDCEB, ícone em quadradinho colorido, selecionada com
  contorno interno de 2px índigo e fundo #F0F0FF. Usada em "Como foi a sessão?" e na pergunta do recibo.
- Chips de catálogo (abordagens, ADR-107): pílulas com borda, marcadas com ✓ e fundo #F0F0FF.

### Selos

Pílula com preenchimento de 4px 10px, 13px peso 600, com ícone de 12px quando houver. Cores da seção 2.2.

### Cartão

Branco, borda #E3E2EF, canto 14px, sombra leve. Cabeçalho com título 17px peso 600 e, à direita, a ação discreta
("Ver agenda"). Cartão inteiro clicável ganha a sombra de hover e sobe 1px.

### Lista e tabela

Linhas de 56 a 64px separadas por #EEEDF6. Cabeçalho de tabela em #F8F8FC, 13px `--suave`, sem caixa alta.
Hora e valor em tabular. Linha sob o mouse: fundo índigo a 6%. A ação da linha fica à direita, alinhada; só a
ação que pede atenção é botão principal (por exemplo "Cadastrar sessão" na sessão que já passou).

### Painel lateral

O padrão de todo cadastro e registro. Flutua a 12px das bordas da janela, canto 18px (20px no largo), sombra
flutuante, véu #15123F a 18% atrás. Largura 460px; 760px para o cadastro de paciente. Cabeçalho com título em
Newsreader 26px e uma linha de contexto ("Otávio Siqueira Melo · hoje, 14:00 · presencial"), botão de fechar.
Rodapé fixo com Cancelar e a ação principal; a ação fica desativada até a escolha obrigatória ser feita, e o
rodapé diz o que falta ("Escolha como foi a sessão"). Fecha com Esc, com o fechar e clicando no véu; o foco vai para
o primeiro campo ao abrir e volta para o botão que abriu ao fechar.

Painéis desenhados: Cadastrar sessão (no Painel; na Agenda do computador abre o mesmo painel, sem prancheta
própria), Novo paciente, Registrar pagamento (Financeiro e ficha), Nova despesa, Novo ganho. Em Meus horários,
adicionar horário e compromisso são formulários no próprio cartão, não painéis.

### Aviso flutuante (toast) com Desfazer

Canto inferior esquerdo, ao lado do dock. Fundo #15123F, texto branco 14px, canto 12px, botão "Desfazer" em
#BAB9F9. Some sozinho em 4 a 5 segundos (mais tempo quando a frase é maior); o mouse em cima segura. `role="status"`. Texto diz o que aconteceu, com o
nome: "Sessão de Otávio cadastrada: presente", "Cadastro de Ana salvo" (com "Abrir ficha").

### Confirmação destrutiva

Modal de 420px no centro, título em Newsreader com a pergunta ("Excluir Clara Vidal Prado?"), o que acontece em uma frase,
campo para escrever o primeiro nome, e os botões "Manter paciente" (secundário) e "Excluir" (perigo cheio).
Para ações reversíveis não há modal: faz e oferece Desfazer.

### Modal de aviso do dia

O aniversário (ADR-134): cartão central de até 420px, ícone de bolo, título "Aniversário hoje", nome em link, uma
linha de apoio e "Fechar". Aparece uma vez por dia. Ver `telas/01-painel-aniversario.jpg`.

### Telas vazias, carregando e erro

Vazio: ícone simples em quadrado lavado, título em Newsreader 22px, uma linha que diz o próximo passo e a ação.
"Tudo em dia" usa só a estrela, com brilho dourado. Carregando: blocos cinza-lavanda no formato do conteúdo, sem
girador de página inteira. Erro: ícone em quadrado vermelho claro, título que diz o que não carregou, frase que
tranquiliza ("Seus dados estão guardados") e "Tentar de novo".

### Calendário

Mês em grade de 7 colunas, título em Newsreader, dia de hoje com contorno índigo, dia escolhido cheio em
#544CE8, ponto embaixo do dia que tem sessão.

---

## 7. Movimento

| O quê | Como |
|---|---|
| Hover de botão, link, item | cor em 120ms |
| Cartão clicável | sombra e 1px para cima em 180ms |
| Balão do dock e "Meu perfil" | opacidade em 120ms, desliza 4px em 160ms |
| Painel lateral | opacidade 160ms; desliza de fora da tela, pela direita, em 280ms com a curva `cubic-bezier(.2,.8,.2,1)` |
| Véu | opacidade em 220ms |
| Aviso flutuante | opacidade 200ms, sobe 16px em 260ms com a mesma curva |
| Item recém-criado | borda índigo e anel lavado de 4px por 2,6 segundos, depois volta ao normal |
| "Tudo em dia" | a estrela gira 45° e brilha em dourado em 700ms, uma vez |

Nada quica, nada pisca em laço. Com `prefers-reduced-motion`, tudo vira troca imediata e a estrela não gira.
Ver `fontes/Movimento.dc.html` no canvas para sentir os tempos.

---

## 8. Noturno

Céu noturno em degradê (fixo na rolagem), cartões foscos (`rgba(18,21,31,.74)` com desfoque de 16px), grão mais
presente (55%), dock translúcido com desfoque. O acento clareia para #929BF5 e o texto do botão principal fica
escuro (#0E1024). Os estados viram fundos translúcidos com texto claro. Todos os valores estão no bloco
`[data-bs-theme="dark"]` de `tokens.css`; o atributo é o do próprio Bootstrap 5.3, então os componentes dele
viram junto.

A escolha mora na conta (Configurações > Aparência: Claro, Noturno, Seguir o computador). "Seguir o computador"
aplica o atributo a partir de `prefers-color-scheme` e escuta a mudança. Para não piscar, o atributo precisa estar
no `<html>` já no HTML que o servidor manda.

**Densidade.** Confortável (padrão) e Compacta. A Compacta reduz tudo em 10% (`font-size: 90%` na raiz, com o
tema todo em rem). Também mora na conta.

---

## 9. Acessibilidade

- Contrastes da seção 2.5. Situação sempre com ícone e palavra.
- Alvo de clique mínimo de 44px (36px só dentro de lista densa, com espaço em volta).
- Foco visível em tudo, com anel índigo; nunca `outline: none` sem substituto.
- Painel lateral e modal com `role="dialog"`, `aria-modal`, título ligado por `aria-labelledby`, foco preso dentro
  enquanto abertos.
- Ícone sozinho sempre com `aria-label`; ícone ao lado de texto com `aria-hidden`.
- Gráficos com `aria-label` que diz o número ("Presença em outubro: 20 presentes, 2 canceladas pelo paciente,
  1 falta sem avisar"), como nas pranchetas.
- Aviso flutuante com `role="status"`; erro de campo ligado ao campo por `aria-describedby`.

---

## 10. Telas, uma a uma

Ordem sugerida de implementação: moldura e tema primeiro (tudo melhora junto), depois Painel, Agenda, Pacientes e
a ficha, Prontuários, Financeiro, Documentos, Configurações e Meu perfil, e por fim as telas de fora do sistema.

| # | Tela | Imagens em `telas/` | Template(s) que substitui | O que muda | ADRs |
|---|---|---|---|---|---|
| 0 | Moldura e tema | todas | `base.html`, `components/_barra.html`, `components/_tema.html` | dock flutuante sem expansão; topo com caminho e conta; céu, grão, Figtree e Newsreader; Noturno e densidade | 088, 105, 108, 114 |
| 1 | Painel | `01-painel*` | `painel.html`, `indicadores/_retrato_da_clinica.html`, `_periodo.html`, `_graficos.html` | "Hoje" com ação por linha (Cadastrar sessão para a que passou, Remarcar ou cancelar para a futura, Corrigir para a cadastrada); Pendências agrupadas e abrindo a pedido; cartões de sessões e receita do mês; bloco "Como a clínica funcionou"; modal de aniversário Pendência nova "sessões agendadas para atualizar" (ADR-139), no mesmo formato das outras. | 072, 104, 131, 132, 134, 136, 139 |
| 2 | Cadastrar sessão | `01-painel-cadastrar-sessao` | `atendimentos/cadastrar.html`, `atendimentos/editar.html`, `atendimentos/_dinamica.html` | vira painel lateral aberto de onde a pessoa está (Painel ou Agenda); quatro opções grandes (Presente, Faltou, Cancelada, Remarcar), e o que cada uma pede aparece só depois de escolhida (pagamento, quem cancelou, novo dia e horário), como na ADR-074, mais o lembrete opcional para o prontuário. O "Cobrar esta sessão" do cancelamento pelo paciente não foi desenhado: manter, logo abaixo de "Quem cancelou"; na sessão futura, Presente e Faltou travadas com a explicação; salvar volta para a mesma tela com aviso e Desfazer | 074, 110, 131 |
| 3 | Agenda | `02-agenda*` | `atendimentos/agenda.html`, `_cartao.html`, `_situacao.html`, `_abas.html`, `indicadores/_retrato_da_agenda.html` | semana em colunas de cartões; legenda com ícones; hoje em destaque; período em segmentado e filtro de situação em lista; "Cadastrar consulta avulsa"; bloco de estatísticas do mês Estado Agendada (ADR-139) com as cores da seção 2.2; no cadastro avulso, data futura sugere Agendada e data passada, nada (a pessoa escolhe). | 110, 139 |
| 4 | Meus horários | `03-agenda-meus-horarios*` | `agenda/horarios.html` | mapa da semana em linha do tempo; quatro números (Disponível, Com paciente fixo, Livre = disponível − com paciente fixo, Ocupação); formulários de horário e de compromisso; grade declarada em lista | 124 |
| 5 | Pacientes | `04-pacientes*` | `pacientes/lista.html`, `indicadores/_presenca_dos_pacientes.html` | blocos com faixa colorida da frequência e barra de presença total; abas Em atendimento e Encerrados; busca; botão "Link de cadastro" com a contagem de links abertos | 109, 135 |
| 6 | Novo paciente | `05-novo-paciente*` | `pacientes/formulario.html`, `components/_endereco_por_pais.html`, `atendimentos/_horario_no_cadastro.html` | painel lateral largo por cima da lista; só o nome é obrigatório; horários livres como chips que preenchem dia e hora; ao salvar, o bloco novo aparece marcado e o aviso oferece "Abrir ficha" | 081, 109 |
| 7 | Ficha do paciente | `06-ficha-*` | `pacientes/detalhe.html`, `pacientes/_abas.html`, `prontuarios/anamnese.html`, `documentos/aba.html`, `documentos/_lista.html` | cabeçalho com nome, idade, frequência e próxima sessão; quatro abas no topo; Cadastro em duas colunas (dados à esquerda, frequência e financeiro à direita); Anamnese com temas que se movem e arquivam; Documentos com o prontuário geral em destaque e os modelos do CFP em cartões; sem botão "Voltar" (o caminho no topo faz isso) | 088, 101, 102 |
| 8 | Prontuários | `07-prontuarios-*` | `prontuarios/lista.html`, `prontuarios/escrever.html`, `prontuarios/_convite_ia.html` | lista do que falta escrever com selo "Não escrito" e filtro por paciente; escrita em Newsreader com a escrita assistida no topo (gravar, transcrever, gerar) e, ao lado, o lembrete deixado no cadastro da sessão e a sessão anterior; Salvar rascunho; "Escrever o próximo" | 111, 127 |
| 9 | Financeiro | `08-financeiro-*` | `financeiro/mes.html`, `outros_ganhos.html`, `despesas.html`, `fluxo.html`, `_abas.html`, `_cabecalho.html`, `pagamento_form.html`, `receita_externa_form.html`, `despesa_form.html`, `_categoria_da_despesa.html`, `indicadores/_resultado_previsto.html` | quatro abas (Receitas, Outros ganhos, Despesas, Fluxo de caixa); três números no topo de cada aba; cobranças do mês em tabela com filtro por situação; vencidas de meses anteriores em bloco próprio; pagamento, despesa e ganho em painel lateral; no pagamento, a pergunta do recibo é obrigatória e sem opção marcada | 132, 133, 136 |
| 10 | Documento | `09-documento-*` | `documentos/modelo.html`, `documentos/_folha.html`, `documentos/_folha_estilo.html`, `documentos/imprimir.html`, `documentos/prontuario.html`, e na raiz de `templates/`: `_folha_preenchivel_estilo.html`, `_folha_preenchivel_js.html` | a folha A4 no centro, preenchida no próprio papel (lacunas em amarelo claro); ao lado, a lista do que falta para emitir; "Emitir" com confirmação e um tempo para desfazer; baixar só depois do primeiro rascunho salvo | 102 |
| 11 | Configurações e Meu perfil | `10-*` | `contas/configuracoes.html`, `contas/perfil.html`, `components/_catalogo.html` | Configurações: interruptores (despesas, IA), Aparência (tema e densidade), pessoa física ou jurídica com confirmação no lugar, Sair. Meu perfil: índice à esquerda, seções em cartões, regime só leitura com link para Configurações, barra de alterações não salvas | 105, 107, 111 |
| 12 | Assinatura | `11-assinatura-*` | `assinaturas/plano.html`, `assinaturas/pagamento.html` | quatro estados (teste em andamento, escolher pagamento, ativa, teste encerrado); PIX Automático ou cartão, com a nota de que o cartão é digitado no Asaas; sem preço na tela | 094 |
| 13 | Entrada | `12-entrada*` | `registration/login.html`, `registration/_entrada.html` | fundo índigo inteiro com só a estrela, brilho dourado; cartão branco; erro de senha no próprio cartão. Escolhido o tom Índigo; Violeta e Azul elétrico ficaram como alternativa | |
| 14 | Esqueci a senha | `13-senha-*` | `registration/senha_pedir.html`, `senha_enviada.html`, `senha_trocar.html`, `senha_trocada.html` | mesmo fundo da entrada; cinco estados, incluindo link vencido | |
| 15 | Criar conta | `14-criar-conta-*` | `contas/criar_conta.html`, `contas/quiz.html` | cadastro curto com CRP (região em lista + número); "Como começar"; as perguntas do quiz uma por tela; primeiro acesso já com o dock e o Painel vazio | 094 |
| 16 | Cadastro pelo link | `15-cadastro-pelo-link-*` | `pacientes/cadastro_publico.html`, `cadastro_publico_fim.html` | tela de celular; cabeçalho com nome e CRP da psicóloga; texto de abertura igual ao atual, com a frase dos asteriscos trocada pela dos campos marcados como opcional; campos que aparecem só quando servem (menor de idade, estrangeiro, nome social, quem paga, segundo contato); CEP preenche o endereço; aviso de privacidade com aceite; quatro estados de fim | 039, 081, 118 |
| 17 | Tour de boas-vindas | `16-boas-vindas-*`, `c07-boas-vindas-*` | `contas/_boas_vindas.html`, `contas/tour/*.html`, `contas/boas_vindas.py` (texto) | modal em passos no visual novo, com mini telas montadas com as peças do sistema, destaque em anel índigo em vez do círculo vermelho; no celular, tela cheia. Ver seção 15 | 138 |

### Templates sem prancheta própria

Herdam a moldura, os tokens e os componentes, sem desenho novo:
`atendimentos/frequencia.html`, `atendimentos/desfecho.html`, `pacientes/cobranca.html`, `pacientes/pagador.html`,
`pacientes/responsavel_form.html`, `pacientes/responsavel_excluir.html`, `pacientes/excluir.html` (usar a
confirmação destrutiva), `pacientes/caso_novo.html`, `pacientes/caso_detalhe.html`, `pacientes/caso_excluir.html`,
`pacientes/historico.html`, `pacientes/convites.html`, `components/_campo.html`, `components/_lista_de_textos.html`.
Os que são formulário curto e partem de outra tela (frequência, cobrança, pagador, responsável) são bons
candidatos a painel lateral; confirmar com a usuária antes.

---

## 11. Dados das imagens

Tudo nas pranchetas é fictício: a psicóloga Marina Alves, 13 pacientes em atendimento e 3 encerrados, outubro de
2026, CRP 00/00000. Nada disso entra no código. Os números batem entre as telas (presença de 87%, receita do mês,
pendências), mas só servem para conferir o desenho.

---

## 12. O que muda em relação às decisões em vigor

Para registrar em `complicacoes.md` antes de implementar:

1. **ADR-108 (direção terrosa) é revogada.** Nova direção: céu claro com luz índigo, cartões brancos, Figtree e
   Newsreader, Claro e Noturno. A regra "variável primeiro, componente depois, tela nunca" continua.
2. **ADR-088, a parte da barra, é revista.** A barra vira dock flutuante que não abre; o nome aparece por ícone,
   num balão. O topo com o caminho e as sub-abas que acompanham o paciente continuam. No celular, a faixa
   horizontal no alto vira o dock embaixo, com o nome de cada seção sempre visível.
3. **ADR-097 (escala de cantos) muda de valores:** controle 10px, cartão 14px, painel 18px.
4. **Tema "um só" deixa de ser um só.** Noturno e Seguir o computador entram, com densidade Compacta; são
   preferências novas na conta.
5. **A regra "sombra não separa blocos" (ADR-090) muda.** Cartão ganha sombra leve sobre o céu; o que flutua ganha
   sombra forte. O brilho como resposta a gesto, da mesma ADR, continua.
6. **Cadastrar sessão e Novo paciente viram painel lateral** e, ao salvar, a pessoa continua onde estava. Hoje
   `atendimentos/views.py` redireciona para a semana da sessão (`redirect(_semana_de(...))`); isso contraria a regra
   da usuária. Sem JavaScript, o formulário continua como página e volta para a origem.
7. **ADR-110, em parte.** A regra de medir a distância entre estados continua, e as cores novas passam (seção 2.2).
   Duas escolhas dela saem: a barra lateral de 5px com a cor cheia do estado (o código ainda tem, em
   `atendimentos/agenda.html`) e o "só a cadastrar tem preenchimento" (aqui presente, faltou e outro compromisso
   também têm fundo lavado). O desenho separa os estados por fundo, borda, ícone e palavra. Decidido com a
   usuária: fica sem a barra lateral.
8. **Caixa alta sai da interface** (a `.rotulo` deixa de ser usada nas telas novas).
9. **ADR-138 (tour de boas-vindas) ganha visual novo e ajustes de texto** em `contas/boas_vindas.py`, listados
   na seção 15. O comportamento (uma vez só, sem reabrir, prioridade sobre o aniversário) não muda.
10. **No cadastro de sessão, nenhuma opção vem marcada.** Hoje `CadastrarPrevista.get_initial` deixa "Presente"
   escolhido para a sessão que já passou; no desenho, a escolha é sempre um gesto ("Escolha como foi a sessão"),
   pela regra de não haver atalho de presença. Decidido com a usuária.

---

## 13. Como o design acompanha as atualizações

O sistema muda toda semana. O desenho só acompanha se a referência visual deixar de ser este pacote e passar a ser
o próprio código. Por isso:

1. **O que é para sempre e o que é de uma vez só.** As seções 1 a 9 e 14 são regras e valem para qualquer tela, inclusive
   as que ainda não existem. A seção 10 e as imagens são o mapa desta migração: servem para fazer a troca e depois
   envelhecem. Não é preciso atualizar as imagens quando o sistema mudar.
2. **As regras moram no `claude.md`.** As seções 1 a 9 e 14, resumidas, entram na seção 3.2b do `claude.md`, que é o que
   o Claude Code lê antes de qualquer mudança. Assim toda feature nova já nasce no visual novo.
3. **A vitrine de componentes.** Uma página interna (por exemplo `/vitrine/`, só para conta logada) que mostra cada
   componente real do sistema, nos dois temas e nas duas densidades, com texto fictício e o trecho de template de
   uso. Ela usa os mesmos includes das telas, então quando um componente muda, a vitrine muda junto. Depois da
   migração, é ela a referência, e não as imagens.
4. **Tela nova é montada, não desenhada.** Usa os componentes que existem e não declara cor, letra, canto nem sombra
   (a regra que já existe: variável primeiro, componente depois, tela nunca). Se faltar um componente, ele nasce no
   `_tema.html`, entra na vitrine e ganha uma linha no `claude.md`. Cor nova é medida antes (seção 2.5 e ADR-110).
5. **Fluxo novo segue os padrões de fluxo.** Cadastrar e registrar em painel lateral; ficar na tela depois de salvar,
   com aviso e Desfazer; situação com ícone e palavra; CRP sempre da conta.
6. **Conferência a cada rodada.** Um script do Playwright, guardado no repositório, tira captura das telas principais
   no computador (1440px) e no celular (390px), em Claro e Noturno, e mais uma vez em Compacta. Rodar antes e depois de cada mudança mostra o que mudou sem querer.
7. **Quando voltar ao canvas.** Tela nova grande ou mudança de fluxo vale desenhar antes. Ajuste, campo novo, coluna
   nova ou aba nova se resolvem direto no código, seguindo as regras.

O desenho foi conferido contra o commit `b65475b` do `origin/main` (22/10/2026, com o tour de boas-vindas da ADR-138 e o
estado Agendada da ADR-139).
O que mudou nos templates depois dele precisa ser olhado na migração.

---

## 14. Celular

Decidido com a usuária: dock embaixo, painéis como folha que sobe de baixo, agenda um dia por vez, e desenho próprio
para Painel, Agenda, Pacientes e ficha, Prontuário e Financeiro. As outras telas se ajeitam sozinhas em uma coluna,
com as mesmas peças. Imagens em `telas/c01-*` a `telas/c07-*`; fontes em `fontes/Cel*.dc.html`.

**É o mesmo sistema, não um aplicativo à parte.** Mesmos templates, mesmas URLs, mesmas regras; o que muda é o CSS
por faixa de largura. Até 767px vale o layout de celular; de 768px em diante, o do computador (dock na lateral),
que já se ajeita em uma coluna nas larguras de tablet.

### 14.1 Moldura

- **Topo** de 60px, sem fundo próprio. À esquerda, a estrela e o nome da tela; numa tela de segundo nível, um
  voltar com o nome de onde se veio ("‹ Pacientes", "‹ Para escrever"), que substitui o caminho do computador.
  À direita, o avatar (leva a Meu perfil) e os ajustes (leva a Configurações), cada um num alvo de 44px. Nome e
  CRP saem do topo, como o sistema já faz abaixo de 576px.
- **Faixa da rodada de testes** em uma linha: "Rodada aberta de testes. Saiba mais", e o texto inteiro abre no toque.
- **Dock embaixo.** Flutua a 12px das bordas (somando a área segura do iPhone, `env(safe-area-inset-bottom)`),
  66px de altura, canto 22px, o mesmo degradê índigo. Cinco itens de largura igual, ícone de 22px e o **nome sempre
  visível** em 11px peso 600, porque no toque não existe passar o mouse. Item atual com fundo #3A30A8 e texto
  branco. No Noturno, o fundo é `rgba(30,24,98,.88)` com desfoque, para o conteúdo de trás não aparecer através.
  O dock some na escrita do prontuário, nos formulários em tela cheia e no tour.
- **Conteúdo** com 16px de margem lateral, cartões com canto de 16px e 108px livres no fim da página, para o último
  item não ficar atrás do dock.
- **Título de página** em Newsreader de 24 a 32px.

### 14.2 Folha que sobe

Substitui o painel lateral em todo cadastro e registro. Sobe de baixo em 280ms (mesma curva), cantos de 22px no alto,
uma alça de 40×5px, até 92% da altura, véu atrás. Título em Newsreader 25px com a linha de contexto, botão de fechar.
Rodapé fixo com **Cancelar e a ação principal lado a lado, do mesmo tamanho, 48px de altura**; acima deles, quando
falta algo, a frase que diz o quê ("Escolha como foi a sessão", "Escolha a forma e diga se o recibo já saiu"). Fecha pelo ×,
tocando no véu e, no sistema, também arrastando a alça para baixo (o protótipo não simula o arrasto). Ao salvar, fecha e a pessoa continua na mesma tela, com o aviso e o Desfazer.

Formulário longo (Novo paciente) e o tour abrem em **tela cheia**: × à esquerda, título, rodapé fixo, dock escondido.
No Novo paciente, as seções além de Identificação e Horário ficam fechadas e abrem no toque.

### 14.3 Peças no celular

- **Aviso flutuante** logo acima do dock, de ponta a ponta com 12px de margem.
- **Tabela vira lista.** Cada linha leva nome, o que é, data, valor e situação; a linha inteira é tocável, com seta.
  A ação que pede atenção aparece como botão dentro da linha (Cadastrar sessão, Registrar).
- **Abas** sublinhadas. Quando não cabem, rolam na horizontal (Financeiro); na ficha, as quatro dividem a largura e
  perdem a contagem, que aparece dentro de cada aba.
- **Toque:** alvo mínimo de 44px; 48px nos botões de rodapé. Nada depende de passar o mouse: o que no computador
  é dica ao passar o mouse vira uma linha que abre no toque.
- **Campos com letra de 16px.** Abaixo disso o iPhone aproxima a tela ao tocar no campo.
- **Números grandes** de 23 a 38px; dois cartões de número lado a lado no máximo.
- **Gráficos** simplificados: uma barra empilhada ou barras simples com o valor escrito.

### 14.4 Telas

| Tela | Imagens | O que é próprio do celular |
|---|---|---|
| Painel | `c01-painel*` | Hoje com a linha inteira tocável; "Cadastrar sessão" como botão dentro da linha da sessão que passou; as outras abrem a folha certa (Corrigir, Remarcar ou cancelar). Pendências abrem a pedido e terminam com "Abrir em ...". |
| Agenda | `c02-agenda*` | Um dia por vez. Faixa da semana com dia e data, ponto embaixo do dia que tem sessão (laranja se há sessão a cadastrar), "Hoje" para voltar. Filtro compacto e "O que cada cor quer dizer" na mesma linha. As sessões do dia em cartões com os estados da seção 2.2. "+ Cadastrar consulta avulsa" no fim, e os números do mês em 2×2. |
| Pacientes | `c03-pacientes*` | Linhas com a inicial na cor da frequência, faixa fina da frequência, dia e hora, presença total em barra. Só aparece dinheiro quando pede atenção. Presença paciente a paciente em lista. |
| Novo paciente | `c03-novo-paciente*` | Tela cheia; Salvar desligado até ter um nome; horários livres como chips. |
| Ficha | `c04-ficha*` | Voltar "‹ Pacientes". O que pede ação vem primeiro (situação financeira com Registrar pagamento), depois frequência e os dados. Anamnese em sanfona; documentos em lista. Registrar pagamento abre a folha com a pergunta do recibo. |
| Prontuário | `c05-prontuarios*` | Na escrita, o dock some e uma barra fixa leva Salvar rascunho e Salvar prontuário. Botão de gravar redondo e grande no alto do bloco de escrita assistida; estados gravando (tempo, barras de nível, Pausar, Parar), transcrito (a barra troca para Gravar de novo e Gerar o registro) e gerado. O texto gerado é corrido, sem títulos (ADR-137). |
| Financeiro | `c06-financeiro*` | Abas roláveis; os três números num cartão; chips de filtro; cobranças em lista com Registrar; vencidas de meses anteriores em bloco próprio; pagamento, despesa e ganho em folha; forma de pagamento em grade 2×2 de opções; fluxo de caixa com o gráfico do ano reduzido, e o toque num mês mostra os números dele. O menu "…" de cada linha do computador (dar o mês como quitado à mão, ADR-133; editar; excluir) não foi desenhado no celular: vai para um botão "…" de 44px na linha, que abre uma folha com essas ações. |
| Tour de boas-vindas | `c07-boas-vindas*` | Tela cheia, progresso em segmentos no alto com Pular, rodapé fixo com Voltar e Avançar. |
| Cadastro pelo link | `15-cadastro-pelo-link*` | Já era de celular. |

Sem desenho próprio no celular, em uma coluna com as mesmas peças: Configurações, Meu perfil, Assinatura, Meus
horários, Documento (a folha A4 encolhe para a largura da tela, e a lista do que falta para emitir vem antes dela),
Entrada, Esqueci a senha e Criar conta (o cartão ocupa a largura, com 16px de margem).

---

## 15. Tour de boas-vindas (ADR-138)

O tour já existe no sistema, no visual antigo. Imagens em `telas/16-boas-vindas-*` (computador) e
`telas/c07-boas-vindas-*` (celular); fontes em `fontes/BoasVindas.dc.html` e `fontes/CelBoasVindas.dc.html`.

**Computador.** Modal de cerca de 640px no centro, canto de 20px, sobre o Painel com o véu. No alto, o progresso em
13 segmentos finos e "Pular" à direita. No meio, o palco: uma mini tela no visual novo (cartões brancos sobre um
pedaço de céu, os dados fictícios das pranchetas), depois o título em Newsreader 27px e o texto em 15px. No rodapé,
"3 de 13" à esquerda, Voltar (secundário) e Avançar (principal), que no último passo vira "Começar a usar".

**Celular.** Tela cheia, dock escondido. Progresso em segmentos no alto com "Pular", a mini tela na largura, o texto,
e o rodapé fixo com "3 de 13" acima de Voltar e Avançar, a 48px; Avançar é o mais largo.

**Destaque.** Um anel índigo (2px #544CE8, com halo lavado até 5px) em volta do que está sendo mostrado, e uma nota
lavada com seta índigo apontando para ele. **Não usar o círculo tracejado vermelho do código atual:** vermelho, aqui,
quer dizer vencido e falta. As notas foram reescritas como frases curtas sobre o que está destacado, para não
repetir o texto do passo.

**Primeiro e último passo** usam a estrela do Polaris, dourada, com brilho suave e parada (sem animação; a única
celebração do sistema continua sendo a das pendências zeradas).

**As mini telas precisam acompanhar o sistema.** No código atual, cada uma (`contas/tour/<chave>.html`) é desenhada
à mão com cores próprias, e ficaria velha na primeira mudança de tela. No redesign, montar cada mini tela com as
mesmas peças do `_tema.html` (as mesmas classes de linha, selo, cartão), dentro de um contêiner reduzido, e sem cor
declarada. Quando uma tela mudar, a mini tela muda junto. Trocar por captura real, como a ADR-138 previa, continua
possível pelo mesmo lugar no template.

**Ajustes de texto em `contas/boas_vindas.py`:**
- Passo 1: "Bem-vindo ao Polaris" vira "Boas-vindas ao Polaris", que já é o título do modal e não tem gênero.
- Passo 13: "pelo menu à esquerda" vira "pelo menu", porque no celular o menu fica embaixo.
- Todos os passos: os travessões viram ponto ou vírgula. O passo 4 foi reescrito assim: "Em cada uma, você registra
  se foi presença, falta, cancelamento ou remarcação. E a remarcação pode ser cadastrada antes mesmo do horário."
- Passos 10 e 13 também tiveram frases reescritas ao tirar os travessões ("com supervisão, ONG, emprego CLT ou um
  bico?", "Se surgir alguma dúvida").
- O texto final de cada passo está em `fontes/BoasVindas.dc.html`.
