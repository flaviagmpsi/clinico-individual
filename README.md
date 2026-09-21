# Hamilton Individual — clínico individual

ERP para o psicólogo clínico autônomo. Muitos psicólogos, **sem vínculo entre si**, na mesma
aplicação, cada um com isolamento total dos seus dados.

O contexto de produto e as decisões estão em [claude.md](claude.md) (resumo operacional) e
[complicacoes.md](complicacoes.md) (as ADRs, que são a fonte da verdade).

## Estado

**Passos 0 a 3 concluídos**: a fundação do isolamento (ADR-001) e a prova de que ela segura; conta com
quiz de cadastro e perfil; pacientes; agenda com as cinco situações da sessão e remarcação com destino;
financeiro básico; painel como agenda do dia; prontuário escrito à mão; documentos psicológicos no formato do CFP. Os próximos são **despesas** (N-05)
e a **lixeira de pacientes** (ADR-048). A IA de prontuário fica por último (ADR-058).

👉 **Se você vai programar aqui, leia [demandas.md](demandas.md) antes de tudo.** Ele diz, história
por história, o que está decidido, o que está no ar e o que não existe — e traz a receita para
criar um model novo sem furar o isolamento.

## Três papéis de banco, e por que importa

O Row-Level Security do Postgres só vale para quem **não** pode ignorá-lo. O papel dono do
banco no Neon tem `BYPASSRLS`, e conectar com ele deixa a policy decorativa — protegido na
aparência, aberto na prática. Daí a separação (ADR-045):

| Papel | Usado quando | Alcança |
|---|---|---|
| `hamilton_owner` | só `migrate` (DDL exige) | tudo |
| `hamilton_web` | **conexão da aplicação** e requisição anônima | login e sessão. Nada de clínico |
| `hamilton_app` | `SET LOCAL ROLE` na requisição autenticada | o domínio, filtrado pelo RLS |

`hamilton_web` é `NOINHERIT`: ele pode *virar* `hamilton_app`, mas não *é* `hamilton_app`.
Por isso um `RESET ROLE` — a fuga clássica de uma injeção de SQL — cai num papel sem
permissão alguma nas tabelas clínicas, em vez de devolver o banco inteiro.

## Subir localmente, do zero

Precisa de **PostgreSQL 16+**. Não use SQLite: metade das garantias deste projeto vive no banco,
e em SQLite os testes que importam se pulam sozinhos.

### 1. Banco

Se você não tem um Postgres à mão, suba um em Docker:

```bash
docker run -d --name hamilton-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16

docker exec -e PGPASSWORD=postgres hamilton-pg psql -U postgres -d postgres \
  -c "CREATE ROLE hamilton_owner LOGIN PASSWORD 'ownerpass' CREATEDB CREATEROLE;" \
  -c "CREATE DATABASE hamilton_dev OWNER hamilton_owner;"
```

> `CREATEDB` é necessário porque o runner de testes cria e destrói o banco de teste.

### 2. Dependências e configuração

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

No `.env`, para o setup em Docker acima:

```
SECRET_KEY=qualquer-coisa-longa-para-desenvolvimento-local-000000
DEBUG=True
DATABASE_URL=postgresql://hamilton_web:websenha@127.0.0.1:5432/hamilton_dev
DATABASE_URL_MIGRACAO=postgresql://hamilton_owner:ownerpass@127.0.0.1:5432/hamilton_dev
```

### 3. Migrar, liberar o papel da aplicação, semear

A ordem importa, e o motivo está na tabela de papéis acima.

```bash
# migrar com o papel DONO (só ele pode fazer DDL)
DATABASE_URL="postgresql://hamilton_owner:ownerpass@127.0.0.1:5432/hamilton_dev" \
  python manage.py migrate

# dar login e senha ao papel da aplicação — uma vez só, fora do repositório
docker exec -e PGPASSWORD=ownerpass hamilton-pg psql -U hamilton_owner -d hamilton_dev \
  -c "ALTER ROLE hamilton_web LOGIN PASSWORD 'websenha';"

# dados de demonstração: dois psicólogos, para o isolamento ficar visível
DATABASE_URL="postgresql://hamilton_owner:ownerpass@127.0.0.1:5432/hamilton_dev" \
  python manage.py semear
```

### 4. Servir

```bash
python manage.py runserver     # usa a DATABASE_URL do .env = hamilton_web
```

Abra **http://127.0.0.1:8000** e entre com:

