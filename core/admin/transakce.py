"""Transakce admin."""
from datetime import date
from decimal import Decimal

from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, reverse
from django.utils import timezone as dj_tz
from django.utils.html import format_html

from ..admin_utils import (
    CZECH_MONTHS_GENITIVE,
    ParsedDateParts,
    format_czech_date,
    format_czech_datetime,
    parse_czech_date_parts,
    trener_label,
)
from ..models import Transakce, Trening


class OnlyPaymentsFilter(admin.SimpleListFilter):
    title = "Typu"
    parameter_name = "typ"

    def lookups(self, request, model_admin):
        return [
            (Transakce.Typ.PLATBA, Transakce.Typ.PLATBA.label),
            (Transakce.Typ.VRATKA, Transakce.Typ.VRATKA.label),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val in (Transakce.Typ.PLATBA, Transakce.Typ.VRATKA):
            return queryset.filter(typ=val)
        return queryset


class TransakceDatumFilter(admin.DateFieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.title = "Data"


@admin.register(Transakce)
class TransakceAdmin(admin.ModelAdmin):
    list_display = ("datum_display", "hrac_link", "castka_display", "typ_display", "poznamka", "akce_smazat")
    list_filter = (OnlyPaymentsFilter, ("vytvoreno", TransakceDatumFilter))
    search_fields = ("hrac__jmeno", "popis")
    actions = ["delete_selected"]
    list_per_page = 50
    
    change_list_template = "admin/core/transakce/change_list.html"
    
    fields = ('hrac', 'typ', 'castka', 'popis', 'vytvoreno')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).select_related("hrac")

    def get_search_results(self, request, queryset, search_term):
        parts = parse_czech_date_parts(search_term)
        if parts:
            if parts.year is not None:
                return queryset.filter(
                    vytvoreno__year=parts.year,
                    vytvoreno__month=parts.month,
                    vytvoreno__day=parts.day,
                ), False
            return queryset.filter(
                vytvoreno__month=parts.month,
                vytvoreno__day=parts.day,
            ), False
        return super().get_search_results(request, queryset, search_term)

    @admin.display(description="Datum", ordering="vytvoreno")
    def datum_display(self, obj):
        if not obj.vytvoreno:
            return "-"
        dt = dj_tz.localtime(obj.vytvoreno) if dj_tz.is_aware(obj.vytvoreno) else obj.vytvoreno
        date_str, time_str = format_czech_datetime(dt)
        return format_html(
            '<span class="tx-datum" data-iso-date="{}">{}</span>'
            ' <span style="color:#888; font-size:0.9em">{}</span>',
            dt.strftime("%Y-%m-%d"),
            date_str,
            time_str,
        )

    @admin.display(description="Hráč", ordering="hrac__jmeno")
    def hrac_link(self, obj):
        if not obj.hrac: return "-"
        url = reverse("admin:core_hrac_change", args=[obj.hrac.id])
        return format_html('<a href="{}" style="font-weight:600;">{}</a>', url, obj.hrac.jmeno)

    @admin.display(description="Částka", ordering="castka")
    def castka_display(self, obj):
        color = "green" if obj.castka >= 0 else "red"
        sign = "+" if obj.castka > 0 else ""
        formatted_val = f"{obj.castka:,.0f}".replace(",", " ")
        
        return format_html(
            '<span style="color:{}; font-weight:bold;">{} {} Kč</span>',
            color, sign, formatted_val
        )

    @admin.display(description="Typ", ordering="typ")
    def typ_display(self, obj):
        return obj.get_typ_display()

    @admin.display(description="Poznámka")
    def poznamka(self, obj):
        return obj.popis or ""

    @admin.display(description="Akce")
    def akce_smazat(self, obj):
        url = reverse("admin:core_transakce_delete", args=[obj.id])
        return format_html('<a class="deletelink" href="{}"></a>', url)

    def trainings_for_day_view(self, request):
        from datetime import datetime as dt_parse

        day = request.GET.get("day")
        month = request.GET.get("month")
        year = request.GET.get("year")
        raw_date = (request.GET.get("date") or "").strip()

        parts = None
        if day and month:
            try:
                parts = ParsedDateParts(
                    day=int(day),
                    month=int(month),
                    year=int(year) if year else None,
                )
            except (TypeError, ValueError):
                parts = None
        elif raw_date:
            try:
                d = dt_parse.strptime(raw_date, "%Y-%m-%d").date()
                parts = ParsedDateParts(day=d.day, month=d.month, year=d.year)
            except ValueError:
                parts = parse_czech_date_parts(raw_date)

        if not parts:
            return JsonResponse({"ok": False, "trainings": []})

        qs = Trening.objects.select_related("trener").prefetch_related("dochazky__hrac")
        if parts.year is not None:
            qs = qs.filter(datum__year=parts.year, datum__month=parts.month, datum__day=parts.day)
        else:
            qs = qs.filter(datum__month=parts.month, datum__day=parts.day)
        qs = qs.order_by("datum")

        items = []
        for t in qs:
            dt = dj_tz.localtime(t.datum) if dj_tz.is_aware(t.datum) else t.datum
            hraci = ", ".join(
                d.hrac.jmeno for d in t.dochazky.all() if d.prisel and d.hrac_id
            ) or "—"
            items.append({
                "time": dt.strftime("%H:%M"),
                "date": format_czech_date(dt),
                "trener": trener_label(t.trener),
                "format": t.get_format_display(),
                "hraci": hraci,
                "url": reverse("admin:core_trening_change", args=[t.pk]),
            })

        if parts.year is not None:
            date_label = format_czech_date(date(parts.year, parts.month, parts.day))
        else:
            date_label = f"{parts.day}. {CZECH_MONTHS_GENITIVE[parts.month]}"

        return JsonResponse({
            "ok": True,
            "date_label": date_label,
            "trainings": items,
        })

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            path(
                "trainings-for-day/",
                self.admin_site.admin_view(self.trainings_for_day_view),
                name="core_transakce_trainings_for_day",
            ),
        ]
        return my_urls + urls

    def get_form(self, request, obj=None, **kwargs):
        Form = super().get_form(request, obj, **kwargs)
        if obj is None and "typ" in Form.base_fields:
            Form.base_fields["typ"].choices = [
                (Transakce.Typ.PLATBA, Transakce.Typ.PLATBA.label),
                (Transakce.Typ.VRATKA, Transakce.Typ.VRATKA.label),
            ]
        return Form

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        hrac_id = request.GET.get("hrac")
        if hrac_id:
            initial["hrac"] = hrac_id
        return initial
