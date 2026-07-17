"""Middleware pro aktivaci jazyka podle nastavení systému."""

from django.conf import settings
from django.utils import translation


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
    Vždy aktivuje výchozí jazyk z SystemNastaveni.
    Nastavení systému má přednost před cookie prohlížeče.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            from .models import SystemNastaveni

            lang = SystemNastaveni.load().vychozi_jazyk
            if lang and lang in dict(settings.LANGUAGES):
                translation.activate(lang)
                request.LANGUAGE_CODE = lang
        except Exception:
            pass

        response = self.get_response(request)
        return response
