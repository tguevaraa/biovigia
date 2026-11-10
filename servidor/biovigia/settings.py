"""Configuración del servidor de aplicación de BioVigIA (componente C2).

Todos los valores sensibles o que cambian por entorno se leen de variables de entorno
o de un archivo ``.env`` junto a ``manage.py`` (ver ``env.ejemplo``).
"""
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Seguridad -----------------------------------------------------------------------
SECRET_KEY = config(
    "DJANGO_SECRET_KEY",
    default="solo-desarrollo-cambiar-antes-de-desplegar-3f9a1c7e5b2d4a6f8e0c",
)
DEBUG = config("DJANGO_DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("DJANGO_CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# --- Aplicaciones ----------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "cuentas",
    "vigilancia",
    "tablero",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "biovigia.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "tablero.context_processors.navegacion",
            ],
        },
    },
]

WSGI_APPLICATION = "biovigia.wsgi.application"

# --- Base de datos ---------------------------------------------------------------------
# El MVP arranca con SQLite. Para pasar a PostgreSQL (BVIA-33) basta con definir
# POSTGRES_DB en el .env e instalar psycopg; no hay que tocar este archivo.
if config("POSTGRES_DB", default=""):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("POSTGRES_DB"),
            "USER": config("POSTGRES_USER", default="biovigia"),
            "PASSWORD": config("POSTGRES_PASSWORD", default=""),
            "HOST": config("POSTGRES_HOST", default="localhost"),
            "PORT": config("POSTGRES_PORT", default="5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "cuentas.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "tablero:login"
LOGIN_REDIRECT_URL = "tablero:inicio"
LOGOUT_REDIRECT_URL = "tablero:login"
SESSION_COOKIE_AGE = config("SESION_SEGUNDOS", default=8 * 3600, cast=int)

# --- Internacionalización (Ecuador) ----------------------------------------------------
LANGUAGE_CODE = "es-ec"
TIME_ZONE = "America/Guayaquil"
USE_I18N = True
USE_TZ = True

# --- Archivos ----------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# La evidencia NO se publica bajo MEDIA_URL: se sirve por una vista que controla el rol
# y deja constancia en la bitácora (RNF-14). Por eso no hay ruta /media/ en urls.py.
MEDIA_ROOT = Path(config("BIOVIGIA_MEDIA_ROOT", default=str(BASE_DIR / "media")))
EVIDENCIA_MAX_BYTES = 2 * 1024 * 1024  # contrato v1: máximo 2 MB
# Un JPEG de 2 MB ocupa ~2,7 MB en base64; el límite por defecto de Django (2,5 MB) no alcanza.
DATA_UPLOAD_MAX_MEMORY_SIZE = 4 * 1024 * 1024

# --- Django REST Framework -----------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # El token va primero para que la ausencia de credenciales responda 401 (contrato v1).
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "vigilancia.api.errores.manejador_de_errores",
    "UNAUTHENTICATED_USER": None,
}

# --- Reglas del dominio ----------------------------------------------------------------------
# Turnos: pendientes de confirmar con el cliente (contrato v1, sección 8).
# Formato: código, etiqueta, hora de inicio (incluida), hora de fin (excluida).
BIOVIGIA_TURNOS = [
    ("manana", "Mañana", 7, 13),
    ("tarde", "Tarde", 13, 19),
]
# Un latido del servicio de visión que llega hasta esta cantidad de segundos después del
# final del último tramo observado lo prolonga; por encima, se abre un tramo nuevo y el
# hueco queda como periodo no observado (RNF-06).
BIOVIGIA_TOLERANCIA_TRAMO_S = config("BIOVIGIA_TOLERANCIA_TRAMO_S", default=30, cast=int)
# Huecos más cortos que esto no se cuentan como periodo no observado.
BIOVIGIA_HUECO_MINIMO_S = config("BIOVIGIA_HUECO_MINIMO_S", default=60, cast=int)
# Si el último latido es más viejo que esto, el tablero avisa que no hay conexión con C1.
BIOVIGIA_LATIDO_VENCIDO_S = config("BIOVIGIA_LATIDO_VENCIDO_S", default=60, cast=int)
# Tolerancia ante relojes desfasados entre el borde y el servidor al validar ocurrido_en.
BIOVIGIA_DESFASE_RELOJ_S = config("BIOVIGIA_DESFASE_RELOJ_S", default=5, cast=int)
BIOVIGIA_FPS_MINIMO = 15  # RNF-09

# --- Seguridad en producción (RNF-18) ----------------------------------------------------------
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = config("DJANGO_SSL_REDIRECT", default=True, cast=bool)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 3600
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

# --- Registro de eventos de la aplicación -----------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "consola": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "loggers": {
        "biovigia": {"handlers": ["consola"], "level": "INFO", "propagate": False},
    },
}
