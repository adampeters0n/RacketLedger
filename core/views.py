# core/views.py
from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.urls import reverse, NoReverseMatch
from django.utils import timezone


def _admin_url(name: str) -> str:
    """Bezpečný reverse do adminu s fallbackem na /admin/."""
    try:
        return reverse(f"admin:{name}")
    except NoReverseMatch:
        return "/admin/"


def home(request):
    from .models import SystemNastaveni

    contact_email = settings.CONTACT_EMAIL
    contact_phone = ""
    contact_address = ""
    slogan = ""
    logo_url = ""
    favicon_url = ""
    product_name = settings.PRODUCT_NAME
    try:
        nast = SystemNastaveni.load()
        if nast.nazev_klubu:
            product_name = nast.nazev_klubu
        if nast.kontakt_email:
            contact_email = nast.kontakt_email
        contact_phone = nast.kontakt_telefon or ""
        contact_address = nast.kontakt_adresa or ""
        slogan = nast.slogan or ""
        if nast.logo:
            logo_url = nast.logo.url
        if nast.favicon:
            favicon_url = nast.favicon.url
    except Exception:
        pass

    schools = []
    for school in settings.TENNIS_SCHOOLS:
        admin_url = school.get("admin_url") or _admin_url("index")
        schools.append({**school, "admin_url": admin_url})

    active_schools = [s for s in schools if s.get("active", True)]
    upcoming_schools = [s for s in schools if not s.get("active", True)]

    ctx = {
        "product_name": product_name,
        "schools": schools,
        "active_schools": active_schools,
        "upcoming_schools": upcoming_schools,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "contact_address": contact_address,
        "slogan": slogan,
        "logo_url": logo_url,
        "favicon_url": favicon_url,
        "now": timezone.now(),
    }
    return render(request, "home/landing.html", ctx)


def logout_to_home(request):
    """Potvrzení odhlášení (GET), po odsouhlasení odhlásí a přesměruje na úvod."""
    if not request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        logout(request)
        return redirect("home")

    cancel_url = request.META.get("HTTP_REFERER", "")
    site_root = request.build_absolute_uri("/")[:-1]
    if not cancel_url.startswith(site_root):
        cancel_url = _admin_url("index")

    return render(request, "admin/logout_confirm.html", {"cancel_url": cancel_url})
