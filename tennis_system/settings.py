"""
Django settings for tennis_system project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# =====================================
# ZÁKLAD
# =====================================
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")  # načti .env, pokud existuje

# Certifikáty (řeší některé problémy s SSL na macOS)
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass

# -------------------------------------
# Režimy: DEV vs PROD (řídí se env proměnnými)
# -------------------------------------
def _get_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")

# SECRET_KEY – v produkci nastav v env!
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    os.getenv("SECRET_KEY", "dev-insecure-please-set-DJANGO_SECRET_KEY"),
)

# DEBUG z env (výchozí True pro lokální vývoj)
DEBUG = _get_bool("DEBUG", True)

# Povolené hosty (z env, čárkami oddělené). Pro vývoj přidej localhost.
_default_hosts = ["127.0.0.1", "localhost"]
ALLOWED_HOSTS = [h for h in os.getenv("ALLOWED_HOSTS", ",".join(_default_hosts)).split(",") if h]

# ✅ PATCH: Přidání vaší vlastní domény
# Přidáme domény, ať už jsou v env nebo ne.
ALLOWED_HOSTS.extend([
    "tscimice.cz",
    "www.tscimice.cz",
])

# CSRF důvěryhodné originy (z env, čárkami oddělené; musí mít https:// prefixy)
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# ✅ PATCH: Přidání vlastní domény pro CSRF (nutné pro přihlášení v adminu)
CSRF_TRUSTED_ORIGINS.extend([
    "https://tscimice.cz",
    "https://www.tscimice.cz",
])

# =====================================
# APLIKACE
# =====================================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # 3rd-party
    "rest_framework",

    # Lokální appky
    "core",
    "web",
]

# =====================================
# MIDDLEWARE
# =====================================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise musí být hned po SecurityMiddleware
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "tennis_system.urls"

# =====================================
# ŠABLONY
# =====================================
import django as _django
# S FORM_RENDERER = TemplatesSetting musí loader vidět i vestavěné šablony formulářů (errorlist atd.)
_DJANGO_FORMS_TEMPLATES = Path(_django.__file__).parent / "forms" / "templates"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates", _DJANGO_FORMS_TEMPLATES],
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

# Formulářové widgety načítají šablony přes projektové TEMPLATES (DIRS + APP_DIRS).
# Bez tohoto by se hledalo jen v django/forms/templates a app templates, bez projektového DIRS.
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

WSGI_APPLICATION = "tennis_system.wsgi.application"

# =====================================
# DATABÁZE
#  - v produkci použij DATABASE_URL (Postgres, SSL)
#  - lokálně fallback na SQLite (bez SSL)
# =====================================
import dj_database_url

if os.environ.get("DATABASE_URL"):
    DATABASES = {
        "default": dj_database_url.config(
            conn_max_age=600,
            conn_health_checks=True,
            ssl_require=True,   # jen pro Postgres
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# =====================================
# HESLA
# =====================================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =====================================
# LOKALIZACE
# =====================================
LANGUAGE_CODE = "cs"
TIME_ZONE = "Europe/Prague"
USE_I18N = True
USE_TZ = True

# =====================================
# STATIKA & MÉDIA
# =====================================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"          # kam se sbírá produkční statika
STATICFILES_DIRS = [BASE_DIR / "static"]        # tvé zdrojové statické soubory (pokud složka existuje)

# ✅ PATCH: cesty pro budoucí uploady médií
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Django 5+: STORAGES – WhiteNoise s manifestem v produkci
if not DEBUG:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# =====================================
# REST FRAMEWORK (můžeš doplnit dle potřeby)
# =====================================
REST_FRAMEWORK = {
    # "DEFAULT_AUTHENTICATION_CLASSES": [...],
    # "DEFAULT_PERMISSION_CLASSES": [...],
}

# =====================================
# E-MAIL (SMTP volny.cz) – výchozí 465/SSL
# =====================================
USE_SMTP = (not DEBUG) or (_get_bool("EMAIL_FORCE_SMTP", False))

if USE_SMTP:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.volny.cz")

    # Výchozí režim: SSL (465). TLS vypnuté.
    EMAIL_USE_SSL = _get_bool("EMAIL_USE_SSL", True)
    EMAIL_USE_TLS = _get_bool("EMAIL_USE_TLS", False)

    # Pokud by někdo v env zapnul oboje, vynutíme SSL a TLS vypneme.
    if EMAIL_USE_SSL and EMAIL_USE_TLS:
        EMAIL_USE_TLS = False

    # Port z env, jinak 465 pro SSL nebo 587 pro TLS
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "465" if EMAIL_USE_SSL else "587"))

    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "kptenis@volny.cz")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "30"))

    DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Tenis Čimice <kptenis@volny.cz>")
    SERVER_EMAIL = os.getenv("SERVER_EMAIL", "kptenis@volny.cz")
    EMAIL_SUBJECT_PREFIX = os.getenv("EMAIL_SUBJECT_PREFIX", "[Tenis Čimice] ")
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    DEFAULT_FROM_EMAIL = "Tenis Čimice <kptenis@volny.cz>"
    SERVER_EMAIL = "kptenis@volny.cz"
    EMAIL_SUBJECT_PREFIX = "[Tenis Čimice] "


# =====================================
# PRODUKČNÍ BEZPEČNOST (když DEBUG=False)
# =====================================
# ✅ PATCH: za reverzní proxy používej host z X-Forwarded-Host
USE_X_FORWARDED_HOST = True

if not DEBUG:
    # za reverzní proxy (Render/Railway) – důležité pro správné schéma https
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # přesměrování na HTTPS
    SECURE_SSL_REDIRECT = _get_bool("SECURE_SSL_REDIRECT", True)

    # secure cookies
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # HSTS (lze upravit přes env)
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))  # 1 rok
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _get_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = _get_bool("SECURE_HSTS_PRELOAD", True)

# =====================================
# LOGGING (stručný základ, ať vidíš chyby v produkci)
# =====================================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO" if not DEBUG else "DEBUG",
    },
}