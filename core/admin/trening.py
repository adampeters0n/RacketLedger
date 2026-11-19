"""Trening admin."""
from ..admin_mixins import ConfigurableListPerPageMixin
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, time, timedelta
import json
import re

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch, Sum
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _
from django.utils import timezone as dj_tz
from django.utils.html import format_html, escape
from django.utils.safestring import mark_safe
from django import forms
from django.forms import formset_factory

from ..analytika_data import TrenerRateLookup
from ..admin_utils import format_month_year, month_range, parse_czech_date_parts, pretty_username, trener_label, filter_queryset_by_parsed_date
from ..roles import can_access_treningy, can_view_all_treneri
from .role_gate import RoleGateMixin
from ..forms import (
    AddDayForm,
    TrainingSlotForm,
    TrainingSlotFormSet,
)
from ..models import (
    Cenik,
    CenikFormat,
    Dochazka,
    Hrac,
    PredpokladanySkip,
    PredpokladanySlot,
    StalyRozvrhSlot,
    SystemNastaveni,
    TrenerPlatba,
    TrenerProfil,
    TrenerSazba,
    Trening,
)
from ..predpokladany import materialize_for_date
from ..schedule_build import build_trening_schedule
from .inlines import DochazkaInline

User = get_user_model()


def _parse_admin_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _period_from_request(request):
    """Bez GET parametrů from/to vrátí aktuální měsíc; prázdné hodnoty = bez filtru."""
    if "from" not in request.GET and "to" not in request.GET:
        return month_range(dj_tz.localdate())

    dfrom = _parse_admin_date(request.GET.get("from", ""))
    dto = _parse_admin_date(request.GET.get("to", ""))
    return dfrom, dto


def _dochazka_prefetch():
    return Prefetch(
        "dochazky",
        queryset=Dochazka.objects.filter(prisel=True).select_related("hrac"),
    )


def _hraci_from_training(training):
    """Hráči z prefetchnutých docházek – bez dalšího dotazu."""
    names = [
        d.hrac.cele_jmeno
        for d in training.dochazky.all()
        if d.prisel and d.hrac_id
    ]
    return ", ".join(names) or "—"


def _format_name_map() -> dict[str, str]:
    names = dict(CenikFormat.VYCHOZI_KODY)
    names.update(CenikFormat.objects.values_list("kod", "nazev"))
    return names


def _training_row_dict(user, training, rate_lookup: TrenerRateLookup, format_names: dict[str, str]):
    dt = dj_tz.localtime(training.datum) if dj_tz.is_aware(training.datum) else training.datum
    is_service = training.je_sluzba()
    castka = rate_lookup.earned_for(
        user.id, dt, training.delka_minut, training.format, training.kurt
    )
    if is_service:
        hours_label = "—"
        sazba_label = f"{rate_lookup.vyplet_for_user(user.id):.0f} Kč"
        cas_label = "—"
    else:
        hours = (Decimal(training.delka_minut) / Decimal(60)).quantize(Decimal("0.01"))
        rate = rate_lookup.for_user_date(user.id, dt)
        hours_label = f"{hours:.2f}"
        sazba_label = f"{rate:.0f} Kč/h"
        cas_label = dt.strftime("%H:%M")
    return {
        "datum": dt.strftime("%d.%m.%Y"),
        "cas": cas_label,
        "format": format_names.get(training.format, training.format),
        "kurt": training.get_kurt_display(),
        "hraci": _hraci_from_training(training),
        "hodiny": hours_label,
        "sazba": sazba_label,
        "castka": f"{castka:.0f} Kč",
        "trening_change_url": reverse("admin:core_trening_change", args=[training.id]),
        "month_key": (dt.year, dt.month),
        "is_service": is_service,
    }


