"""Middleware pro health check, jazyk systému a gate předplatného (BILLING_ACTIVE)."""

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _

HEALTHZ_PATHS = frozenset({"/healthz", "/healthz/"})


class HealthCheckMiddleware:
    """Okamžitá odpověď bez databáze, sessions i SSL redirectu.

    Na Renderu nastavte Health Check Path na ``/healthz``. Běžná stránka
    (``/`` nebo ``/admin/``) by při minutových kontrolách nenechala Neon usnout.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in HEALTHZ_PATHS:
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)


def set_language_cookie(response, lang_code: str):
    """Nastaví Django language cookie (Django 5.2+ používá cookie místo session)."""
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        lang_code,
        max_age=settings.LANGUAGE_COOKIE_AGE,
        path=settings.LANGUAGE_COOKIE_PATH,
        domain=settings.LANGUAGE_COOKIE_DOMAIN,
        secure=settings.LANGUAGE_COOKIE_SECURE,
        httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
    )
    return response


class SystemLanguageMiddleware:
    """
    Aktivuje jazyk: osobní preference uživatele → SystemNastaveni → default.
    Má přednost před cookie prohlížeče.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in HEALTHZ_PATHS:
            return self.get_response(request)

        try:
            from .models import SystemNastaveni
            from .user_prefs import resolve_language_for_user

            nast = SystemNastaveni.load()
            lang = resolve_language_for_user(getattr(request, "user", None), nast)
            if lang and lang in dict(settings.LANGUAGES):
                translation.activate(lang)
                request.LANGUAGE_CODE = lang
        except Exception:
            pass

        response = self.get_response(request)
        return response


_BILLING_ALLOW_PREFIXES = (
    "/healthz",
    "/health/",
    "/privacy/",
    "/terms/",
    "/static/",
    "/media/",
    "/i18n/",
    "/jsi18n/",
    "/logout/",
    "/stripe/webhook/",
    "/admin/login/",
    "/admin/logout/",
    "/admin/password_reset/",
    "/admin/password_change/",
    "/admin/reset/",
)


class BillingGateMiddleware:
    """Read-only gate podle billing_active() (Stripe status / BILLING_ACTIVE).

    Checkout, Customer Portal a webhook zůstávají dostupné i při suspendu.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core.billing import billing_active
        from core.roles import is_platform_admin

        request.billing_read_only = False

        if billing_active():
            return self.get_response(request)

        path = request.path or "/"
        if any(path.startswith(prefix) for prefix in _BILLING_ALLOW_PREFIXES):
            return self.get_response(request)
        if "/nastaveni/billing-portal" in path:
            return self.get_response(request)
        if "/nastaveni/billing-checkout" in path:
            return self.get_response(request)

        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False) and is_platform_admin(user):
            return self.get_response(request)

        if request.method in ("GET", "HEAD", "OPTIONS"):
            request.billing_read_only = True
            return self.get_response(request)

        if user is not None and getattr(user, "is_authenticated", False):
            messages.error(
                request,
                _(
                    "Předplatné TenisSystému není aktivní. "
                    "Úpravy jsou dočasně vypnuté — obnovte platbu v Nastavení → Předplatné."
                ),
            )
            try:
                return redirect(f"{reverse('admin:nastaveni')}#predplatne")
            except Exception:
                return redirect("/admin/nastaveni/")

        return redirect("/admin/login/")
