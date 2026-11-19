"""Django system checks pro produkční deploy."""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Warning, register

_INSECURE_SECRET_MARKERS = (
    "dev-insecure",
    "django-insecure",
    "insecure",
    "please-set",
    "change-me",
    "changeme",
)


@register()
def check_production_hosts(app_configs, **kwargs):
    """V produkci (DEBUG=False) vyžaduj reálné ALLOWED_HOSTS a CSRF originy."""
    if settings.DEBUG:
        return []

    errors: list = []
    hosts = [h.strip() for h in (settings.ALLOWED_HOSTS or []) if h and h.strip()]
    if not hosts:
        errors.append(
            Error(
                "ALLOWED_HOSTS is empty while DEBUG=False.",
                hint=(
                    "Set ALLOWED_HOSTS (and optionally EXTRA_ALLOWED_HOSTS) "
                    "to the instance domain, e.g. klub.example.com"
                ),
                id="core.E001",
            )
        )
    elif hosts == ["*"]:
        errors.append(
            Error(
                "ALLOWED_HOSTS=['*'] is not safe in production.",
                hint="List concrete hostnames for this club instance.",
                id="core.E002",
            )
        )

    origins = [o.strip() for o in (settings.CSRF_TRUSTED_ORIGINS or []) if o and o.strip()]
    if not origins:
        errors.append(
            Warning(
                "CSRF_TRUSTED_ORIGINS is empty while DEBUG=False.",
                hint=(
                    "Set CSRF_TRUSTED_ORIGINS / EXTRA_CSRF_TRUSTED_ORIGINS "
                    "with https:// prefix, e.g. https://klub.example.com"
                ),
                id="core.W001",
            )
        )
    else:
        bad = [o for o in origins if not o.startswith(("https://", "http://"))]
        if bad:
            errors.append(
                Error(
                    "CSRF_TRUSTED_ORIGINS entries must include scheme (https://…).",
                    hint=f"Invalid: {', '.join(bad[:3])}",
                    id="core.E003",
                )
            )

    return errors


@register()
def check_production_secret(app_configs, **kwargs):
    """V produkci odmítni výchozí / zjevně insecure SECRET_KEY."""
    if settings.DEBUG:
        return []

    key = (settings.SECRET_KEY or "").strip()
    low = key.casefold()
    insecure = (not key) or len(key) < 32 or any(m in low for m in _INSECURE_SECRET_MARKERS)
    if not insecure:
        return []

    return [
        Error(
            "SECRET_KEY looks insecure while DEBUG=False.",
            hint=(
                "Set DJANGO_SECRET_KEY (or SECRET_KEY) to a long random value. "
                "Do not use the development default."
            ),
            id="core.E004",
        )
    ]


@register()
def check_production_email(app_configs, **kwargs):
    """V produkci varuj, když SMTP není nakonfigurované (reset hesla / vyúčtování)."""
    if settings.DEBUG:
        return []

    host = (getattr(settings, "EMAIL_HOST", "") or "").strip()
    user = (getattr(settings, "EMAIL_HOST_USER", "") or "").strip()
    if host and user:
        return []

    return [
        Warning(
            "SMTP is not fully configured while DEBUG=False.",
            hint=(
                "Set EMAIL_HOST and EMAIL_HOST_USER (and EMAIL_HOST_PASSWORD). "
                "Password reset and billing e-mails will fail without SMTP."
            ),
            id="core.W002",
        )
    ]


@register()
def check_production_storage(app_configs, **kwargs):
    """V produkci varuj, když média nejsou na object storage (S3/R2)."""
    if settings.DEBUG:
        return []

    if getattr(settings, "USE_S3", False):
        bucket = (getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or "").strip()
        key_id = (getattr(settings, "AWS_ACCESS_KEY_ID", "") or "").strip()
        if bucket and key_id:
            return []
        missing = []
        if not bucket:
            missing.append("AWS_STORAGE_BUCKET_NAME")
        if not key_id:
            missing.append("AWS_ACCESS_KEY_ID")
        return [
            Warning(
                "USE_S3=True but S3 credentials/bucket are incomplete.",
                hint=f"Set {', '.join(missing)} (and AWS_SECRET_ACCESS_KEY / endpoint).",
                id="core.W003",
            )
        ]

    return [
        Warning(
            "Media files use local disk while DEBUG=False (USE_S3 is off).",
            hint=(
                "Set USE_S3=1 and S3/R2 credentials so logo/favicon survive "
                "ephemeral filesystems. Local MEDIA_ROOT is fine only with persistent disk."
            ),
            id="core.W003",
        )
    ]
