"""Trener-related model admins."""
from decimal import Decimal

from django.contrib import admin

from ..forms import TrenerPlatbaForm
from ..models import TrenerPlatba, TrenerProfil, TrenerSazba
from ..roles import can_view_all_treneri
from .role_gate import RoleGateMixin


@admin.register(TrenerProfil)
class TrenerProfilAdmin(RoleGateMixin, admin.ModelAdmin):
    # Sazby / výplaty upravuje jen admin a provozovatel
    role_check = staticmethod(can_view_all_treneri)
    list_display = ("uzivatel", "sazba_za_hodinu")
    search_fields = ("user__username", "user__first_name", "user__last_name")

    def uzivatel(self, obj):
        return obj.user.get_full_name() or obj.user.username
    uzivatel.short_description = "Trenér"


@admin.register(TrenerSazba)
class TrenerSazbaAdmin(RoleGateMixin, admin.ModelAdmin):
    role_check = staticmethod(can_view_all_treneri)
    list_display = ("uzivatel", "platnost_od", "platnost_do", "sazba_za_hodinu")
    list_filter = ("user",)
    date_hierarchy = "platnost_od"
    search_fields = ("user__username", "user__first_name", "user__last_name")

    def uzivatel(self, obj):
        return obj.user.get_full_name() or obj.user.username
    uzivatel.short_description = "Trenér"


@admin.register(TrenerPlatba)
class TrenerPlatbaAdmin(RoleGateMixin, admin.ModelAdmin):
    role_check = staticmethod(can_view_all_treneri)
    form = TrenerPlatbaForm
    list_display = ("vytvoreno", "uzivatel", "castka", "poznamka")
    list_filter = ("user", "vytvoreno")
    search_fields = ("user__username", "user__first_name", "user__last_name", "poznamka")
    
    fields = ('user', 'castka', 'poznamka', 'vytvoreno')

    def uzivatel(self, obj):
        return obj.user.get_full_name() or obj.user.username
    uzivatel.short_description = "Trenér"

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        uid = request.GET.get("user")
        if uid:
            initial["user"] = uid
        amt = request.GET.get("amount")
        if amt:
            try:
                initial["castka"] = Decimal(str(amt).replace(",", "."))
            except Exception:
                pass
        return initial
