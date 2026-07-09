"""Vyuctovani admin."""
from decimal import Decimal

from django.contrib import admin
from django.utils import timezone as dj_tz

from ..admin_utils import parse_czech_date_parts
from ..models import Vyuctovani


class VyuctovaniDatumFilter(admin.DateFieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.title = "Data"
        if self.links:
            links = list(self.links)
            links[0] = ("Vše", links[0][1])
            self.links = links


@admin.register(Vyuctovani)
class VyuctovaniAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False
        
    date_hierarchy = "created_at"
    ordering = ("-period_to",)
    list_filter = (("created_at", VyuctovaniDatumFilter),)
    search_fields = ("hrac__jmeno",)
    list_per_page = 50

    list_display = (
        "col_obdobi",
        "hrac",
        "col_nauctovano",
        "col_platby",
        "col_k_uhrade",
        "col_kredit",
        "col_kredit_po_uhrade",
    )

    def get_search_results(self, request, queryset, search_term):
        parts = parse_czech_date_parts(search_term)
        if parts:
            if parts.year is not None:
                return queryset.filter(
                    period_from__year=parts.year,
                    period_from__month=parts.month,
                    period_from__day=parts.day,
                ), False
            return queryset.filter(
                period_from__month=parts.month,
                period_from__day=parts.day,
            ), False
        return super().get_search_results(request, queryset, search_term)

    def _kc(self, value: Decimal) -> str:
        value = Decimal(value or 0).quantize(Decimal("0.01"))
        return f"{value:.0f} Kč"

    def col_obdobi(self, obj):
        def _fmt(dt):
            if not dt:
                return "—"
            if dj_tz.is_aware(dt):
                dt = dj_tz.localtime(dt)
            return dt.strftime("%d.%m.%Y %H:%M")
        return f"{_fmt(obj.period_from)} → {_fmt(obj.period_to)}"
    col_obdobi.short_description = "Období"

    def _fallback_charges(self, obj):
        return obj.nacitano_v_obdobi

    def _fallback_payments(self, obj):
        return obj.platby_v_obdobi

    def _fallback_credit_end(self, obj):
        return obj.kredit_na_konci

    def col_nauctovano(self, obj):
        val = obj.charges_total or 0
        if val == 0 and obj.amount_due == 0 and obj.payments_total == 0:
            val = self._fallback_charges(obj)
        return self._kc(val)
    col_nauctovano.short_description = "Naúčtováno"

    def col_platby(self, obj):
        val = obj.payments_total or 0
        if val == 0 and obj.amount_due == 0 and obj.charges_total == 0:
            val = self._fallback_payments(obj)
        return self._kc(val)
    col_platby.short_description = "Platby/vratky"

    def col_k_uhrade(self, obj):
        if obj.amount_due is None or (obj.amount_due == 0 and obj.charges_total == 0 and obj.payments_total == 0):
            val = (self._fallback_charges(obj) - self._fallback_payments(obj))
        else:
            val = obj.amount_due
        return self._kc(val)
    col_k_uhrade.short_description = "K úhradě"

    def col_kredit(self, obj):
        val = obj.credit_end or 0
        if val == 0 and obj.amount_due == 0 and obj.charges_total == 0 and obj.payments_total == 0:
            val = self._fallback_credit_end(obj)
        return self._kc(val)
    col_kredit.short_description = "Kredit"

    def col_kredit_po_uhrade(self, obj):
        val = (Decimal(obj.credit_end or 0) + Decimal(obj.amount_due or 0))
        return self._kc(val)
    col_kredit_po_uhrade.short_description = "Kredit po úhradě"
