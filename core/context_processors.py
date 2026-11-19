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
    resolve_appearance_for_user,
)


def system_nastaveni(request):
    """Název klubu, režim a CSS proměnné pro všechny stránky."""
    nast = None
    nazev = getattr(settings, "PRODUCT_NAME", "TenisSystém")
    colors = preset_colors(DEFAULT_THEME, dark=False)
    slogan = ""
    logo_url = ""
    favicon_url = ""
    variant = DEFAULT_THEME
    tmavy = False

    try:
        nast = SystemNastaveni.load()
        nazev = nast.nazev_klubu or nazev
        slogan = nast.slogan or ""
        if nast.logo:
            logo_url = nast.logo.url
        if nast.favicon:
            favicon_url = nast.favicon.url
    except Exception:
        pass

    user = getattr(request, "user", None)
    variant, tmavy, colors = resolve_appearance_for_user(user, nast)

    if variant not in THEME_VARIANTS:
        variant = DEFAULT_THEME

    jazyk = DEFAULT_LANGUAGE
    try:
        from .user_prefs import resolve_language_for_user

        jazyk = resolve_language_for_user(user, nast)
    except Exception:
        if nast and getattr(nast, "vychozi_jazyk", None):
            jazyk = nast.vychozi_jazyk

    nav = {}
    is_plat_admin = False
    try:
        from .roles import is_platform_admin, nav_permissions

        is_plat_admin = is_platform_admin(user)
        nav = nav_permissions(user)
    except Exception:
        pass

    
    billing_active_flag = True
    billing_read_only = False
    stripe_billing_configured = False
    stripe_checkout_configured_flag = False
    try:
        from core.billing import billing_active, stripe_checkout_configured, stripe_configured
        billing_active_flag = billing_active()
        billing_read_only = bool(getattr(request, "billing_read_only", False))
        stripe_billing_configured = stripe_configured()
        stripe_checkout_configured_flag = stripe_checkout_configured()
    except Exception:
        pass

    return {
        "billing_active": billing_active_flag,
        "billing_read_only": billing_read_only,
        "stripe_billing_configured": stripe_billing_configured,
        "stripe_checkout_configured": stripe_checkout_configured_flag,

        "system_nastaveni": nast,
        "system_theme_variant": variant,
        "system_nazev_klubu": nazev,
        "is_platform_admin": is_plat_admin,
        **nav,
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