def _build_trener_training_stats(user, trainings, rate_lookup: TrenerRateLookup):
    """Součty, měsíční rozpis a seskupení tréninků v jedné iteraci."""
    format_names = _format_name_map()
    total_min = 0
    total_castka = Decimal("0.00")
    pocet = 0
    monthly = defaultdict(lambda: {"pocet": 0, "minuty": 0, "castka": Decimal("0.00")})
    groups = defaultdict(list)

    for t in trainings:
        dt = dj_tz.localtime(t.datum) if dj_tz.is_aware(t.datum) else t.datum
        castka = rate_lookup.earned_for(user.id, dt, t.delka_minut, t.format, t.kurt)
        mins = 0 if t.je_sluzba() else (t.delka_minut or 0)
        pocet += 1
        total_min += mins
        total_castka += castka

        key = (dt.year, dt.month)
        monthly[key]["pocet"] += 1
        monthly[key]["minuty"] += mins
        monthly[key]["castka"] += castka
        groups[key].append(_training_row_dict(user, t, rate_lookup, format_names))

    hodiny = (Decimal(total_min) / Decimal(60)).quantize(Decimal("0.01"))
    mesice = []
    for (year, month), data in sorted(monthly.items(), reverse=True):
        m_hours = (Decimal(data["minuty"]) / Decimal(60)).quantize(Decimal("0.01"))
        m_castka = data["castka"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        mesice.append({
            "label": format_month_year(year, month),
            "year": year,
            "month": month,
            "pocet": data["pocet"],
            "hodiny": f"{m_hours:.2f}",
            "castka": f"{m_castka:.0f} Kč",
            "castka_raw": m_castka,
        })

    stats = {
        "pocet": pocet,
        "hodiny": f"{hodiny:.2f}",
        "castka": f"{total_castka.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.0f} Kč",
        "castka_raw": total_castka,
        "hodiny_raw": hodiny,
        "mesice": mesice,
        "monthly_raw": {k: v["castka"] for k, v in monthly.items()},
    }

    today = dj_tz.localdate()
    current_key = (today.year, today.month)
    sorted_keys = sorted(groups.keys(), reverse=True)
    open_key = current_key if current_key in groups else (sorted_keys[0] if sorted_keys else None)

    training_months = []
    for key in sorted_keys:
        year, month = key
        rows = groups[key]
        training_months.append({
            "label": format_month_year(year, month),
            "rows": rows,
            "pocet": len(rows),
            "is_open": key == open_key,
        })

    return stats, training_months


def _all_trener_ids():
    """Všichni trenéři v systému (historie tréninků + nastavené sazby)."""
    ids = set(Trening.objects.values_list("trener_id", flat=True))
    ids.update(TrenerSazba.objects.values_list("user_id", flat=True))
    ids.discard(None)
    return ids


def _aggregate_trener_trainings(user, trainings, rate_lookup: TrenerRateLookup | None = None):
    """Součty a měsíční rozpis z iterable tréninků jednoho trenéra."""
    if rate_lookup is None:
        rate_lookup = TrenerRateLookup([user.id])
    total_min = 0
    total_castka = Decimal("0.00")
    pocet = 0
    monthly = defaultdict(lambda: {"pocet": 0, "minuty": 0, "castka": Decimal("0.00")})

    for t in trainings:
        dt = dj_tz.localtime(t.datum) if dj_tz.is_aware(t.datum) else t.datum
        castka = rate_lookup.earned_for(user.id, dt, t.delka_minut, t.format, t.kurt)
        mins = 0 if t.je_sluzba() else (t.delka_minut or 0)
        pocet += 1
        total_min += mins
        total_castka += castka

        key = (dt.year, dt.month)
        monthly[key]["pocet"] += 1
        monthly[key]["minuty"] += mins
        monthly[key]["castka"] += castka

    hodiny = (Decimal(total_min) / Decimal(60)).quantize(Decimal("0.01"))
    mesice = []
    for (year, month), data in sorted(monthly.items(), reverse=True):
        m_hours = (Decimal(data["minuty"]) / Decimal(60)).quantize(Decimal("0.01"))
        m_castka = data["castka"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        mesice.append({
            "label": format_month_year(year, month),
            "year": year,
            "month": month,
            "pocet": data["pocet"],
            "hodiny": f"{m_hours:.2f}",
            "castka": f"{m_castka:.0f} Kč",
            "castka_raw": m_castka,
        })

    return {
        "pocet": pocet,
        "hodiny": f"{hodiny:.2f}",
        "castka": f"{total_castka.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.0f} Kč",
        "castka_raw": total_castka,
        "hodiny_raw": hodiny,
        "mesice": mesice,
        "monthly_raw": {k: v["castka"] for k, v in monthly.items()},
    }


def _format_kc(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.0f} Kč"


def _trener_financial_overview(user, rate_lookup: TrenerRateLookup, stats: dict | None = None):
    """Celková odehraná částka, aktuální měsíc a dlužná částka (bez filtru období)."""
    if stats is not None:
        celkem = stats["castka_raw"]
        monthly_raw = stats["monthly_raw"]
    else:
        monthly_raw: dict = defaultdict(lambda: Decimal("0.00"))
        celkem = Decimal("0.00")
        for row in Trening.objects.filter(trener=user).values(
            "datum", "delka_minut", "format", "kurt"
        ):
            dt = row["datum"]
            if dj_tz.is_aware(dt):
                dt = dj_tz.localtime(dt)
            castka = rate_lookup.earned_for(
                user.id, dt, row["delka_minut"], row["format"], row["kurt"]
            )
            celkem += castka
            monthly_raw[(dt.year, dt.month)] += castka

    today = dj_tz.localdate()
    mesic_castka = monthly_raw.get((today.year, today.month), Decimal("0.00"))

    zaplaceno = Decimal(
        TrenerPlatba.objects.filter(user=user).aggregate(s=Sum("castka"))["s"] or 0
    )
    dluzna = (celkem - zaplaceno).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "celkova_castka": _format_kc(celkem),
        "mesic_label": format_month_year(today.year, today.month),
        "mesic_castka": _format_kc(mesic_castka),
        "dluzna_castka": _format_kc(dluzna),
        "dluzna_raw": dluzna,
    }


def _enrich_mesice_with_payments(user, mesice):
    """Doplní měsíční přehled o zaznamenané výplaty trenérovi."""
    platby_by_month = defaultdict(lambda: {"items": [], "total": Decimal("0.00")})
    for p in TrenerPlatba.objects.filter(user=user).order_by("-vytvoreno"):
        dt = dj_tz.localtime(p.vytvoreno) if dj_tz.is_aware(p.vytvoreno) else p.vytvoreno
        key = (dt.year, dt.month)
        platby_by_month[key]["items"].append({
            "datum": dt.strftime("%d.%m.%Y"),
            "castka": f"{p.castka:.0f} Kč",
            "url": reverse("admin:core_trenerplatba_change", args=[p.id]),
        })
        platby_by_month[key]["total"] += p.castka

    enriched = []
    for m in mesice:
        data = platby_by_month.get((m["year"], m["month"]), {"items": [], "total": Decimal("0.00")})
        enriched.append({
            **m,
            "vyplaty": data["items"],
            "vyplaceno_celkem": _format_kc(data["total"]) if data["items"] else "",
        })
    return enriched


def _training_formset_from_request(post_data=None, initial_slots=None):
    from ..forms import TrainingSlotFormSetBase

    if post_data is not None:
        total = int(post_data.get("slots-TOTAL_FORMS", 10) or 10)
        extra = max(5, total)
    else:
        total = max(len(initial_slots or []), 1)
        extra = max(5, total + 2)

    FormSetClass = formset_factory(
        TrainingSlotForm,
        formset=TrainingSlotFormSetBase,
        extra=extra,
        max_num=50,
        min_num=1,
        validate_min=True,
    )
    if post_data is not None:
        return FormSetClass(post_data, prefix="slots")
    return FormSetClass(prefix="slots", initial=initial_slots or [])


class TrenerListFilter(admin.SimpleListFilter):
    title = _("Trenér")
    parameter_name = "trener"

    def lookups(self, request, model_admin):
        trener_ids = (
            model_admin.get_queryset(request)
            .values_list("trener_id", flat=True)
            .distinct()
        )
        users = (
            User.objects.filter(pk__in=trener_ids)
            .order_by("first_name", "last_name", "username")
        )
        return [(str(u.pk), trener_label(u)) for u in users if u.pk]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            return queryset.filter(trener_id=val)
        return queryset


class TreningFormatFilter(admin.SimpleListFilter):
    title = _("Typ tréninku")
    parameter_name = "format"

    def lookups(self, request, model_admin):
        return CenikFormat.choices()

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            return queryset.filter(format=val)
        return queryset


class SezonaListFilter(admin.SimpleListFilter):
    title = _("Sezóna")
    parameter_name = "sezona"

    def lookups(self, request, model_admin):
        return [
            (Cenik.Kurt.VENEK, _("Léto")),
            (Cenik.Kurt.HALA, _("Zima")),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            return queryset.filter(kurt=val)
        return queryset


class TreningDatumFilter(admin.DateFieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.title = _("Datum")
        if self.links:
            links = list(self.links)
            links[0] = (_("Vše"), links[0][1])
            self.links = links


@admin.register(Trening)
class TreningAdmin(RoleGateMixin, ConfigurableListPerPageMixin, admin.ModelAdmin):
    role_check = staticmethod(can_access_treningy)
    change_form_template = "admin/core/trening/change_form.html"
    add_form_template = "admin/core/trening/add_form.html"
    change_list_template = "admin/core/trening/change_list.html"
    list_display = ("datum_display", "hraci_jmena", "trener_jmeno", "format_display", "castka_na_hrace_kc")
    list_filter = (
        TrenerListFilter,
        TreningFormatFilter,
        SezonaListFilter,
        ("datum", TreningDatumFilter),
    )
    search_fields = (
        "trener__username", "trener__first_name", "trener__last_name",
        "poznamka", "dochazky__hrac__jmeno", "dochazky__hrac__prijmeni"
    )
    list_per_page_default = 50
    inlines = [DochazkaInline]
    actions = ["znovu_zpracovat_uctovani"]
    fields = ("trener", "datum", "delka_minut", "format", "kurt", "poznamka")

    def get_form(self, request, obj=None, **kwargs):
        Form = super().get_form(request, obj, **kwargs)
        if "format" in Form.base_fields:
            Form.base_fields["format"] = forms.ChoiceField(
                label=_("Formát"),
                choices=CenikFormat.choices(),
                widget=forms.Select(attrs={"class": "vTextField"}),
            )
        if "delka_minut" in Form.base_fields:
            field = Form.base_fields["delka_minut"]
            field.label = _("Délka (hodiny)")
            field.widget = forms.Select(choices=list(SystemNastaveni.DELKA_MINUT_CHOICES))
            field.help_text = ""
            if obj is None:
                try:
                    defaults = SystemNastaveni.training_defaults(user=request.user)
                    field.initial = defaults["delka_minut"]
                except Exception:
                    field.initial = 60
        if "trener" in Form.base_fields:
            Form.base_fields["trener"].label = "Trenér"
        if "datum" in Form.base_fields:
            Form.base_fields["datum"].label = ""
        if "kurt" in Form.base_fields:
            Form.base_fields["kurt"].label = "Kurt"
            if obj is None:
                try:
                    Form.base_fields["kurt"].initial = SystemNastaveni.training_defaults(
                        user=request.user
                    )["kurt"]
                except Exception:
                    pass
        if "poznamka" in Form.base_fields:
            Form.base_fields["poznamka"].label = "Poznámka"
        return Form

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "trener":
            formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)

            def label_from_instance(user):
                full = (getattr(user, "get_full_name", None) or (lambda: ""))().strip()
                return full or pretty_username(user.username)

            formfield.label_from_instance = label_from_instance
            return formfield

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_inline_instances(self, request, obj=None):
        # Change form má vlastní UI hráčů (jako Přidat trénink) – bez tabular inline a částek
        if obj is not None:
            return []
        return super().get_inline_instances(request, obj)

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        if change and obj is not None:
            local = dj_tz.localtime(obj.datum) if dj_tz.is_aware(obj.datum) else obj.datum
            hraci_qs = Hrac.objects.filter(aktivni=True).order_by("prijmeni", "jmeno")
            change_hraci_all = [{"id": str(h.pk), "jmeno": h.cele_jmeno} for h in hraci_qs]
            change_hraci_initial = [
                {"id": str(d.hrac_id), "jmeno": d.hrac.cele_jmeno}
                for d in obj.dochazky.select_related("hrac").all()
                if d.hrac_id
            ]
            context.update({
                "date_value": local.date().isoformat(),
                "time_value": local.strftime("%H:%M"),
                "change_hraci_all_json": mark_safe(json.dumps(change_hraci_all, ensure_ascii=False)),
                "change_hraci_initial": change_hraci_initial,
            })
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    def save_model(self, request, obj, form, change):
        if not form.is_valid():
            messages.error(request, f"Chyba v hlavním formuláři: {form.errors}")
        if Cenik.je_sluzba(getattr(obj, "format", None), getattr(obj, "kurt", None)):
            obj.kurt = Cenik.Kurt.SLUZBA
            obj.delka_minut = 60
        super().save_model(request, obj, form, change)

    def _sync_change_form_hraci(self, trening, hrac_ids):
        seen = set()
        wanted = []
        for hrac_id in hrac_ids:
            if not hrac_id or hrac_id in seen:
                continue
            seen.add(hrac_id)
            try:
                wanted.append(Hrac.objects.get(pk=hrac_id))
            except (Hrac.DoesNotExist, ValueError, TypeError):
                continue
        with transaction.atomic():
            existing = {d.hrac_id: d for d in trening.dochazky.all()}
            wanted_ids = {h.pk for h in wanted}
            for hrac_id, doch in list(existing.items()):
                if hrac_id not in wanted_ids:
                    doch.delete()
            for hrac in wanted:
                if hrac.pk not in existing:
                    Dochazka.objects.create(trening=trening, hrac=hrac, prisel=True)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if change and request.POST.get("change_form_hraci_ui"):
            self._sync_change_form_hraci(form.instance, request.POST.getlist("change_form_hraci"))

    def save_formset(self, request, form, formset, change):
        if formset.model == Dochazka and not change:
            # Přidání tréninku (add): hráči přicházejí z multiselectu add_form_hraci (jako v add_day)
            hrac_ids = request.POST.getlist("add_form_hraci")
            formset.new_objects = []
            formset.changed_objects = []
            formset.deleted_objects = []
            with transaction.atomic():
                for hrac_id in hrac_ids:
                    if not hrac_id:
                        continue
                    try:
                        hrac_obj = Hrac.objects.get(pk=hrac_id)
                    except (Hrac.DoesNotExist, ValueError):
                        continue
                    obj = Dochazka.objects.create(
                        trening=form.instance,
                        hrac=hrac_obj,
                        prisel=True,
                    )
                    formset.new_objects.append(obj)
            return

        if not formset.is_valid():
            messages.error(request, f"Chyba v seznamu hráčů: {formset.errors}")
            return

        if formset.model == Dochazka:
            formset.new_objects = []
            formset.changed_objects = []
            formset.deleted_objects = []

            with transaction.atomic():
                form.instance.dochazky.all().delete()

                for inline_form in formset.forms:
                    if not inline_form.cleaned_data or inline_form.cleaned_data.get('DELETE'):
                        continue

                    hrac_obj = inline_form.cleaned_data.get('hrac')
                    if hrac_obj:
                        obj = Dochazka.objects.create(
                            trening=form.instance,
                            hrac=hrac_obj,
                            prisel=True
                        )
                        formset.new_objects.append(obj)
        else:
            super().save_formset(request, form, formset, change)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "datum":
            # Stejné buňky jako Přidat trénink / add-day: type=date + type=time
            kwargs["widget"] = forms.SplitDateTimeWidget(
                date_attrs={"type": "date", "class": "add-day-datum-input vDateField"},
                time_attrs={"type": "time", "class": "vTimeField", "placeholder": "např. 13:00"},
            )
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        # Trenér bez related ikon (+/✎) – stejně široký select jako na Přidat trénink
        if db_field.name == "trener" and formfield is not None:
            w = formfield.widget
            if hasattr(w, "widget"):
                formfield.widget = w.widget
        return formfield

    def _add_form_context(self, request, day_form, formset):
        slots_render = []
        for i, form in enumerate(formset):
            slots_render.append({
                "form": form,
                "index": i,
                "hidden": i > 0,
            })
        raw_datum = day_form["datum"].value()
        if hasattr(raw_datum, "isoformat"):
            date_value = raw_datum.isoformat()
        elif raw_datum:
            date_value = str(raw_datum)
        else:
            date_value = dj_tz.localdate().isoformat()
        return {
            **self.admin_site.each_context(request),
            "title": _("Trénink: přidat"),
            "opts": self.model._meta,
            "day_form": day_form,
            "formset": formset,
            "slots_render": slots_render,
            "date_value": date_value,
        }

    def add_view(self, request, form_url="", extra_context=None):
        """Na /add/ zobrazit formulář den + sloty + Přidat Trénink; POST zpracovat zde."""
        AddDayFormClass = AddDayForm
        FormSetClass = TrainingSlotFormSet
        is_add_form = request.path.rstrip("/").endswith("/add") and self.add_form_template

        if is_add_form and request.method == "POST" and ("day-datum" in request.POST or "slots-TOTAL_FORMS" in request.POST):
            day_form = AddDayFormClass(request.POST, prefix="day")
            formset = _training_formset_from_request(post_data=request.POST)
            if day_form.is_valid() and formset.is_valid():
                default_trener = day_form.cleaned_data.get("trener")
                if not default_trener:
                    messages.error(request, _("Vyberte trenéra pro celý den."))
                else:
                    default_datum = day_form.cleaned_data["datum"]
                    created = 0
                    created_items = []
                    with transaction.atomic():
                        for form in formset:
                            cd = form.cleaned_data
                            if not cd.get("cas"):
                                continue
                            slot_trener = cd.get("trener") or default_trener
                            if not slot_trener:
                                continue
                            slot_datum = cd.get("slot_datum") or default_datum
                            dt = datetime.combine(slot_datum, cd["cas"])
                            if settings.USE_TZ:
                                dt = dj_tz.make_aware(dt, dj_tz.get_current_timezone())
                            defaults = SystemNastaveni.training_defaults(
                                for_date=slot_datum, user=request.user
                            )
                            fmt = cd["format"] or CenikFormat.default_kod()
                            kurt = cd["kurt"] or defaults["kurt"]
                            delka = cd.get("delka_minut") or defaults["delka_minut"]
                            if Cenik.je_sluzba(fmt, kurt):
                                kurt = Cenik.Kurt.SLUZBA
                                delka = 60
                            trening = Trening.objects.create(
                                trener=slot_trener,
                                datum=dt,
                                delka_minut=delka,
                                format=fmt,
                                kurt=kurt,
                                poznamka=(cd.get("poznamka") or "")[:240],
                            )
                            hraci = cd.get("hraci") or []
                            for hrac in hraci:
                                Dochazka.objects.create(trening=trening, hrac=hrac, prisel=True)
                            cas_str = cd["cas"].strftime("%H:%M")
                            jmena = [getattr(h, "cele_jmeno", str(h)) for h in hraci]
                            datum_str = slot_datum.strftime("%d.%m.%Y")
                            created_items.append((datum_str, cas_str, ", ".join(jmena) if jmena else "—", trening.pk))
                            created += 1
                    if created:
                        trener_str = (getattr(default_trener, "get_full_name", lambda: "")() or getattr(default_trener, "username", ""))
                        item_bits = []
                        for datum_str, cas_str, hraci_str, trening_pk in created_items:
                            change_url = reverse("admin:core_trening_change", args=[trening_pk])
                            item_bits.append(format_html(
                                '<a href="{}"><strong>{} {}</strong></a> – {}',
                                change_url, escape(datum_str), escape(cas_str), escape(hraci_str),
                            ))
                        if created == 1:
                            msg_html = format_html(
                                "Trénink {} uložen · trenér {}",
                                item_bits[0],
                                escape(trener_str) or "—",
                            )
                        else:
                            msg_html = format_html(
                                "Uloženo <strong>{}</strong> tréninků · trenér {}<br>{}",
                                created,
                                escape(trener_str) or "—",
                                mark_safe("<br>".join(str(b) for b in item_bits)),
                            )
                        messages.success(request, msg_html)
                        if request.POST.get("_addanother"):
                            add_url = reverse("admin:core_trening_add")
                            return HttpResponseRedirect(f"{add_url}?date={default_datum.isoformat()}")
                        return HttpResponseRedirect(reverse("admin:core_trening_changelist"))
                    else:
                        messages.error(
                            request,
                            "Vyplňte alespoň jeden trénink (čas).",
                        )
            context = self._add_form_context(request, day_form, formset)
            return TemplateResponse(request, self.add_form_template, context)

        if is_add_form and request.method == "GET":
            day_form = AddDayFormClass(prefix="day")
            initial_date = dj_tz.localdate()
            if request.GET.get("date"):
                try:
                    from datetime import datetime as dt_parse
                    initial_date = dt_parse.strptime(request.GET["date"], "%Y-%m-%d").date()
                except Exception:
                    pass
            day_form.initial["datum"] = initial_date
            formset = FormSetClass(prefix="slots")
            context = self._add_form_context(request, day_form, formset)
            return TemplateResponse(request, self.add_form_template, context)
        return super().add_view(request, form_url=form_url, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path("schedule/", self.admin_site.admin_view(self.schedule_view), name="core_trening_schedule"),
            path(
                "schedule/quick-add/",
                self.admin_site.admin_view(self.schedule_quick_add_view),
                name="core_trening_schedule_quick_add",
            ),
            path(
                "schedule/delete/",
                self.admin_site.admin_view(self.schedule_delete_view),
                name="core_trening_schedule_delete",
            ),
            path(
                "schedule/move/",
                self.admin_site.admin_view(self.schedule_move_view),
                name="core_trening_schedule_move",
            ),
            path(
                "schedule/staly/",
                self.admin_site.admin_view(self.schedule_staly_save_view),
                name="core_trening_schedule_staly_save",
            ),
            path(
                "schedule/staly/<int:slot_id>/delete/",
                self.admin_site.admin_view(self.schedule_staly_delete_view),
                name="core_trening_schedule_staly_delete",
            ),
            path(
                "schedule/materialize/",
                self.admin_site.admin_view(self.schedule_materialize_view),
                name="core_trening_schedule_materialize",
            ),
            path(
                "schedule/predpokladany/skip/",
                self.admin_site.admin_view(self.schedule_predpokladany_skip_view),
                name="core_trening_schedule_predpokladany_skip",
            ),
        ]
        return extra + urls

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("trener")
            .prefetch_related(_dochazka_prefetch())
        )

    def get_search_results(self, request, queryset, search_term):
        parts = parse_czech_date_parts(search_term)
        if parts:
            return filter_queryset_by_parsed_date(queryset, parts, "datum"), False
        return super().get_search_results(request, queryset, search_term)

    @admin.display(description=_("Datum"), ordering="datum")
    def datum_display(self, obj):
        dt = dj_tz.localtime(obj.datum) if dj_tz.is_aware(obj.datum) else obj.datum
        url = reverse("admin:core_trening_change", args=[obj.pk])
        return format_html(
            '<a href="{}"><span class="tx-datum" data-iso-date="{}">{}</span>'
            ' <span style="color:#888;font-size:0.9em">{}</span></a>',
            url,
            dt.strftime("%Y-%m-%d"),
            dt.strftime("%d.%m.%Y"),
            dt.strftime("%H:%M"),
        )

    @admin.display(description=_("Hráč(i)"))
    def hraci_jmena(self, obj):
        return _hraci_from_training(obj)

    @admin.display(description=_("Trenér"))
    def trener_jmeno(self, obj):
        return trener_label(obj.trener)

    @admin.display(description=_("Typ"))
    def format_display(self, obj):
        return obj.get_format_display()

    @admin.display(description=_("Částka / hráč"))
    def castka_na_hrace_kc(self, obj):
        # Zobrazení bez desetinných míst; výpočty dál přes cena_na_hrace() (Decimal)
        return f"{obj.cena_na_hrace():.0f} Kč"

    def response_add(self, request, obj, post_url_continue=None):
        local_dt = dj_tz.localtime(obj.datum) if dj_tz.is_aware(obj.datum) else obj.datum
        date_str = local_dt.strftime("%d.%m.%Y")
        time_str = local_dt.strftime("%H:%M")

        trener_str = self.trener_jmeno(obj)
        format_str = obj.get_format_display()
        hraci_str = self.hraci_jmena(obj)
        edit_url = reverse("admin:core_trening_change", args=[obj.pk])

        summary_message = format_html(
            (
                'Trénink <a href="{}"><strong>{} {}</strong></a> uložen'
                ' · {} · {} · {}'
            ),
            edit_url,
            date_str,
            time_str,
            hraci_str or "—",
            trener_str or "—",
            format_str or "—",
        )

        response = super().response_add(request, obj, post_url_continue)

        storage = messages.get_messages(request)
        kept = []
        for m in storage:
            text = str(m.message)
            if "Položka typu Trénink" in text and "byla úspěšně přidána" in text and "Zkontrolujte prosím zadané údaje" not in text:
                continue
            kept.append(m)

        for m in kept:
            messages.add_message(request, m.level, m.message, extra_tags=m.extra_tags)

        messages.success(request, summary_message)

        return response

    def response_change(self, request, obj):
        response = super().response_change(request, obj)

        local_dt = dj_tz.localtime(obj.datum) if dj_tz.is_aware(obj.datum) else obj.datum
        date_str = local_dt.strftime("%d.%m.%Y")
        time_str = local_dt.strftime("%H:%M")

        trener_str = self.trener_jmeno(obj)
        format_str = obj.get_format_display()
        edit_url = reverse("admin:core_trening_change", args=[obj.pk])
        hraci_str = self.hraci_jmena(obj)
        summary_message = format_html(
            (
                'Trénink <a href="{}"><strong>{} {}</strong></a> upraven'
                ' · {} · {} · {}'
            ),
            edit_url,
            date_str,
            time_str,
            hraci_str or "—",
            trener_str or "—",
            format_str or "—",
        )

        storage = messages.get_messages(request)
        kept = []
        for m in storage:
            text = str(m.message)
            if "Položka" in text and "typu Trénink" in text and "byla úspěšně změněna" in text:
                continue
            kept.append(m)

        for m in kept:
            messages.add_message(request, m.level, m.message, extra_tags=m.extra_tags)

        messages.success(request, summary_message)
        return response

    def schedule_view(self, request):
        """Týdenní/denní rozvrh tréninků s filtry + rozložení překryvů do pruhů.
        Režim `rozvrh=staly` zobrazí stálý týdenní rozvrh (jen info, bez tréninků).
        """
        if not self.has_module_permission(request):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        q = request.GET
        try:
            base_date = datetime.strptime(q.get("date", ""), "%Y-%m-%d").date()
        except Exception:
            base_date = dj_tz.localdate()

        rozvrh_mode = (q.get("rozvrh") or "aktualni").strip().lower()
        trainer_id = q.get("trener") or ""
        # Přepínač Den/Týden je pryč – vždy týden (mobil má denní pager / pás dnů)
        sched = build_trening_schedule(
            base_date=base_date,
            rozvrh_mode=rozvrh_mode,
            trainer_id=trainer_id,
            mode="week",
        )

        ctx = dict(self.admin_site.each_context(request))
        if sched["is_staly"]:
            title = _("Stálý rozvrh")
        elif sched["is_predpokladany"]:
            title = _("Předpokládaný rozvrh")
        else:
            title = _("Rozvrh tréninků")
        ctx.update(sched)
        ctx.update({
            "title": title,
            "active_menu": "rozvrh",
        })
        return TemplateResponse(request, "admin/core/trening/kalendar.html", ctx)

    def schedule_materialize_view(self, request):
        """AJAX / POST: ze stálého rozvrhu vytvoří tréninky na dnes (nebo zadané datum)."""
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": _("Method not allowed.")}, status=405)

        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            payload = request.POST.dict()

        date_raw = (payload.get("date") or "").strip()
        target = None
        if date_raw:
            try:
                target = datetime.strptime(date_raw, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                return JsonResponse({"ok": False, "error": _("Neplatné datum.")}, status=400)

        trainer_raw = payload.get("trener") or ""
        result = materialize_for_date(target, trainer_id=trainer_raw or None)
        return JsonResponse(result)

    def schedule_predpokladany_skip_view(self, request):
        """AJAX: přeskočit stálý ghost / smazat jednorázový předpokládaný slot."""
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": _("Method not allowed.")}, status=405)

        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            payload = request.POST.dict()

        date_raw = (payload.get("date") or "").strip()
        try:
            day = datetime.strptime(date_raw, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatné datum.")}, status=400)

        predp_raw = payload.get("predpokladany_id")
        if predp_raw not in (None, ""):
            try:
                predp_id = int(predp_raw)
            except (TypeError, ValueError):
                return JsonResponse({"ok": False, "error": _("Neplatný slot.")}, status=400)
            deleted, _ = PredpokladanySlot.objects.filter(pk=predp_id, datum=day).delete()
            if not deleted:
                return JsonResponse({"ok": False, "error": _("Slot nenalezen.")}, status=404)
            return JsonResponse({"ok": True, "date": day.isoformat(), "predpokladany_id": predp_id})

        try:
            slot_id = int(payload.get("staly_slot_id") or payload.get("ghost_slot_id"))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatný slot.")}, status=400)

        slot = StalyRozvrhSlot.objects.filter(pk=slot_id).first()
        if not slot:
            return JsonResponse({"ok": False, "error": _("Slot nenalezen.")}, status=404)

        PredpokladanySkip.objects.get_or_create(datum=day, staly_slot=slot)
        return JsonResponse({"ok": True, "date": day.isoformat(), "staly_slot_id": slot_id})

    def schedule_staly_save_view(self, request):
        """AJAX: vytvořit / upravit slot stálého rozvrhu (bez zápisu tréninku/vyúčtování)."""
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": _("Method not allowed.")}, status=405)

        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            payload = request.POST.dict()

        slot_id = payload.get("id")
        move_only = bool(payload.get("move_only"))

        # Přesun: jen den + čas, ostatní zůstane v DB
        if move_only and slot_id not in (None, "", "null"):
            try:
                slot = StalyRozvrhSlot.objects.filter(pk=int(slot_id)).first()
            except (TypeError, ValueError):
                slot = None
            if slot is None:
                return JsonResponse({"ok": False, "error": _("Slot nenalezen.")}, status=404)
            try:
                dow = int(payload.get("dow"))
            except (TypeError, ValueError):
                return JsonResponse({"ok": False, "error": _("Neplatný den.")}, status=400)
            if dow < 0 or dow > 6:
                return JsonResponse({"ok": False, "error": _("Neplatný den.")}, status=400)
            time_raw = (payload.get("time") or "").strip()
            cas = None
            for time_fmt in ("%H:%M", "%H:%M:%S"):
                try:
                    cas = datetime.strptime(time_raw, time_fmt).time()
                    break
                except (TypeError, ValueError):
                    continue
            if cas is None:
                return JsonResponse({"ok": False, "error": _("Neplatný čas.")}, status=400)
            slot.den = dow
            slot.cas_od = cas
            slot.save(update_fields=["den", "cas_od"])
            return JsonResponse(self._staly_slot_json(slot))

        try:
            dow = int(payload.get("dow"))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatný den.")}, status=400)
        if dow < 0 or dow > 6:
            return JsonResponse({"ok": False, "error": _("Neplatný den.")}, status=400)

        time_raw = (payload.get("time") or "").strip()
        cas = None
        for time_fmt in ("%H:%M", "%H:%M:%S"):
            try:
                cas = datetime.strptime(time_raw, time_fmt).time()
                break
            except (TypeError, ValueError):
                continue
        if cas is None:
            return JsonResponse({"ok": False, "error": _("Neplatný čas.")}, status=400)

        try:
            delka = int(payload.get("delka_minut") or 60)
        except (TypeError, ValueError):
            delka = 60
        if delka not in {c[0] for c in SystemNastaveni.DELKA_MINUT_CHOICES}:
            if delka < 15 or delka > 300:
                return JsonResponse({"ok": False, "error": _("Neplatná délka.")}, status=400)

        trener_raw = payload.get("trener")
        try:
            trener = User.objects.filter(pk=int(trener_raw)).first()
        except (TypeError, ValueError):
            trener = None
        if trener is None:
            return JsonResponse({"ok": False, "error": _("Vyberte trenéra.")}, status=400)

        fmt = (payload.get("format") or "").strip()
        valid_formats = {c[0] for c in CenikFormat.choices() if c[0]}
        if fmt not in valid_formats:
            return JsonResponse({"ok": False, "error": _("Vyberte typ tréninku.")}, status=400)

        kurt = (payload.get("kurt") or "").strip()
        valid_kurty = {c[0] for c in Cenik.Kurt.choices if c[0]}
        if kurt not in valid_kurty:
            return JsonResponse({"ok": False, "error": _("Vyberte kurt.")}, status=400)

        poznamka = (payload.get("poznamka") or "").strip()[:240]
        hraci_raw = payload.get("hraci") or []
        if isinstance(hraci_raw, str):
            hraci_raw = [x for x in hraci_raw.split(",") if x.strip()]
        hrac_ids = []
        for raw in hraci_raw:
            try:
                hrac_ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        hraci = list(Hrac.objects.filter(pk__in=hrac_ids)) if hrac_ids else []

        slot = None
        if slot_id not in (None, "", "null"):
            try:
                slot = StalyRozvrhSlot.objects.filter(pk=int(slot_id)).first()
            except (TypeError, ValueError):
                slot = None
            if slot is None:
                return JsonResponse({"ok": False, "error": _("Slot nenalezen.")}, status=404)

        if slot is None:
            slot = StalyRozvrhSlot()

        slot.den = dow
        slot.cas_od = cas
        slot.delka_minut = delka
        slot.trener = trener
        slot.format = fmt
        slot.kurt = kurt
        slot.poznamka = poznamka
        slot.save()
        slot.hraci.set(hraci)

        return JsonResponse(self._staly_slot_json(slot))

    def _staly_slot_json(self, slot: StalyRozvrhSlot) -> dict:
        dur = int(slot.delka_minut or 60)
        end_t = (datetime.combine(date.min, slot.cas_od) + timedelta(minutes=dur)).time()
        fmt_label = slot.get_format_display()
        players = []
        player_ids = []
        for hrac in slot.hraci.all():
            label = (hrac.prijmeni or "").strip() or (hrac.jmeno or "").strip() or hrac.cele_jmeno
            players.append(label)
            player_ids.append(hrac.pk)
        return {
            "ok": True,
            "id": slot.pk,
            "dow": int(slot.den),
            "time": slot.cas_od.strftime("%H:%M"),
            "delka_minut": dur,
            "trener": slot.trener_id or "",
            "format": slot.format or "",
            "kurt": slot.kurt or "",
            "poznamka": slot.poznamka or "",
            "hraci": player_ids,
            "title": ", ".join(players) or fmt_label or "—",
            "sub": f"{slot.cas_od.strftime('%H:%M')}–{end_t.strftime('%H:%M')}",
            "names": players,
            "fmt_label": fmt_label,
        }

    def schedule_staly_delete_view(self, request, slot_id: int):
        """AJAX: smazat slot stálého rozvrhu."""
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": _("Method not allowed.")}, status=405)
        deleted, _ = StalyRozvrhSlot.objects.filter(pk=slot_id).delete()
        if not deleted:
            return JsonResponse({"ok": False, "error": _("Slot nenalezen.")}, status=404)
        return JsonResponse({"ok": True, "id": slot_id})

    def schedule_quick_add_view(self, request):
        """AJAX: rychlé přidání tréninku z rozvrhu (bez odchodu z kalendáře)."""
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": _("Method not allowed.")}, status=405)

        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            payload = request.POST.dict()

        date_raw = (payload.get("date") or "").strip()
        time_raw = (payload.get("time") or "").strip()
        trener_raw = payload.get("trener")
        delka_raw = payload.get("delka_minut", 60)
        fmt = (payload.get("format") or "").strip()
        kurt = (payload.get("kurt") or "").strip()
        poznamka = (payload.get("poznamka") or "").strip()[:240]
        hraci_raw = payload.get("hraci") or []

        try:
            day = datetime.strptime(date_raw, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatné datum.")}, status=400)

        cas = None
        for time_fmt in ("%H:%M", "%H:%M:%S"):
            try:
                cas = datetime.strptime(time_raw, time_fmt).time()
                break
            except (TypeError, ValueError):
                continue
        if cas is None:
            return JsonResponse({"ok": False, "error": _("Neplatný čas.")}, status=400)

        try:
            trener = User.objects.get(pk=int(trener_raw))
        except (TypeError, ValueError, User.DoesNotExist):
            return JsonResponse({"ok": False, "error": _("Vyberte trenéra.")}, status=400)

        try:
            delka = int(delka_raw)
        except (TypeError, ValueError):
            delka = 60
        allowed_delka = {c[0] for c in SystemNastaveni.DELKA_MINUT_CHOICES}
        if delka not in allowed_delka:
            delka = 60

        defaults = SystemNastaveni.training_defaults(for_date=day, user=request.user)
        if not fmt:
            return JsonResponse({"ok": False, "error": _("Vyberte typ tréninku.")}, status=400)
        if not kurt:
            kurt = (defaults.get("kurt") or "").strip()
        if not kurt:
            return JsonResponse({"ok": False, "error": _("Vyberte kurt.")}, status=400)
        if Cenik.je_sluzba(fmt, kurt):
            kurt = Cenik.Kurt.SLUZBA
            delka = 60

        hrac_ids = []
        if isinstance(hraci_raw, str):
            hraci_raw = [x for x in hraci_raw.split(",") if x.strip()]
        for item in hraci_raw:
            try:
                hrac_ids.append(int(item))
            except (TypeError, ValueError):
                continue
        hraci = list(Hrac.objects.filter(pk__in=hrac_ids))

        as_projected = bool(
            payload.get("as_projected")
            or (payload.get("mode") or "").strip() == "predpokladany"
        )
        today = dj_tz.localdate()
        save_as_ghost = as_projected and day >= today

        def _slug(s: str) -> str:
            s = (s or "").strip().lower()
            repl = (("á", "a"), ("č", "c"), ("ď", "d"), ("é", "e"), ("ě", "e"), ("í", "i"),
                    ("ň", "n"), ("ó", "o"), ("ř", "r"), ("š", "s"), ("ť", "t"), ("ú", "u"),
                    ("ů", "u"), ("ý", "y"), ("ž", "z"))
            for a, b in repl:
                s = s.replace(a, b)
            s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
            if not s or not s[0].isalpha():
                s = f"f-{s or 'neznamy'}"
            return s

        try:
            hours = SystemNastaveni.load().schedule_hours()
        except Exception:
            hours = list(range(6, 23))
        day_start_min = (hours[0] if hours else 6) * 60
        start_min = cas.hour * 60 + cas.minute
        offset = max(0, start_min - day_start_min)

        names = []
        for h in hraci:
            label = (h.prijmeni or "").strip() or (h.jmeno or "").strip() or h.cele_jmeno
            names.append(label)

        if save_as_ghost:
            predp_id = payload.get("predpokladany_id")
            ghost_staly_raw = payload.get("ghost_slot_id") or payload.get("staly_slot_id")
            zdroj_staly = None
            if ghost_staly_raw not in (None, ""):
                try:
                    zdroj_staly = StalyRozvrhSlot.objects.filter(pk=int(ghost_staly_raw)).first()
                except (TypeError, ValueError):
                    zdroj_staly = None

            with transaction.atomic():
                slot = None
                if predp_id not in (None, ""):
                    try:
                        slot = PredpokladanySlot.objects.filter(pk=int(predp_id)).first()
                    except (TypeError, ValueError):
                        slot = None
                if slot is None:
                    slot = PredpokladanySlot(datum=day)
                slot.datum = day
                slot.cas_od = cas
                slot.delka_minut = delka
                slot.trener = trener
                slot.format = fmt
                slot.kurt = kurt
                slot.poznamka = poznamka
                if zdroj_staly and not slot.zdroj_staly_id:
                    slot.zdroj_staly = zdroj_staly
                slot.save()
                slot.hraci.set(hraci)
                if zdroj_staly:
                    PredpokladanySkip.objects.get_or_create(datum=day, staly_slot=zdroj_staly)

            end_t = (datetime.combine(date.min, cas) + timedelta(minutes=delka)).time()
            fmt_label = slot.get_format_display()
            fmt_slug = _slug(fmt_label)
            fmt_code = (slot.format or "").lower().replace("_", "-")
            sub = f"{cas.strftime('%H:%M')}–{end_t.strftime('%H:%M')}"
            title = ", ".join(names) or "—"
            return JsonResponse(
                {
                    "ok": True,
                    "projected": True,
                    "id": f"predp-{slot.pk}",
                    "predpokladany_id": slot.pk,
                    "event": {
                        "id": f"predp-{slot.pk}",
                        "date": day.isoformat(),
                        "offset_min": offset,
                        "dur_min": delka,
                        "names": names,
                        "title": title,
                        "sub": sub,
                        "fmt": fmt_slug,
                        "fmt_code": fmt_code,
                        "fmt_label": fmt_label,
                        "is_ghost": True,
                        "predpokladany_id": slot.pk,
                    },
                }
            )

        dt = datetime.combine(day, cas)
        if settings.USE_TZ:
            dt = dj_tz.make_aware(dt, dj_tz.get_current_timezone())

        obj_id = payload.get("id")
        trening = None
        if obj_id not in (None, "", "null"):
            try:
                trening = Trening.objects.filter(pk=int(obj_id)).first()
            except (TypeError, ValueError):
                trening = None
            if trening is None:
                return JsonResponse({"ok": False, "error": _("Trénink nenalezen.")}, status=404)

        with transaction.atomic():
            if trening is None:
                trening = Trening.objects.create(
                    trener=trener,
                    datum=dt,
                    delka_minut=delka,
                    format=fmt,
                    kurt=kurt,
                    poznamka=poznamka,
                )
                for hrac in hraci:
                    Dochazka.objects.create(trening=trening, hrac=hrac, prisel=True)
            else:
                trening.trener = trener
                trening.datum = dt
                trening.delka_minut = delka
                trening.format = fmt
                trening.kurt = kurt
                trening.poznamka = poznamka
                trening.save()
                existing = {d.hrac_id: d for d in trening.dochazky.all()}
                wanted = {h.pk for h in hraci}
                for hrac_id, doch in list(existing.items()):
                    if hrac_id not in wanted:
                        doch.delete()
                for hrac in hraci:
                    if hrac.pk not in existing:
                        Dochazka.objects.create(trening=trening, hrac=hrac, prisel=True)

            # Úprava ghostu ze stálého v minulosti: přeskočit noční zápis stálého
            ghost_staly_raw = payload.get("ghost_slot_id") or payload.get("staly_slot_id")
            if ghost_staly_raw not in (None, ""):
                try:
                    staly = StalyRozvrhSlot.objects.filter(pk=int(ghost_staly_raw)).first()
                    if staly:
                        PredpokladanySkip.objects.get_or_create(datum=day, staly_slot=staly)
                except (TypeError, ValueError):
                    pass

        local = dj_tz.localtime(trening.datum) if dj_tz.is_aware(trening.datum) else trening.datum
        end_local = local + timedelta(minutes=int(trening.delka_minut))
        fmt_label = trening.get_format_display()
        fmt_slug = _slug(fmt_label)
        fmt_code = (trening.format or "").lower().replace("_", "-")
        sub = f"{local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}"
        title = ", ".join(names) or "—"

        return JsonResponse(
            {
                "ok": True,
                "id": trening.pk,
                "change_url": reverse("admin:core_trening_change", args=[trening.pk]),
                "event": {
                    "id": trening.pk,
                    "date": local.strftime("%Y-%m-%d"),
                    "offset_min": offset,
                    "dur_min": int(trening.delka_minut),
                    "names": names,
                    "title": title,
                    "sub": sub,
                    "fmt": fmt_slug,
                    "fmt_code": fmt_code,
                    "fmt_label": fmt_label,
                    "trener_id": trening.trener_id or "",
                    "format": trening.format or "",
                    "kurt": trening.kurt or "",
                    "poznamka": trening.poznamka or "",
                    "hraci_ids": [h.pk for h in hraci],
                    "time": local.strftime("%H:%M"),
                },
            }
        )

    def schedule_delete_view(self, request):
        """AJAX: smazat trénink přímo z rozvrhu."""
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": _("Method not allowed.")}, status=405)
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            payload = request.POST.dict()
        try:
            obj_id = int(payload.get("id"))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatný trénink.")}, status=400)
        deleted, _ = Trening.objects.filter(pk=obj_id).delete()
        if not deleted:
            return JsonResponse({"ok": False, "error": _("Trénink nenalezen.")}, status=404)
        return JsonResponse({"ok": True, "id": obj_id})

    def schedule_move_view(self, request):
        """AJAX: přesun existujícího tréninku v rozvrhu (den / čas)."""
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": _("Method not allowed.")}, status=405)

        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            payload = request.POST.dict()

        try:
            trening_id = int(payload.get("id"))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatný trénink.")}, status=400)

        date_raw = (payload.get("date") or "").strip()
        time_raw = (payload.get("time") or "").strip()

        try:
            day = datetime.strptime(date_raw, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatné datum.")}, status=400)

        cas = None
        for time_fmt in ("%H:%M", "%H:%M:%S"):
            try:
                cas = datetime.strptime(time_raw, time_fmt).time()
                break
            except (TypeError, ValueError):
                continue
        if cas is None:
            return JsonResponse({"ok": False, "error": _("Neplatný čas.")}, status=400)

        trening = Trening.objects.filter(pk=trening_id).first()
        if not trening:
            return JsonResponse({"ok": False, "error": _("Trénink nenalezen.")}, status=404)

        dt = datetime.combine(day, cas)
        if settings.USE_TZ:
            dt = dj_tz.make_aware(dt, dj_tz.get_current_timezone())

        trening.datum = dt
        trening.save(update_fields=["datum"])

        local = dj_tz.localtime(trening.datum) if dj_tz.is_aware(trening.datum) else trening.datum
        end_local = local + timedelta(minutes=int(trening.delka_minut or 60))
        sub = f"{local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}"

        return JsonResponse(
            {
                "ok": True,
                "id": trening.pk,
                "date": local.strftime("%Y-%m-%d"),
                "sub": sub,
                "offset_min": None,
            }
        )

    def treneri_summary_view(self, request):
        if not self.has_module_permission(request):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        dfrom, dto = _period_from_request(request)
        search_q = (request.GET.get("q") or "").strip()

        base_qs = Trening.objects.all()
        if dfrom:
            base_qs = base_qs.filter(datum__date__gte=dfrom)
        if dto:
            base_qs = base_qs.filter(datum__date__lte=dto)

        # Admin / provozovatel → všichni; trenér / správce → jen sebe
        if can_view_all_treneri(request.user):
            trener_ids = _all_trener_ids()
        else:
            trener_ids = {request.user.pk}
        users = {
            u.id: u
            for u in User.objects.filter(pk__in=trener_ids).order_by(
                "last_name", "first_name", "username"
            )
        }
        if search_q:
            needle = search_q.casefold()
            users = {
                uid: u
                for uid, u in users.items()
                if needle in trener_label(u).casefold()
                or needle in (u.get_full_name() or "").casefold()
                or needle in (u.username or "").casefold()
                or needle in (u.first_name or "").casefold()
                or needle in (u.last_name or "").casefold()
            }
        rate_lookup = TrenerRateLookup(list(users.keys()))

        rows = []
        total_pocet = 0
        total_hodiny = Decimal("0.00")
        total_castka = Decimal("0.00")

        for uid in sorted(users.keys(), key=lambda i: trener_label(users[i]).casefold()):
            u = users[uid]
            tqs = list(
                base_qs.filter(trener_id=uid).order_by("datum").prefetch_related(_dochazka_prefetch())
            )
            stats = _aggregate_trener_trainings(u, tqs, rate_lookup)
            total_pocet += stats["pocet"]
            total_hodiny += stats["hodiny_raw"]
            total_castka += stats["castka_raw"]

            q_params = []
            if dfrom:
                q_params.append(("from", dfrom.isoformat()))
            if dto:
                q_params.append(("to", dto.isoformat()))
            if search_q:
                q_params.append(("q", search_q))
            detail_qs = ("?" + urlencode(q_params)) if q_params else ""

            rows.append({
                "trener": trener_label(u),
                "detail_url": reverse("admin:core_treneri_detail", args=[u.id]) + detail_qs,
                "pocet": stats["pocet"],
                "hodiny": stats["hodiny"],
                "castka": stats["castka"],
            })

        from types import SimpleNamespace

        cl = SimpleNamespace(
            result_count=len(rows),
            opts=SimpleNamespace(verbose_name_plural=_("Trenéři")),
        )
        ctx = dict(
            self.admin_site.each_context(request),
            title=_("Trenéři – souhrn"),
            rows=rows,
            total_pocet=total_pocet,
            total_hodiny=f"{total_hodiny:.2f}",
            total_castka=f"{total_castka.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.0f} Kč",
            dfrom=dfrom,
            dto=dto,
            search_q=search_q,
            active_menu="treneri",
            cl=cl,
        )
        return TemplateResponse(request, "admin/core/trening/treneri_summary.html", ctx)

    def trener_detail_view(self, request, user_id: int):
        from django.core.exceptions import PermissionDenied

        if not self.has_module_permission(request):
            raise PermissionDenied
        # Trenér / správce: cizí detail v seznamu není – přesměrovat na souhrn
        if not can_view_all_treneri(request.user) and int(user_id) != request.user.pk:
            return redirect(reverse("admin:core_treneri_summary"))

        u = User.objects.get(pk=user_id)
        can_manage_sazby = can_view_all_treneri(request.user)

        if request.method == "POST" and "_nastavit_sazbu" in request.POST:
            if not can_manage_sazby:
                return redirect(request.get_full_path())
            date_raw = (request.POST.get("rate_from") or "").strip()
            amt_raw = (request.POST.get("rate_amount") or "").strip()

            try:
                eff_from = datetime.strptime(date_raw, "%Y-%m-%d").date()
            except Exception:
                messages.error(request, _("Neplatné datum 'Od'."))
                return redirect(request.get_full_path())

            try:
                amount = Decimal(amt_raw.replace(",", "."))
                if amount <= 0:
                    raise ValueError()
            except Exception:
                messages.error(request, _("Neplatná částka sazby."))
                return redirect(request.get_full_path())

            try:
                TrenerSazba.set_rate_from(user=u, effective_from=eff_from, rate=amount)
            except ValidationError as e:
                messages.error(request, f"Sazbu se nepodařilo nastavit: {e}")
            else:
                messages.success(
                    request,
                    f"Sazba {amount:.0f} Kč/h nastavena od {eff_from.strftime('%d.%m.%Y')}."
                )
            return redirect(request.get_full_path())

        if request.method == "POST" and "_nastavit_vyplet" in request.POST:
            if not can_manage_sazby:
                return redirect(request.get_full_path())
            amt_raw = (request.POST.get("vyplet_amount") or "").strip()
            try:
                amount = Decimal(amt_raw.replace(",", "."))
                if amount < 0:
                    raise ValueError()
            except Exception:
                messages.error(request, _("Neplatná částka sazby za výplet."))
                return redirect(request.get_full_path())

            profil, _created = TrenerProfil.objects.get_or_create(
                user=u,
                defaults={
                    "sazba_za_hodinu": Decimal("500.00"),
                    "sazba_za_vyplet": amount,
                },
            )
            profil.sazba_za_vyplet = amount
            profil.save(update_fields=["sazba_za_vyplet"])
            messages.success(
                request,
                _("Sazba za výplet nastavena na %(amount)s Kč.")
                % {"amount": f"{amount:.0f}"},
            )
            return redirect(request.get_full_path())

        dfrom = _parse_admin_date(request.GET.get("from", ""))
        dto = _parse_admin_date(request.GET.get("to", ""))
        has_filter = bool(dfrom or dto)

        rate_lookup = TrenerRateLookup([u.id])

        tqs = Trening.objects.filter(trener=u)
        if dfrom:
            tqs = tqs.filter(datum__date__gte=dfrom)
        if dto:
            tqs = tqs.filter(datum__date__lte=dto)
        trainings = list(
            tqs.prefetch_related(_dochazka_prefetch()).order_by("-datum")
        )

        stats, training_months = _build_trener_training_stats(u, trainings, rate_lookup)
        if has_filter:
            finance = _trener_financial_overview(u, rate_lookup)
        else:
            finance = _trener_financial_overview(u, rate_lookup, stats=stats)

        rate_today = rate_lookup.for_user_date(u.id, dj_tz.now())
        rate_today_amount = f"{rate_today:.0f}"
        rate_today_date = dj_tz.localdate().strftime("%Y-%m-%d")
        rate_form_initial_date = rate_today_date
        vyplet_amount = f"{rate_lookup.vyplet_for_user(u.id):.0f}"

        sazby = (
            TrenerSazba.objects.filter(user=u).order_by("-platnost_od")
            .values("id", "platnost_od", "platnost_do", "sazba_za_hodinu")
        )
        mesice = _enrich_mesice_with_payments(u, stats["mesice"])

        platba_add_url = reverse("admin:core_trenerplatba_add")
        if finance["dluzna_raw"] > 0:
            platba_add_url += f"?user={u.id}&amount={finance['dluzna_raw']:.0f}"
        else:
            platba_add_url += f"?user={u.id}"

        ctx = dict(
            self.admin_site.each_context(request),
            title=_("Trenér – %(name)s") % {"name": trener_label(u)},
            trener=u,
            trener_display_name=trener_label(u),
            pocet=stats["pocet"],
            total_hours=f"{stats['hodiny']} h",
            total_castka=stats["castka"],
            celkova_castka=finance["celkova_castka"],
            mesic_label=finance["mesic_label"],
            mesic_castka=finance["mesic_castka"],
            dluzna_castka=finance["dluzna_castka"],
            mesice=mesice,
            platba_add_url=platba_add_url,
            training_months=training_months,
            rate_today_amount=rate_today_amount,
            rate_today_date=rate_today_date,
            rate_form_initial_date=rate_form_initial_date,
            vyplet_amount=vyplet_amount,
            sazby=sazby,
            can_manage_sazby=can_manage_sazby,
            summary_url=reverse("admin:core_treneri_summary"),
            dfrom=dfrom, dto=dto,
            active_menu="treneri",
        )
        return TemplateResponse(request, "admin/core/trening/trener_detail.html", ctx)
