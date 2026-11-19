"""
Django settings for tennis_system project.
"""

from pathlib import Path
import json
import os
import socket
import sys
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

# Při `manage.py test` nespouštěj produkční deploy checky jako fatal
# (testy je volají přímo s override_settings).
if len(sys.argv) > 1 and sys.argv[1] == "test":
    SILENCED_SYSTEM_CHECKS = [
        "core.E001",
        "core.E002",
        "core.E003",
        "core.E004",
        "core.W001",
        "core.W002",
        "core.W003",
    ]

# Povolené hosty (z env, čárkami oddělené). Pro vývoj přidej localhost.
_default_hosts = ["127.0.0.1", "localhost"]
ALLOWED_HOSTS = [h for h in os.getenv("ALLOWED_HOSTS", ",".join(_default_hosts)).split(",") if h]

# Další domény (doplňuje ALLOWED_HOSTS) – default prázdný; instance si doplní v .env.
ALLOWED_HOSTS.extend([
    h for h in os.getenv("EXTRA_ALLOWED_HOSTS", "").split(",") if h
])

# CSRF důvěryhodné originy (z env, čárkami oddělené; musí mít https:// prefixy)
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# Další CSRF originy (doplňuje CSRF_TRUSTED_ORIGINS) – default prázdný.
CSRF_TRUSTED_ORIGINS.extend([
    o for o in os.getenv("EXTRA_CSRF_TRUSTED_ORIGINS", "").split(",") if o
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

    # Lokální appky
    "core.apps.CoreConfig",
    "axes",
]

# =====================================
# MIDDLEWARE
# =====================================
MIDDLEWARE = [
    # Před SecurityMiddleware – /healthz bez DB, sessions i SSL redirectu
    "core.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise musí být hned po SecurityMiddleware
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "core.middleware.SystemLanguageMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "axes.middleware.AxesMiddleware",
    "core.middleware.BillingGateMiddleware",
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
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.system_nastaveni",
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
            # Lokální Docker Postgres typicky bez SSL; produkce: DATABASE_SSL_REQUIRE=1
            ssl_require=_get_bool("DATABASE_SSL_REQUIRE", False),
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

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "core.auth_backends.EmailOrUsernameModelBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Rate-limit přihlášení / brute-force (django-axes)
AXES_ENABLED = _get_bool("AXES_ENABLED", True)
AXES_FAILURE_LIMIT = int(os.getenv("AXES_FAILURE_LIMIT", "5"))
AXES_COOLOFF_TIME = float(os.getenv("AXES_COOLOFF_TIME", "1"))  # hodiny
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_USERNAME_FORM_FIELD = "username"
# Sleduj i password reset POST (stejný username/email field „email“ — Axes default login only).
# Login admin form field = username (email-or-username).

# =====================================
# LOKALIZACE
# =====================================
from core.i18n_config import DEFAULT_LANGUAGE, SYSTEM_LANGUAGES  # noqa: E402

LANGUAGE_CODE = DEFAULT_LANGUAGE
LANGUAGES = SYSTEM_LANGUAGES
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Prague"
USE_I18N = True
USE_L10N = True
USE_TZ = True

# =====================================
# STATIKA & MÉDIA
# =====================================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"          # kam se sbírá produkční statika
STATICFILES_DIRS = [BASE_DIR / "static"]        # tvé zdrojové statické soubory (pokud složka existuje)

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# S3 / R2 / MinIO pro uploady (logo, favicon) — doporučeno při DEBUG=False
USE_S3 = _get_bool("USE_S3", False)
if USE_S3:
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME", "")
    AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "") or None
    AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL", "") or None
    AWS_S3_CUSTOM_DOMAIN = os.getenv("AWS_S3_CUSTOM_DOMAIN", "") or None
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = _get_bool("AWS_QUERYSTRING_AUTH", False)
    AWS_S3_FILE_OVERWRITE = False
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}

