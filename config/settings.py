import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.getenv("DEBUG", "False") == "True"

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    # Sem o `raise`, uma variável de ambiente esquecida no Render subia a aplicação com uma
    # chave que está no repositório — e quem conhece a chave assina cookie de sessão e token
    # de recuperação de senha de qualquer psicólogo. Falhar no arranque é barulhento; o padrão
    # inseguro era silencioso.
    if not DEBUG:
        raise RuntimeError("SECRET_KEY não definida. A aplicação não sobe sem ela.")
    SECRET_KEY = "inseguro-apenas-para-desenvolvimento-nao-use-com-DEBUG=False"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "contas",
    "assinaturas",
    "pacientes",
    "agenda",
    "atendimentos",
    "financeiro",
    "indicadores",
    "prontuarios",
    "documentos",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Depois da autenticação, porque deriva o escopo do usuário autenticado.
    "core.middleware.EscopoDoPsicologoMiddleware",
    # Depois do escopo (lê a assinatura do psicólogo) e antes do quiz: escolher entre assinar e testar vem primeiro.
    "assinaturas.middleware.AssinaturaMiddleware",
    # Depois do escopo: o quiz de cadastro grava no próprio psicólogo, e a view precisa do papel certo.
    "contas.middleware.CadastroCompletoMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# O psicólogo é o usuário e é a raiz do isolamento — a mesma entidade nos dois papéis.
AUTH_USER_MODEL = "contas.Psicologo"
TENANT_MODEL = "contas.Psicologo"

DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv("DATABASE_URL", ""),
        conn_max_age=600,
        ssl_require=not DEBUG,
    )
}

# ⚠️ A `DATABASE_URL` da aplicação aponta para `hamilton_web`, que **não** tem BYPASSRLS.
# O papel dono fica reservado às migrações, numa URL separada. `core/checks.py` recusa o
# arranque se esta regra for violada com DEBUG=False. Ver ADR-001 e ADR-046.

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Assinatura (ADR-094) -----------------------------------------------------------------------
# Enquanto a integração com o Asaas não existe (S-01), o pagamento é simulado. Nasce de `DEBUG` de propósito:
# não há `.env` que ligue em produção um botão que ativa a assinatura sem cobrar.
ASSINATURA_SIMULADA = DEBUG
# O preço é decisão de negócio ainda em aberto (P-91). Vazio, a tela não inventa valor nenhum.
ASSINATURA_VALOR_MENSAL = os.getenv("ASSINATURA_VALOR_MENSAL") or None

LOGIN_URL = "contas:entrar"
LOGIN_REDIRECT_URL = "painel"
LOGOUT_REDIRECT_URL = "contas:entrar"

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
