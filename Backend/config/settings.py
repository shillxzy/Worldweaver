"""Django settings for Worldweaver.

All environment-specific values come from environment variables (optionally loaded
from Backend/.env). Nothing secret is stored in this file.
"""
from pathlib import Path
import os

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # python-dotenv is optional
    pass


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        # Development-only key; never used when DEBUG is off.
        SECRET_KEY = "dev-insecure-key-change-me"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    "apps.common",
    "apps.accounts",
    "apps.worlds",
    "apps.books",
    "apps.boards",
    "apps.analysis",
    "apps.ai",
    "apps.language",
    "apps.pages",
    "apps.collab",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "config.wsgi.application"

# --- Database -------------------------------------------------------------
# PostgreSQL is the target database. SQLite is allowed for quick local tests.
DB_ENGINE = env("DB_ENGINE", "postgres").lower()
if DB_ENGINE in {"postgres", "postgresql"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", "worldweaver"),
            "USER": env("DB_USER", "worldweaver"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "127.0.0.1"),
            "PORT": env("DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
elif DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / env("SQLITE_NAME", "db.sqlite3"),
            "OPTIONS": {"timeout": 20},
        }
    }
else:
    raise ImproperlyConfigured("DB_ENGINE must be 'postgres' or 'sqlite'.")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "uk"
TIME_ZONE = env("TIME_ZONE", "Europe/Kyiv")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded files are private: they are NOT served from MEDIA_URL.
# Access goes through authenticated API views only.
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "private_media")))
MEDIA_URL = "/private-media-not-served/"

DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# --- Security -------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # the SPA reads the token to send X-CSRFToken
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
CORS_ALLOW_CREDENTIALS = True

# --- DRF ------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {"auth": "20/min", "public": "120/min"},
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Worldweaver API",
    "DESCRIPTION": "Локальний API для письменницького простору Worldweaver.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "PrecisionEnum": "apps.worlds.models.Precision",
        "CharacterStatusEnum": "apps.worlds.models.Character.Status",
        "BookStatusEnum": "apps.books.models.Book.Status",
        "ChapterStatusEnum": "apps.books.models.Chapter.Status",
        "JobStatusEnum": "apps.analysis.models.AnalysisJob.Status",
    },
}

# --- Worldweaver specific -------------------------------------------------
WW_MAX_DOCUMENT_BYTES = int(env("WW_MAX_DOCUMENT_BYTES", str(2 * 1024 * 1024)))
WW_MAX_DOCX_BYTES = int(env("WW_MAX_DOCX_BYTES", str(10 * 1024 * 1024)))
WW_MAX_DOCX_UNCOMPRESSED_BYTES = int(env("WW_MAX_DOCX_UNCOMPRESSED_BYTES", str(60 * 1024 * 1024)))
WW_MAX_PORTRAIT_BYTES = int(env("WW_MAX_PORTRAIT_BYTES", str(3 * 1024 * 1024)))
WW_MAX_ANALYSIS_CHARS = int(env("WW_MAX_ANALYSIS_CHARS", str(2_000_000)))
WW_VERSION_INTERVAL_SECONDS = int(env("WW_VERSION_INTERVAL_SECONDS", "300"))
WW_MAX_VERSIONS_PER_CHAPTER = int(env("WW_MAX_VERSIONS_PER_CHAPTER", "50"))

# Local AI (Ollama). Only loopback hosts are accepted unless listed explicitly.
OLLAMA_URL = env("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = env("OLLAMA_MODEL", "qwen2.5:7b-instruct")
OLLAMA_ALLOWED_HOSTS = env_list("OLLAMA_ALLOWED_HOSTS", "")
OLLAMA_TIMEOUT_SECONDS = int(env("OLLAMA_TIMEOUT_SECONDS", "180"))
OLLAMA_NUM_CTX = int(env("OLLAMA_NUM_CTX", "8192"))
AI_MAX_CONCURRENT_JOBS = int(env("AI_MAX_CONCURRENT_JOBS", "1"))
AI_CHUNK_CHARS = int(env("AI_CHUNK_CHARS", "3500"))
AI_CHUNK_OVERLAP = int(env("AI_CHUNK_OVERLAP", "300"))
AI_MAX_LORE_CONTEXT_CHARS = int(env("AI_MAX_LORE_CONTEXT_CHARS", "4000"))

WORKER_POLL_SECONDS = float(env("WORKER_POLL_SECONDS", "2"))
WORKER_STALE_SECONDS = int(env("WORKER_STALE_SECONDS", "300"))
WORKER_MAX_ATTEMPTS = int(env("WORKER_MAX_ATTEMPTS", "3"))

SPELL_DICT_DIR = Path(env("SPELL_DICT_DIR", str(BASE_DIR / "dictionaries")))

# Logging: manuscript text must never be logged. Loggers below only receive ids/statuses.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}
