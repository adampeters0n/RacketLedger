"""Vyuctovani admin."""
from decimal import Decimal

from django.contrib import admin, messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone as dj_tz
from django.utils.html import format_html

from ..admin_utils import parse_czech_date_parts
from ..forms import VyuctovaniNastaveniForm
from ..models import Hrac, Vyuctovani, VyuctovaniNastaveni

REASON_LABELS = {
    "manual": "Ručně z adminu",
    "MESICNE": "Měsíčně",
    "N_TRENINGU": "Po N trénincích",
    "CASTKA": "Limit kreditu",
    "AUTO": "Automaticky (limit kreditu)",
    "rodina": "Vyúčtování rodiny",
}

REZIM_LABELS = dict(VyuctovaniNastaveni.AutoRezim.choices)


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
    change_form_template = "admin/core/vyuctovani/change_form.html"
    change_list_template = "admin/core/vyuctovani/change_list.html"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    date_hierarchy = "created_at"
    ordering = ("-period_to",)
    list_filter = (("created_at", VyuctovaniDatumFilter),)
    search_fields = ("hrac__jmeno", "hrac__prijmeni")
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

    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path(
                "nastaveni/",
                self.admin_site.admin_view(self.nastaveni_view),
                name="core_vyuctovani_nastaveni",
            ),
        ]
        return extra + urls

    def nastaveni_view(self, request):
        nastaveni = VyuctovaniNastaveni.load()

        if request.method == "POST":
            form = VyuctovaniNastaveniForm(request.POST, instance=nastaveni)
            if form.is_valid():
                form.save()
                nastaveni = VyuctovaniNastaveni.load()
                if (
                    form.cleaned_data.get("aplikovat_na_vsechny")
                    and form.instance.auto_rezim != VyuctovaniNastaveni.AutoRezim.MANUAL
                ):
                    updated = Hrac.objects.update(
                        vyuctovani_rezim=form.instance.auto_rezim,
                        vyuctovani_n=form.instance.auto_pocet_treninku,
                        vyuctovani_threshold=form.instance.auto_limit,
                    )
                    self.message_user(
                        request,
                        f"Nastavení uloženo. Režim synchronizován u {updated} hráčů.",
                        level=messages.SUCCESS,
                    )
                else:
                    self.message_user(request, "Nastavení vyúčtování uloženo.", level=messages.SUCCESS)
                return redirect("admin:core_vyuctovani_nastaveni")
            self.message_user(
                request,
                "Nastavení se nepodařilo uložit. Zkontrolujte zvýrazněná pole.",
                level=messages.ERROR,
            )
        else:
            form = VyuctovaniNastaveniForm(instance=nastaveni)

        hraci_qs = Hrac.objects.order_by("prijmeni", "jmeno")[:20]
        for h in hraci_qs:
            h.prepocitat_stav_uzaverky()

        hraci_prehled = [
            {
                "jmeno": h.cele_jmeno,
                "pocet_treninku": h.pocet_treninku_od_vyuctovani,
                "posledni": self._fmt_dt(h.posledni_vyuctovani_at) if h.posledni_vyuctovani_at else "—",
                "url": reverse("admin:core_hrac_change", args=[h.pk]),
            }
            for h in hraci_qs
        ]

        ctx = {
            **self.admin_site.each_context(request),
            "title": "Nastavení vyúčtování",
            "form": form,
            "opts": self.model._meta,
            "changelist_url": reverse("admin:core_vyuctovani_changelist"),
            "hraci_url": reverse("admin:core_hrac_changelist"),
            "hraci_prehled": hraci_prehled,
            "hraci_celkem": Hrac.objects.count(),
            "aktualni_rezim": REZIM_LABELS.get(nastaveni.auto_rezim, nastaveni.auto_rezim),
            "aktualni_popis": nastaveni.popis_rezimu(),
        }
        if request.method == "POST" and not form.is_valid():
            ctx["aktualni_rezim"] = REZIM_LABELS.get(
                form.data.get("auto_rezim", nastaveni.auto_rezim),
                nastaveni.auto_rezim,
            )
        return TemplateResponse(request, "admin/core/vyuctovani/nastaveni.html", ctx)

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

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        if obj is None:
            return self._get_obj_does_not_exist_redirect(request, self.opts, object_id)

        extra_context = extra_context or {}
        extra_context.update(self._detail_context(request, obj))
        return TemplateResponse(
            request,
            self.change_form_template,
            {
                **self.admin_site.each_context(request),
                "title": f"Vyúčtování – {obj.hrac.cele_jmeno}",
                "subtitle": None,
                "opts": self.model._meta,
                "original": obj,
                "object": obj,
                "has_view_permission": self.has_view_permission(request, obj),
                "has_change_permission": False,
                "has_delete_permission": self.has_delete_permission(request, obj),
                "has_editable_inline_admin_formsets": False,
                "media": self.media,
                "is_popup": False,
                "save_as": False,
                "show_delete": self.has_delete_permission(request, obj),
                **extra_context,
            },
        )

    def _detail_context(self, request, obj):
        kredit_po = (Decimal(obj.credit_end or 0) + Decimal(obj.amount_due or 0)).quantize(Decimal("0.01"))
        return {
            "obdobi": self._fmt_obdobi(obj),
            "duvod": REASON_LABELS.get(obj.reason, obj.reason),
            "vytvoreno": self._fmt_dt(obj.created_at),
            "pocet_treninku": obj.sessions_count,
            "nauctovano": self._kc(obj.charges_total),
            "platby": self._kc(obj.payments_total),
            "k_uhrade": self._kc(obj.amount_due),
            "kredit_start": self._kc_kredit(obj.credit_start),
            "kredit_end": self._kc_kredit(obj.credit_end),
            "kredit_po_uhrade": self._kc_kredit(kredit_po),
            "hrac_change_url": reverse("admin:core_hrac_change", args=[obj.hrac_id]),
            "vyuctovani_list_url": f"{reverse('admin:core_vyuctovani_changelist')}?hrac__id__exact={obj.hrac_id}",
            "nastaveni_url": reverse("admin:core_vyuctovani_nastaveni"),
            "delete_url": reverse("admin:core_vyuctovani_delete", args=[obj.pk]),
            "history_url": reverse("admin:core_vyuctovani_history", args=[obj.pk]),
        }

    def _fmt_dt(self, dt):
        if not dt:
            return "—"
        if dj_tz.is_aware(dt):
            dt = dj_tz.localtime(dt)
        return dt.strftime("%d.%m.%Y %H:%M")

    def _fmt_obdobi(self, obj):
        start = self._fmt_dt(obj.period_from) if obj.period_from else "od začátku"
        end = self._fmt_dt(obj.period_to)
        return f"{start} → {end}"

    def _kc(self, value: Decimal) -> str:
        value = Decimal(value or 0).quantize(Decimal("0.01"))
        return f"{value:,.0f} Kč".replace(",", " ")

    def _kc_kredit(self, value: Decimal) -> str:
        value = Decimal(value or 0).quantize(Decimal("0.01"))
        if value < 0:
            return format_html('<span class="vyuct-kredit-dluh">{} Kč (dluh)</span>', f"{abs(value):,.0f}".replace(",", " "))
        if value > 0:
            return format_html('<span class="vyuct-kredit-plus">+{} Kč (přeplatek)</span>', f"{value:,.0f}".replace(",", " "))
        return "0 Kč"

    def col_obdobi(self, obj):
        return self._fmt_obdobi(obj)
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
        return self._kc_kredit(val)
    col_kredit.short_description = "Kredit"

    def col_kredit_po_uhrade(self, obj):
        val = (Decimal(obj.credit_end or 0) + Decimal(obj.amount_due or 0))
        return self._kc_kredit(val)
    col_kredit_po_uhrade.short_description = "Kredit po úhradě"
