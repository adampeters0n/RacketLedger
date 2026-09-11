"""Django system checks pro produkční deploy."""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Warning, register


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
