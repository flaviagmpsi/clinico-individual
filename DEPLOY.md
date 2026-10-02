# Como subir o Hamilton

Banco no **Neon**, aplicação no **Render**. O que já está feito e o que falta você fazer.

---

## O que já está pronto

O banco de produção **existe e está migrado**: projeto `hamilton-individual-producao` no Neon, banco `hamilton`,
81 migrações aplicadas, 27 tabelas com RLS ligada e forçada, 30 políticas de isolamento, **zero contas**.

Ele é um projeto **separado** do `hamilton-individual-dev` de propósito. O de desenvolvimento tem as contas de
demonstração com senha conhecida (`ana@exemplo.com` / `hamilton123`) — nada disso pode existir num endereço
público. Uma ramificação do Neon não serviria: ela copia os dados do pai.

Os valores para colar no Render estão em **`.env.producao`**, que fica fora do Git.

---

## Os três papéis do banco, e por que são três

| Papel | Quando é usado | Alcança |
|---|---|---|
| `hamilton_owner` | só o `migrate`, no build | tudo, inclusive ignorar o RLS |
| `hamilton_web` | a conexão da aplicação e a requisição anônima | login e sessão. **Nada de clínico** |
| `hamilton_app` | `SET LOCAL ROLE` na requisição autenticada | o domínio, filtrado pelo RLS |

É por isso que há **duas `DATABASE_URL`**. Se a aplicação conectasse com o papel dono, um `RESET ROLE` emendado
numa injeção de SQL devolveria o banco inteiro, e o RLS seria decorativo (ADR-046). O `build.sh` roda
`check --deploy` **com a URL da aplicação**: se ela tiver `BYPASSRLS`, o deploy para ali.

---

## O que falta você fazer

### 1. Criar o serviço no Render

⚠️ **Tem de ser `New → Blueprint`, não `New → Web Service`.** Só o Blueprint lê o `render.yaml`. No caminho de
Web Service, o Render propõe `pip install -r requirements.txt` e `gunicorn app:app` — e os dois estão errados
aqui: o primeiro pula o `collectstatic`, o `migrate` e o portão de segurança; o segundo aponta para um módulo que
não existe neste projeto.

Se você já criou como Web Service, apague o serviço e recrie como Blueprint, ou preencha à mão:

| Campo | Valor |
|---|---|
| Build Command | `bash build.sh` |
| Start Command | `gunicorn config.wsgi:application --workers 2 --timeout 120` |
| Health Check Path | `/saude/` |
| Region | Ohio |

...e aí **todas** as variáveis abaixo precisam ser digitadas, inclusive as que o Blueprint preencheria sozinho
(`PYTHON_VERSION=3.12.4`, `DEBUG=False`, `ACESSO_LIBERADO=True`, `IA_SINTESES_POR_MES=40`, `SECRET_KEY` e
`ALLOWED_HOSTS`).

1. Em [dashboard.render.com](https://dashboard.render.com), **New → Blueprint**.
2. Conecte `github.com/PauloHenriqueL/clinico-individual`. Ele lê o `render.yaml` sozinho.
3. Em **Environment**, cole os valores que o `render.yaml` marca como `sync: false`:

| Variável | De onde vem |
|---|---|
| `DATABASE_URL` | `.env.producao` — papel `hamilton_web` |
| `DATABASE_URL_MIGRACAO` | `.env.producao` — papel dono |
| `OPENAI_API_KEY` | a mesma do `.env` de desenvolvimento |
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | o passo 2 |

`SECRET_KEY` e `ALLOWED_HOSTS` o Render preenche sozinho.

### 2. Escolher um serviço de e-mail (P-105)

Sem `EMAIL_HOST`, a recuperação de senha **manda a mensagem para o console do servidor** — quem esquecer a senha
pede o link e espera para sempre. Resend ou Brevo têm faixa grátis de sobra para esta rodada; os dois pedem um
domínio verificado para a mensagem não cair em spam.

### 3. Antes de convidar as pessoas

- **O `/admin/` está exposto** na raiz (P-107). É uma tela de login que dá acesso a tudo.
- **O termo que o testador aceita** ao criar a conta (P-106): são pacientes reais, de terceiros.

---

## O que esperar no primeiro acesso

O plano grátis do Render **hiberna depois de 15 minutos parado**, e a visita seguinte demora uns 30 segundos até
a aplicação acordar. Não é defeito. Trocar para pago é mudar `plan: free` no `render.yaml`.

O endereço de saúde é `/saude/`: devolve `ok` sem tocar o banco, de propósito — um Neon lento não pode parecer
aplicação caída e disparar um reinício.

---

## Se o deploy falhar

| O que aparece | O que é |
|---|---|
| `core.E001` no build | A `DATABASE_URL` aponta para um papel com `BYPASSRLS`. Use a do `hamilton_web`. |
| `SECRET_KEY não definida` | Falta a variável. O `render.yaml` manda gerar; confira se ela existe no painel. |
| `permission denied for table ...` | A `DATABASE_URL_MIGRACAO` não é a do papel dono. |
| `DisallowedHost` | `ALLOWED_HOSTS` sem o domínio do serviço. |

---

## Trocar a senha do banco

A senha do `hamilton_web` **não vive no repositório**. Para trocá-la, conecte com o papel dono e rode
`ALTER ROLE hamilton_web WITH LOGIN PASSWORD '...'`; depois atualize a `DATABASE_URL` no Render.