_default_storage = (
    {"BACKEND": "storages.backends.s3.S3Storage"}
    if USE_S3
    else {"BACKEND": "django.core.files.storage.FileSystemStorage"}
)
_static_storage = (
    {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}
    if not DEBUG
    else {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
)
STORAGES = {
    "default": _default_storage,
    "staticfiles": _static_storage,
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# =====================================
# INSTANCE / OBSERVABILITY
# =====================================
INSTANCE_NAME = (os.getenv("INSTANCE_NAME") or "").strip() or socket.gethostname()

# =====================================
# SENTRY (volitelné)
# =====================================
SENTRY_DSN = (os.getenv("SENTRY_DSN") or "").strip()
if SENTRY_DSN:
    import sentry_sdk

    try:
        _sentry_traces = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0") or "0.0")
    except ValueError:
        _sentry_traces = 0.0

    _sentry_release = (
        (os.getenv("SENTRY_RELEASE") or "").strip()
        or (os.getenv("GIT_COMMIT") or "").strip()
        or (os.getenv("RENDER_GIT_COMMIT") or "").strip()
        or (os.getenv("SOURCE_VERSION") or "").strip()  # Heroku
        or None
    )

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=False,
        traces_sample_rate=max(0.0, min(1.0, _sentry_traces)),
        environment=os.getenv("SENTRY_ENVIRONMENT", "production" if not DEBUG else "development"),
        release=_sentry_release,
        server_name=INSTANCE_NAME,
    )
    sentry_sdk.set_tag("instance", INSTANCE_NAME)

# =====================================
# E-MAIL (SMTP) – výchozí 465/SSL
# =====================================
USE_SMTP = (not DEBUG) or (_get_bool("EMAIL_FORCE_SMTP", False))

if USE_SMTP:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.getenv("EMAIL_HOST", "")

    # Výchozí režim: SSL (465). TLS vypnuté.
    EMAIL_USE_SSL = _get_bool("EMAIL_USE_SSL", True)
    EMAIL_USE_TLS = _get_bool("EMAIL_USE_TLS", False)

    # Pokud by někdo v env zapnul oboje, vynutíme SSL a TLS vypneme.
    if EMAIL_USE_SSL and EMAIL_USE_TLS:
        EMAIL_USE_TLS = False

    # Port z env, jinak 465 pro SSL nebo 587 pro TLS
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "465" if EMAIL_USE_SSL else "587"))

    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "30"))

    DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "TenisSystém <noreply@tenissystem.cz>")
    SERVER_EMAIL = os.getenv("SERVER_EMAIL", "noreply@tenissystem.cz")
    EMAIL_SUBJECT_PREFIX = os.getenv("EMAIL_SUBJECT_PREFIX", "[TenisSystém] ")
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    DEFAULT_FROM_EMAIL = "TenisSystém <noreply@tenissystem.cz>"
    SERVER_EMAIL = "noreply@tenissystem.cz"
    EMAIL_SUBJECT_PREFIX = "[TenisSystém] "

# Automatické vyúčtování – po naúčtování tréninku, když dluh od poslední uzávěrky
# dosáhne této částky (Kč), systém vytvoří vyúčtování a pošle e-mail.
VYUCTOVANI_AUTO_LIMIT = os.getenv("VYUCTOVANI_AUTO_LIMIT", "5000")
VYUCTOVANI_EMAIL_VARIANT = os.getenv("VYUCTOVANI_EMAIL_VARIANT", "1")


# =====================================
# PRODUKČNÍ BEZPEČNOST (když DEBUG=False)
# =====================================
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
# LANDING PAGE – registr škol na platformě
# =====================================
PRODUCT_NAME = os.getenv("PRODUCT_NAME", "TenisSystém")

# Prázdný default = landing sestaví jednu školu z SystemNastaveni (single-tenant).
# Multi-school adresář jen přes env TENNIS_SCHOOLS (JSON).
_DEFAULT_TENNIS_SCHOOLS: list = []


def _get_tennis_schools():
    raw = os.getenv("TENNIS_SCHOOLS", "").strip()
    if raw:
        return json.loads(raw)
    return list(_DEFAULT_TENNIS_SCHOOLS)


TENNIS_SCHOOLS = _get_tennis_schools()
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "info@tenissystem.cz")

# =====================================
# PŘEDPLATNÉ ZA SOFTWARE (Stripe) — 1 Customer ↔ 1 instance
# =====================================
BILLING_ACTIVE = _get_bool("BILLING_ACTIVE", True)
# Když True a Checkout je nastavený: bez aktivního předplatného je instance zamčená.
STRIPE_REQUIRE_SUBSCRIPTION = _get_bool("STRIPE_REQUIRE_SUBSCRIPTION", False)
STRIPE_SECRET_KEY = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
STRIPE_WEBHOOK_SECRET = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()
STRIPE_PRICE_ID = (os.getenv("STRIPE_PRICE_ID") or "").strip()
# Volitelný seed customer (starší ruční napojení); Checkout/webhook ukládá do DB.
STRIPE_CUSTOMER_ID = (os.getenv("STRIPE_CUSTOMER_ID") or "").strip()
# Online platby hráčů (Stripe Connect) — oddělené od SaaS předplatného
STRIPE_PLAYER_CURRENCY = (os.getenv("STRIPE_PLAYER_CURRENCY") or "czk").strip().lower()
STRIPE_CONNECT_COUNTRY = (os.getenv("STRIPE_CONNECT_COUNTRY") or "CZ").strip().upper()
# Jen sandbox: přeskočí Connect KYC a Checkout jde na platformní účet (bez destination).
STRIPE_CONNECT_TEST_BYPASS = (os.getenv("STRIPE_CONNECT_TEST_BYPASS") or "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Veřejná báze URL instance (Checkout success/cancel, odkazy v e-mailech)
PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")

# =====================================
# LOGGING (stručný základ + instance tag)
# =====================================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "instance_context": {
            "()": "core.logging_filters.InstanceContextFilter",
        },
    },
    "formatters": {
        "structured": {
            "format": "%(asctime)s %(levelname)s instance=%(instance)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["instance_context"],
            "formatter": "structured",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO" if not DEBUG else "DEBUG",
    },
}