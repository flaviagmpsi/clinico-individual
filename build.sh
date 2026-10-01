#!/usr/bin/env bash
# Build do Render (ADR-114). `set -e`: qualquer passo que falhe derruba o deploy em vez de subir pela metade.
set -o errexit

pip install -r requirements.txt

# Os estáticos são servidos pelo whitenoise, que exige o manifesto gerado aqui.
python manage.py collectstatic --no-input

# As migrações rodam com o papel **dono**, que é o único que pode alterar tabela e criar policy. É também o único
# com BYPASSRLS — por isso ele vive numa variável separada e nunca na DATABASE_URL da aplicação (ADR-046).
DATABASE_URL="${DATABASE_URL_MIGRACAO:-$DATABASE_URL}" python manage.py migrate --no-input

# O portão da ADR-046, rodado **com a URL da aplicação**: se ela tiver BYPASSRLS, o RLS é decorativo e o deploy
# para aqui. É verificação de ambiente, e nenhum teste de repositório a substitui.
python manage.py check --deploy --fail-level ERROR