| Login | Senha | Tem |
|---|---|---|
| `ana@exemplo.com` | `hamilton123` | 12 pacientes, uma semana cheia |
| `bruno@exemplo.com` | `hamilton123` | 2 pacientes |

Entre com um, depois com o outro. O banco tem 14 pacientes; cada psicólogo vê só os seus, e só o
próprio cadastro em "Meu perfil". Nenhuma view filtra por psicólogo — quem corta é o RLS.

### O que existe de tela

Criar conta e quiz de cadastro · login · painel (agenda de hoje) · pacientes com busca, ficha, cadastro
(à mão ou por **link que o paciente preenche**), edição e exclusão · agenda com filtros, frequência, cadastro de sessão, remarcação e desfecho · grade de
horários · financeiro do mês com registro de pagamento, **despesas** e **fluxo de caixa** · **estatísticas** (resultado
previsto do ano e retrato dos atendimentos) · **anamnese** opcional na ficha · prontuários (os registros de sessão) · documentos psicológicos (modelos, rascunho, emissão e impressão) e o
prontuário geral do paciente, na forma da Res. CFP 001/2009, montado com os registros de sessão · PDF e DOCX de
documentos e do prontuário geral · meu perfil.

## Testes

Exigem **PostgreSQL**. Em SQLite a camada de RLS não existe e os testes dela se pulam
sozinhos, em vez de passar em falso.

```bash
DATABASE_URL="postgresql://hamilton_owner:ownerpass@127.0.0.1:5432/hamilton_dev" \
  python manage.py test --parallel 4
```

O runner precisa criar o banco de teste, então roda com o papel dono. São **583 testes**, e nenhum
fica pulado. Contra um PostgreSQL local levam cerca de **1 minuto e 40 segundos com `--parallel 4`**.

⚠️ **Rode em paralelo.** Em série a mesma suíte leva ~11 minutos, e não é por teste lento: medida app a app,
ela soma ~3,7 minutos. O excesso vem da limpeza do banco entre os testes de tela (`TransactionTestCase`), que
percorre todas as tabelas e fica mais cara a cada app novo. Em paralelo, cada processo tem o seu banco.

⚠️ **Não rode a suíte contra o Neon do plano gratuito.** Ele suspende o banco por inatividade — e
suspendeu duas vezes no meio de execuções em andamento, derrubando todas as conexões. No plano
gratuito isso não se desliga. O banco de desenvolvimento pode continuar no Neon; os testes, não.

E, mesmo aceitando a lentidão, **`--parallel` não funciona contra o Neon**: ele precisa clonar o banco de
teste (`CREATE DATABASE ... TEMPLATE`), e o Neon responde *"is being accessed by other users"* mesmo com
`pg_stat_activity` vazio — a sessão que segura o banco é dele, e não aparece. Sem máquina com PostgreSQL à
mão, a saída é paralelizar por fora: várias execuções em série ao mesmo tempo, cada uma com o seu banco
(`DATABASES["default"]["TEST"] = {"NAME": ...}`) e um conjunto de apps. Foi assim que a Rodada 42 rodou —
em ~35 minutos, contra 1,7 min num PostgreSQL local.

O papel dono do teste precisa de `BYPASSRLS`, como o papel dono do Neon — sem ele, o
`FORCE ROW LEVEL SECURITY` barra até a preparação dos dados de teste:

```sql
CREATE ROLE hamilton_owner LOGIN PASSWORD 'ownerpass' CREATEDB CREATEROLE BYPASSRLS;
```

No Windows sem Docker, os [binários oficiais do PostgreSQL](https://www.enterprisedb.com/download-postgresql-binaries)
em `.zip` funcionam sem instalador e sem serviço: `initdb`, `pg_ctl start`, e a `DATABASE_URL` da
suíte apontando para `127.0.0.1`.

Vale saber o que a suíte cobre, porque não é o usual: 21 desses testes existem para **tentar
atravessar** o isolamento — por SQL cru, por `RESET ROLE`, por id alheio na URL, por injeção de
`psicologo` no POST. Eles passam quando a tentativa **falha**.

## Antes de fazer deploy

```bash
python manage.py check --deploy
```

Não é formalidade. `core/checks.py` reprova o arranque se a `DATABASE_URL` apontar para um
papel com `BYPASSRLS` — o erro que não está no código, está no ambiente, e que nenhum teste
de repositório pega. Este comando pertence ao script de build.
