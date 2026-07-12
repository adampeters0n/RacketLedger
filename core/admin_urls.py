"""Admin site URL patching and branding."""
from django.contrib import admin
from django.urls import path

from .admin.changelist import patch_admin_single_column_sorting
from .admin_views import (
    admin_analytika_index_view,
    admin_analytika_view,
    admin_dashboard_view,
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


def setup_admin_site():
    """Patch admin.site URLs and set branding."""
    patch_admin_single_column_sorting()
    _original_get_urls = admin.site.get_urls

    def _new_get_urls():
        urls = _original_get_urls()
        extra = [
            path("", admin.site.admin_view(admin_dashboard_view), name="index"),
            path("analytika/", admin.site.admin_view(admin_analytika_index_view), name="analytika"),
            path(
                "analytika/<slug:section>/",
                admin.site.admin_view(admin_analytika_view),
                name="analytika_section",
            ),
        ]
        try:
            extra += _treneri_urls_for_site(admin.site)
        except Exception:
            pass
        return extra + urls

    admin.site.get_urls = _new_get_urls
    admin.site.site_header = "Tenis systém Čimice"
    admin.site.site_title = "Tenis systém"
    admin.site.index_title = "Přehled"
