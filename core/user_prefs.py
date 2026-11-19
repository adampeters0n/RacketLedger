"""Osobní preference uživatele (jazyk, tabulky, výchozí trénink)."""

from __future__ import annotations

from django.conf import settings

from .i18n_config import DEFAULT_LANGUAGE, SYSTEM_LANGUAGE_CODES
from .models import SystemNastaveni, UzivatelskyVzhled


def resolve_language_for_user(user, nastaveni: SystemNastaveni | None = None) -> str:
    """Jazyk rozhraní: osobní → klub → default."""
    if user is not None and getattr(user, "is_authenticated", False):
        try:
            prefs = user.vzhled
            if prefs.jazyk and prefs.jazyk in dict(settings.LANGUAGES):
                return prefs.jazyk
        except Exception:
            pass
    if nastaveni is None:
        try:
            nastaveni = SystemNastaveni.load()
        except Exception:
            nastaveni = None
    if nastaveni and nastaveni.vychozi_jazyk and nastaveni.vychozi_jazyk in dict(settings.LANGUAGES):
        return nastaveni.vychozi_jazyk
    return DEFAULT_LANGUAGE


def save_user_obecne_prefs(user, data, *, nastaveni: SystemNastaveni | None = None) -> UzivatelskyVzhled:
    """Uloží osobní pole z panelu Obecné (správce/trenér)."""
    prefs = UzivatelskyVzhled.for_user(user, nastaveni=nastaveni)

    lang = str(data.get("vychozi_jazyk") or "").strip()
    if lang in SYSTEM_LANGUAGE_CODES:
        prefs.jazyk = lang

    radku_raw = data.get("radku_na_stranku")
    if radku_raw in (None, ""):
        prefs.radku_na_stranku = None
    else:
        try:
            radku = int(radku_raw)
            if radku in {c[0] for c in UzivatelskyVzhled.RADKU_CHOICES}:
                prefs.radku_na_stranku = radku
        except (TypeError, ValueError):
            pass

    delka_raw = data.get("vychozi_delka_minut")
    if delka_raw in (None, ""):
        prefs.vychozi_delka_minut = None
    else:
        try:
            delka = int(delka_raw)
            if delka in {c[0] for c in SystemNastaveni.DELKA_MINUT_CHOICES}:
                prefs.vychozi_delka_minut = delka
        except (TypeError, ValueError):
            pass

    kurt = str(data.get("vychozi_kurt") or "").strip()
    valid_kurty = {c[0] for c in SystemNastaveni._meta.get_field("vychozi_kurt").choices}
    if kurt in valid_kurty:
        prefs.vychozi_kurt = kurt
    elif kurt == "":
        prefs.vychozi_kurt = ""

    prefs.save()
    return prefs
