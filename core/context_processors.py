"""Globální proměnné pro šablony."""

from django.conf import settings

from .i18n_config import DEFAULT_LANGUAGE, SYSTEM_LANGUAGES
from .js_i18n import get_global_js_i18n
from .models import SystemNastaveni
from .system_theme import (
    DEFAULT_THEME,
    THEME_VARIANTS,
    css_vars_dict,
    css_vars_style_block,
    preset_colors,
    resolve_theme_colors,
)


def system_nastaveni(request):
    """Název klubu, režim a CSS proměnné pro všechny stránky."""
    nast = None
    variant = DEFAULT_THEME
    nazev = getattr(settings, "PRODUCT_NAME", "TenisSystém")
    tmavy = False
    colors = preset_colors(DEFAULT_THEME, dark=False)
    slogan = ""
    logo_url = ""
    favicon_url = ""

    try:
        nast = SystemNastaveni.load()
        variant = nast.barevna_varianta or DEFAULT_THEME
        nazev = nast.nazev_klubu or nazev
        tmavy = bool(nast.tmavy_rezim)
        colors = resolve_theme_colors(nast)
        slogan = nast.slogan or ""
        if nast.logo:
            logo_url = nast.logo.url
        if nast.favicon:
            favicon_url = nast.favicon.url
    except Exception:
        pass

    if variant not in THEME_VARIANTS:
        variant = DEFAULT_THEME

    jazyk = DEFAULT_LANGUAGE
    if nast and getattr(nast, "vychozi_jazyk", None):
        jazyk = nast.vychozi_jazyk

    return {
        "system_nastaveni": nast,
        "system_theme_variant": variant,
        "system_nazev_klubu": nazev,
        "system_slogan": slogan,
        "system_logo_url": logo_url,
        "system_favicon_url": favicon_url,
        "system_kontakt_email": getattr(nast, "kontakt_email", "") if nast else "",
        "system_kontakt_telefon": getattr(nast, "kontakt_telefon", "") if nast else "",
        "system_kontakt_adresa": getattr(nast, "kontakt_adresa", "") if nast else "",
        "system_tmavy_rezim": tmavy,
        "system_jazyk": jazyk,
        "system_jazyky": SYSTEM_LANGUAGES,
        "LANGUAGES": settings.LANGUAGES,
        "system_theme_colors": colors,
        "system_theme_css_vars": css_vars_dict(colors),
        "system_theme_style": css_vars_style_block(colors, dark=tmavy),
        "system_theme_state": {
            "palette": variant,
            "mode": "dark" if tmavy else "light",
            "colors": colors,
        },
        "ts_global_i18n": get_global_js_i18n(),
    }
