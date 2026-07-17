"""Admin site URL patching and branding."""
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.translation import gettext_lazy as _

from .admin.changelist import patch_admin_single_column_sorting
from .admin_views import (
    admin_analytika_export_view,
    admin_analytika_index_view,
    admin_analytika_view,
    admin_dashboard_view,
    admin_nastaveni_view,
    admin_nastaveni_autosave_view,
    admin_nastaveni_export_view,
    admin_nastaveni_import_view,
    admin_nastaveni_vzhled_view,
)


def _treneri_urls_for_site(site):
    """Vrátí URL patterns /admin/core/treneri/... pro daný AdminSite."""
    from .models import Trening

    def wrap(view):
        return site.admin_view(view)

    def summary_view(request, *args, **kwargs):
        ma = site._registry[Trening]
        return ma.treneri_summary_view(request)

    def detail_view(request, user_id, *args, **kwargs):
        ma = site._registry[Trening]
        return ma.trener_detail_view(request, user_id=user_id)

    return [
        path("core/treneri/", wrap(summary_view), name="core_treneri_summary"),
        path("core/treneri/<int:user_id>/", wrap(detail_view), name="core_treneri_detail"),
    ]


def _rodina_urls_for_site(site):
    """Seznam rodin pod /admin/core/hrac/rodina/; stará URL přesměruje."""
    from .models import Rodina

    def wrap(view):
        return site.admin_view(view)

    def changelist_view(request, *args, **kwargs):
        ma = site._registry[Rodina]
        return ma.changelist_view(request, *args, **kwargs)

    def legacy_redirect(request):
        target = reverse("admin:core_hrac_rodina_changelist")
        qs = request.META.get("QUERY_STRING", "")
        if qs:
            target = f"{target}?{qs}"
        return redirect(target)

    return [
        path("core/hrac/rodina/", wrap(changelist_view), name="core_hrac_rodina_changelist"),
        path("core/rodina/", wrap(legacy_redirect)),
    ]


def refresh_admin_branding(site=None):
    """Aktualizuje hlavičku adminu podle SystemNastaveni."""
    site = site or admin.site
    try:
        from .models import SystemNastaveni

        nast = SystemNastaveni.load()
        name = (nast.nazev_klubu or "TenisSystém").strip()
        site.site_header = name
        site.site_title = name
    except Exception:
        pass


def setup_admin_site():
    """Patch admin.site URLs and set branding."""
    patch_admin_single_column_sorting()
    _original_get_urls = admin.site.get_urls

    def _new_get_urls():
        urls = _original_get_urls()
        extra = [
            path("", admin.site.admin_view(admin_dashboard_view), name="index"),
            path("nastaveni/", admin.site.admin_view(admin_nastaveni_view), name="nastaveni"),
            path(
                "nastaveni/vzhled/",
                admin.site.admin_view(admin_nastaveni_vzhled_view),
                name="nastaveni_vzhled",
            ),
            path(
                "nastaveni/ulozit/",
                admin.site.admin_view(admin_nastaveni_autosave_view),
                name="nastaveni_autosave",
            ),
            path(
                "nastaveni/export/",
                admin.site.admin_view(admin_nastaveni_export_view),
                name="nastaveni_export",
            ),
            path(
                "nastaveni/import/",
                admin.site.admin_view(admin_nastaveni_import_view),
                name="nastaveni_import",
            ),
            path("analytika/", admin.site.admin_view(admin_analytika_index_view), name="analytika"),
            path(
                "analytika/<slug:section>/",
                admin.site.admin_view(admin_analytika_view),
                name="analytika_section",
            ),
            path(
                "analytika/export/<slug:period>/<slug:fmt>/",
                admin.site.admin_view(admin_analytika_export_view),
                name="analytika_export",
            ),
        ]
        try:
            extra += _treneri_urls_for_site(admin.site)
        except Exception:
            pass
        try:
            extra += _rodina_urls_for_site(admin.site)
        except Exception:
            pass
        return extra + urls

    admin.site.get_urls = _new_get_urls
    admin.site.site_header = "TenisSystém"
    admin.site.site_title = "Tenis systém"
    admin.site.index_title = _("Přehled")

    _orig_each_context = admin.site.each_context

    def _each_context(request):
        ctx = _orig_each_context(request)
        try:
            from .models import SystemNastaveni

            name = (SystemNastaveni.load().nazev_klubu or "TenisSystém").strip()
            ctx["site_header"] = name
            ctx["site_title"] = name
        except Exception:
            pass
        return ctx

    admin.site.each_context = _each_context
