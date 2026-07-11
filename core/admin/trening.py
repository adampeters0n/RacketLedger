"""Trening admin."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, time, timedelta
import json
import re

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone as dj_tz
from django.utils.html import format_html, escape
from django.utils.safestring import mark_safe
from django import forms
from django.forms import formset_factory

from ..admin_utils import CZECH_MONTHS_NOMINATIVE, format_czech_datetime, month_range, parse_czech_date_parts, pretty_username, trener_label
from ..forms import (
    AddDayForm,
    AdminSplitDateTimeWithDatalist,
    CopyTrainingsForm,
    TrainingSlotForm,
    TrainingSlotFormSet,
)
from ..models import Cenik, Dochazka, Hrac, TrenerPlatba, TrenerSazba, Trening, sazba_trenera_k_datu
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


def _training_row_dict(user, training):
    dt = dj_tz.localtime(training.datum) if dj_tz.is_aware(training.datum) else training.datum
    hours = (Decimal(training.delka_minut) / Decimal(60)).quantize(Decimal("0.01"))
    rate = sazba_trenera_k_datu(user, dt)
    castka = (hours * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    hraci = ", ".join(
        d.hrac.jmeno
        for d in training.dochazky.select_related("hrac").filter(prisel=True)
    ) or "—"
    return {
        "datum": dt.strftime("%d.%m.%Y"),
        "cas": dt.strftime("%H:%M"),
        "format": training.get_format_display(),
        "kurt": training.get_kurt_display(),
        "hraci": hraci,
        "hodiny": f"{hours:.2f}",
        "sazba": f"{rate:.0f} Kč/h",
        "castka": f"{castka:.0f} Kč",
        "trening_change_url": reverse("admin:core_trening_change", args=[training.id]),
        "month_key": (dt.year, dt.month),
    }


def _group_trainings_by_month(user, trainings):
    """Seskupí tréninky po měsících; aktuální měsíc (nebo nejnovější) je rozbalený."""
    groups = defaultdict(list)
    for t in trainings:
        row = _training_row_dict(user, t)
        groups[row["month_key"]].append(row)

    today = dj_tz.localdate()
    current_key = (today.year, today.month)
    sorted_keys = sorted(groups.keys(), reverse=True)
    open_key = current_key if current_key in groups else (sorted_keys[0] if sorted_keys else None)

    months = []
    for key in sorted_keys:
        year, month = key
        rows = groups[key]
        months.append({
            "label": f"{CZECH_MONTHS_NOMINATIVE[month]} {year}",
            "rows": rows,
            "pocet": len(rows),
            "is_open": key == open_key,
        })
    return months


def _all_trener_ids():
    """Všichni trenéři v systému (historie tréninků + nastavené sazby)."""
    ids = set(Trening.objects.values_list("trener_id", flat=True))
    ids.update(TrenerSazba.objects.values_list("user_id", flat=True))
    ids.discard(None)
    return ids


def _aggregate_trener_trainings(user, trainings):
    """Součty a měsíční rozpis z iterable tréninků jednoho trenéra."""
    total_min = 0
    total_castka = Decimal("0.00")
    pocet = 0
    monthly = defaultdict(lambda: {"pocet": 0, "minuty": 0, "castka": Decimal("0.00")})

    for t in trainings:
        dt = dj_tz.localtime(t.datum) if dj_tz.is_aware(t.datum) else t.datum
        rate = sazba_trenera_k_datu(user, dt)
        hours_val = (Decimal(t.delka_minut) / Decimal(60)).quantize(Decimal("0.01"))
        castka = (hours_val * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        pocet += 1
        total_min += t.delka_minut
        total_castka += castka

        key = (dt.year, dt.month)
        monthly[key]["pocet"] += 1
        monthly[key]["minuty"] += t.delka_minut
        monthly[key]["castka"] += castka

    hodiny = (Decimal(total_min) / Decimal(60)).quantize(Decimal("0.01"))
    mesice = []
    for (year, month), data in sorted(monthly.items(), reverse=True):
        m_hours = (Decimal(data["minuty"]) / Decimal(60)).quantize(Decimal("0.01"))
        m_castka = data["castka"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        mesice.append({
            "label": f"{CZECH_MONTHS_NOMINATIVE[month]} {year}",
            "pocet": data["pocet"],
            "hodiny": f"{m_hours:.2f}",
            "castka": f"{m_castka:.0f} Kč",
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


def _trener_financial_overview(user):
    """Celková odehraná částka, aktuální měsíc a dlužná částka (bez filtru období)."""
    all_trainings = list(Trening.objects.filter(trener=user).order_by("datum"))
    all_stats = _aggregate_trener_trainings(user, all_trainings)
    celkem = all_stats["castka_raw"]

    today = dj_tz.localdate()
    mesic_castka = all_stats["monthly_raw"].get(
        (today.year, today.month), Decimal("0.00")
    )

    zaplaceno = Decimal(
        TrenerPlatba.objects.filter(user=user).aggregate(s=Sum("castka"))["s"] or 0
    )
    dluzna = (celkem - zaplaceno).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "celkova_castka": _format_kc(celkem),
        "mesic_label": f"{CZECH_MONTHS_NOMINATIVE[today.month]} {today.year}",
        "mesic_castka": _format_kc(mesic_castka),
        "dluzna_castka": _format_kc(dluzna),
    }


def _week_start(d):
    return d - timedelta(days=d.weekday())


def _trainings_for_copy(source_date, target_date, scope, trener=None):
    """
  Načte tréninky ze zdrojového dne/týdne a připraví data pro formulář slotů.
  scope: 'day' | 'week'
  """
    if scope == CopyTrainingsForm.SCOPE_WEEK:
        source_start = _week_start(source_date)
        target_start = _week_start(target_date)
        date_from = source_start
        date_to = source_start + timedelta(days=6)
    else:
        source_start = source_date
        date_from = source_date
        date_to = source_date

    start_dt = dj_tz.make_aware(datetime.combine(date_from, time.min))
    end_dt = dj_tz.make_aware(datetime.combine(date_to, time.max))

    qs = (
        Trening.objects
        .filter(datum__range=(start_dt, end_dt))
        .select_related("trener")
        .prefetch_related("dochazky__hrac")
        .order_by("datum")
    )
    if trener:
        qs = qs.filter(trener_id=trener.pk if hasattr(trener, "pk") else trener)

    slots = []
    for t in qs:
        local = dj_tz.localtime(t.datum) if dj_tz.is_aware(t.datum) else t.datum
        src_d = local.date()
        if scope == CopyTrainingsForm.SCOPE_WEEK:
            day_offset = (src_d - source_start).days
            slot_datum = _week_start(target_date) + timedelta(days=day_offset)
        else:
            slot_datum = None

        hraci = list(t.hraci.all())
        slots.append({
            "cas": local.time().replace(second=0, microsecond=0),
            "delka_minut": t.delka_minut,
            "format": t.format,
            "kurt": t.kurt,
            "poznamka": t.poznamka or "",
            "hraci": hraci,
            "slot_datum": slot_datum,
            "trener": t.trener,
        })
    return slots


def _slot_formset_for_copy(initial_slots):
    """Formset s dostatečným počtem prázdných slotů pro načtená data."""
    from ..forms import TrainingSlotFormSetBase

    count = max(len(initial_slots), 1)
    extra = max(5, count + 2)
    FormSetClass = formset_factory(
        TrainingSlotForm,
        formset=TrainingSlotFormSetBase,
        extra=extra,
        max_num=50,
        min_num=1,
        validate_min=True,
    )
    return FormSetClass(prefix="slots", initial=initial_slots)


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
    title = "Trenéra"
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


class TreningFormatFilter(admin.ChoicesFieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.title = "Formátu"


class SezonaListFilter(admin.SimpleListFilter):
    title = "Sezóny"
    parameter_name = "sezona"

    def lookups(self, request, model_admin):
        return [
            (Cenik.Kurt.VENEK, "Léto"),
            (Cenik.Kurt.HALA, "Zima"),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            return queryset.filter(kurt=val)
        return queryset


class TreningDatumFilter(admin.DateFieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.title = "Data"
        if self.links:
            links = list(self.links)
            links[0] = ("Vše", links[0][1])
            self.links = links


@admin.register(Trening)
class TreningAdmin(admin.ModelAdmin):
    change_form_template = "admin/core/trening/change_form.html"
    add_form_template = "admin/core/trening/add_form.html"
    change_list_template = "admin/core/trening/change_list.html"
    list_display = ("datum_display", "hraci_jmena", "trener_jmeno", "format_display", "castka_na_hrace_kc")
    list_filter = (
        TrenerListFilter,
        ("format", TreningFormatFilter),
        SezonaListFilter,
        ("datum", TreningDatumFilter),
    )
    search_fields = (
        "trener__username", "trener__first_name", "trener__last_name",
        "poznamka", "dochazky__hrac__jmeno"
    )
    list_per_page = 50
    inlines = [DochazkaInline]
    actions = ["znovu_zpracovat_uctovani"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "trener":
            formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)

            def label_from_instance(user):
                full = (getattr(user, "get_full_name", None) or (lambda: ""))().strip()
                return full or pretty_username(user.username)

            formfield.label_from_instance = label_from_instance
            return formfield

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not form.is_valid():
            messages.error(request, f"Chyba v hlavním formuláři: {form.errors}")
        super().save_model(request, obj, form, change)

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

    def get_form(self, request, obj=None, **kwargs):
        Form = super().get_form(request, obj, **kwargs)
        if "delka_minut" in Form.base_fields:
            field = Form.base_fields["delka_minut"]
            field.label = "Délka (hodiny)"
            CHOICES = [(30, "30 min"), (45, "45 min"), (60, "1 h"), (90, "1,5 h"), (120, "2 h"), (150, "2,5 h"), (180, "3 h")]
            field.widget = forms.Select(choices=CHOICES)
            field.help_text = ""
            if obj is None: field.initial = 60
        return Form

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "datum":
            # Na stránce Přidat trénink funkčně stejné buňky jako add-day: type=date + type=time (nativní pickery)
            if request.path.rstrip("/").endswith("/add"):
                w = forms.SplitDateTimeWidget(
                    date_attrs={"type": "date", "class": "add-day-datum-input vDateField"},
                    time_attrs={"type": "time", "class": "vTimeField", "placeholder": "např. 13:00"},
                )
            else:
                w = AdminSplitDateTimeWithDatalist()
            kwargs["widget"] = w
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def _add_form_context(self, request, day_form, formset, copy_form=None, copy_loaded=False, copy_scope=None, copy_slot_count=0, copy_slots_players_json=None, copy_hraci_lists=None):
        players_json_list = copy_slots_players_json or []
        hraci_lists = copy_hraci_lists or []
        slots_render = []
        copy_hidden_trener_id = ""
        copy_hidden_day_datum = ""
        if copy_loaded:
            trener_val = day_form.initial.get("trener")
            if trener_val is not None:
                copy_hidden_trener_id = getattr(trener_val, "pk", trener_val)
            datum_val = day_form.initial.get("datum")
            if datum_val is not None and hasattr(datum_val, "isoformat"):
                copy_hidden_day_datum = datum_val.isoformat()

        for i, form in enumerate(formset):
            if copy_loaded:
                hraci_initial = hraci_lists[i] if i < len(hraci_lists) else list(form.initial.get("hraci") or [])
                slots_render.append({
                    "form": form,
                    "index": i,
                    "hidden": i >= copy_slot_count,
                    "players_json": players_json_list[i] if i < len(players_json_list) else "[]",
                    "hraci_initial": hraci_initial,
                })
            else:
                slots_render.append({
                    "form": form,
                    "index": i,
                    "hidden": i > 0,
                    "players_json": None,
                    "hraci_initial": [],
                })
        return {
            **self.admin_site.each_context(request),
            "title": "Trénink: přidat",
            "opts": self.model._meta,
            "day_form": day_form,
            "formset": formset,
            "slots_render": slots_render,
            "copy_form": copy_form,
            "copy_loaded": copy_loaded,
            "copy_scope": copy_scope or CopyTrainingsForm.SCOPE_DAY,
            "copy_slot_count": copy_slot_count,
            "copy_slots_players_json": players_json_list,
            "copy_hidden_trener_id": copy_hidden_trener_id,
            "copy_hidden_day_datum": copy_hidden_day_datum,
        }

    def add_view(self, request, form_url="", extra_context=None):
        """Na /add/ zobrazit formulář den + sloty + Přidat Trénink; POST zpracovat zde."""
        AddDayFormClass = AddDayForm
        FormSetClass = TrainingSlotFormSet
        is_add_form = request.path.rstrip("/").endswith("/add") and self.add_form_template

        if is_add_form and request.method == "POST" and ("day-datum" in request.POST or "slots-TOTAL_FORMS" in request.POST):
            day_form = AddDayFormClass(request.POST, prefix="day")
            formset = _training_formset_from_request(post_data=request.POST)
            copy_scope = request.POST.get("copy_scope") or CopyTrainingsForm.SCOPE_DAY
            if day_form.is_valid() and formset.is_valid():
                default_trener = day_form.cleaned_data.get("trener")
                if not default_trener:
                    messages.error(request, "Vyberte trenéra pro celý den.")
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
                            trening = Trening.objects.create(
                                trener=slot_trener,
                                datum=dt,
                                delka_minut=cd["delka_minut"],
                                format=cd["format"] or Cenik.Format.DVOJICE_C,
                                kurt=cd["kurt"] or Cenik.Kurt.HALA,
                                poznamka=(cd.get("poznamka") or "")[:240],
                            )
                            hraci = cd.get("hraci") or []
                            for hrac in hraci:
                                Dochazka.objects.create(trening=trening, hrac=hrac, prisel=True)
                            cas_str = cd["cas"].strftime("%H:%M")
                            jmena = [getattr(h, "jmeno", str(h)) for h in hraci]
                            datum_str = slot_datum.strftime("%d.%m.%Y")
                            created_items.append((datum_str, cas_str, ", ".join(jmena) if jmena else "—", trening.pk))
                            created += 1
                    if created:
                        trener_str = (getattr(default_trener, "get_full_name", lambda: "")() or getattr(default_trener, "username", ""))
                        parts = [
                            format_html("<strong>Trenér:</strong> {}", escape(trener_str)),
                            format_html("Bylo uloženo {} tréninků:", created),
                        ]
                        for datum_str, cas_str, hraci_str, trening_pk in created_items:
                            change_url = reverse("admin:core_trening_change", args=[trening_pk])
                            parts.append(format_html(
                                '  • <a href="{}"><strong>{} {}</strong></a> – {}',
                                change_url, escape(datum_str), escape(cas_str), escape(hraci_str),
                            ))
                        msg_html = mark_safe("<br>".join(str(p) for p in parts))
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
            context = self._add_form_context(
                request, day_form, formset,
                copy_form=CopyTrainingsForm(prefix="copy", initial={
                    "source_date": request.POST.get("copy-source_date") or request.GET.get("copy-source_date"),
                    "target_date": day_form.data.get("day-datum") if hasattr(day_form, "data") else None,
                    "scope": copy_scope,
                }),
                copy_scope=copy_scope,
                copy_loaded=bool(request.POST.get("copy_loaded")),
                copy_slot_count=int(request.POST.get("copy_slot_count") or 0),
            )
            return TemplateResponse(request, self.add_form_template, context)

        if is_add_form and request.method == "GET":
            copy_form = None
            copy_loaded = False
            copy_scope = CopyTrainingsForm.SCOPE_DAY
            copy_slot_count = 0
            copy_slots_players_json = []
            copy_hraci_lists = []

            if request.GET.get("copy"):
                copy_form = CopyTrainingsForm(request.GET, prefix="copy")
                if copy_form.is_valid():
                    source_date = copy_form.cleaned_data["source_date"]
                    target_date = copy_form.cleaned_data["target_date"]
                    copy_scope = copy_form.cleaned_data["scope"]
                    filter_trener = copy_form.cleaned_data.get("trener")
                    slots_data = _trainings_for_copy(source_date, target_date, copy_scope, filter_trener)
                    if slots_data:
                        copy_loaded = True
                        copy_slot_count = len(slots_data)
                        copy_hraci_lists = [slot["hraci"] for slot in slots_data]
                        initial_slots = []
                        for slot in slots_data:
                            initial_slots.append({
                                "cas": slot["cas"],
                                "delka_minut": slot["delka_minut"],
                                "format": slot["format"],
                                "kurt": slot["kurt"],
                                "poznamka": slot["poznamka"],
                                "hraci": slot["hraci"],
                                "slot_datum": slot["slot_datum"],
                                "trener": slot["trener"],
                            })
                            copy_slots_players_json.append(json.dumps([
                                {"id": h.pk, "jmeno": h.jmeno}
                                for h in slot["hraci"]
                            ]))
                        day_form = AddDayFormClass(
                            prefix="day",
                            initial={
                                "datum": target_date,
                                "trener": filter_trener or slots_data[0]["trener"],
                            },
                        )
                        formset = _training_formset_from_request(initial_slots=initial_slots)
                    else:
                        messages.warning(
                            request,
                            "Ve zvoleném období nejsou žádné tréninky ke zkopírování.",
                        )
                        copy_form = CopyTrainingsForm(initial={
                            "source_date": source_date,
                            "target_date": target_date,
                            "scope": copy_scope,
                            "trener": filter_trener,
                        })
                        day_form = AddDayFormClass(prefix="day", initial={"datum": target_date})
                        formset = FormSetClass(prefix="slots")
                else:
                    day_form = AddDayFormClass(prefix="day")
                    formset = FormSetClass(prefix="slots")
            else:
                day_form = AddDayFormClass(prefix="day")
                if request.GET.get("date"):
                    try:
                        from datetime import datetime as dt_parse
                        day_form.initial["datum"] = dt_parse.strptime(request.GET["date"], "%Y-%m-%d").date()
                    except Exception:
                        pass
                formset = FormSetClass(prefix="slots")

            context = self._add_form_context(
                request, day_form, formset,
                copy_form=copy_form or CopyTrainingsForm(prefix="copy"),
                copy_loaded=copy_loaded,
                copy_scope=copy_scope,
                copy_slot_count=copy_slot_count,
                copy_slots_players_json=copy_slots_players_json,
                copy_hraci_lists=copy_hraci_lists if copy_loaded else None,
            )
            return TemplateResponse(request, self.add_form_template, context)
        return super().add_view(request, form_url=form_url, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path("schedule/", self.admin_site.admin_view(self.schedule_view), name="core_trening_schedule"),
        ]
        return extra + urls

    def get_search_results(self, request, queryset, search_term):
        parts = parse_czech_date_parts(search_term)
        if parts:
            if parts.year is not None:
                return queryset.filter(
                    datum__year=parts.year,
                    datum__month=parts.month,
                    datum__day=parts.day,
                ), False
            return queryset.filter(
                datum__month=parts.month,
                datum__day=parts.day,
            ), False
        return super().get_search_results(request, queryset, search_term)

    @admin.display(description="Datum", ordering="datum")
    def datum_display(self, obj):
        dt = dj_tz.localtime(obj.datum) if dj_tz.is_aware(obj.datum) else obj.datum
        date_str, time_str = format_czech_datetime(dt)
        url = reverse("admin:core_trening_change", args=[obj.pk])
        return format_html(
            '<a href="{}"><span class="tx-datum" data-iso-date="{}">{}</span>'
            ' <span style="color:#888;font-size:0.9em">{}</span></a>',
            url,
            dt.strftime("%Y-%m-%d"),
            date_str,
            time_str,
        )

    def hraci_jmena(self, obj):
        names = [d.hrac.jmeno for d in obj.dochazky.select_related("hrac").filter(prisel=True)]
        return ", ".join(names) if names else "—"
    hraci_jmena.short_description = "Hráč(i)"

    def trener_jmeno(self, obj):
        return trener_label(obj.trener)
    trener_jmeno.short_description = "Trenér"

    def format_display(self, obj):
        return obj.get_format_display()
    format_display.short_description = "Formát"

    def castka_na_hrace_kc(self, obj):
        return f"{obj.cena_na_hrace()} Kč"
    castka_na_hrace_kc.short_description = "Částka / hráč"

    def response_add(self, request, obj, post_url_continue=None):
        local_dt = dj_tz.localtime(obj.datum) if dj_tz.is_aware(obj.datum) else obj.datum
        date_str = local_dt.strftime("%d.%m.%Y")
        time_str = local_dt.strftime("%H:%M")

        hours = obj.hodiny
        try:
            if hours == hours.to_integral():
                hours_str = f"{int(hours)} h"
            else:
                hours_str = f"{str(hours).replace('.', ',')} h"
        except Exception:
            hours_str = f"{obj.delka_minut} min"

        trener_str = self.trener_jmeno(obj)
        format_str = obj.get_format_display()
        kurt_str = obj.get_kurt_display()
        hraci_str = self.hraci_jmena(obj)
        edit_url = reverse("admin:core_trening_change", args=[obj.pk])

        summary_message = format_html(
            (
                'Položka typu <strong>Trénink</strong> byla úspěšně přidána.<br>'
                'Zkontrolujte prosím zadané údaje:<br>'
                '<strong>Trenér:</strong> {}<br>'
                '<strong>Datum:</strong> {}<br>'
                '<strong>Čas:</strong> {}<br>'
                '<strong>Délka (hodiny):</strong> {}<br>'
                '<strong>Formát:</strong> {}<br>'
                '<strong>Kurt:</strong> {}<br>'
                '<strong>Hráči:</strong> {}<br>'
                'Níže můžete přidat další položku typu <strong>Trénink</strong>.<br>'
                '<a href="{}" class="button" '
                'style="display:inline-block;margin-top:14px;padding:6px 12px;'
                'font-size:12px;line-height:1.4;">'
                'Otevřít a upravit tento trénink'
                '</a>'
            ),
            trener_str,
            date_str,
            time_str,
            hours_str,
            format_str,
            kurt_str,
            hraci_str,
            edit_url,
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

        hours = obj.hodiny
        try:
            if hours == hours.to_integral():
                hours_str = f"{int(hours)} h"
            else:
                hours_str = f"{str(hours).replace('.', ',')} h"
        except Exception:
            hours_str = f"{obj.delka_minut} min"

        trener_str = self.trener_jmeno(obj)
        format_str = obj.get_format_display()
        kurt_str = obj.get_kurt_display()

        summary_message = format_html(
            (
                'Položka typu <strong>Trénink</strong> byla úspěšně změněna.<br>'
                'Aktuálně uložené údaje:<br>'
                '<strong>Trenér:</strong> {}<br>'
                '<strong>Datum:</strong> {}<br>'
                '<strong>Čas:</strong> {}<br>'
                '<strong>Délka (hodiny):</strong> {}<br>'
                '<strong>Formát:</strong> {}<br>'
                '<strong>Kurt:</strong> {}'
            ),
            trener_str,
            date_str,
            time_str,
            hours_str,
            format_str,
            kurt_str,
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
        """Týdenní/denní rozvrh tréninků s filtry + rozložení překryvů do pruhů."""
        q = request.GET
        CZECH_DOW = ["po", "út", "st", "čt", "pá", "so", "ne"]

        def _slug(s: str) -> str:
            s = (s or "").strip().lower()
            repl = (("á", "a"), ("č", "c"), ("ď", "d"), ("é", "e"), ("ě", "e"), ("í", "i"),
                    ("ň", "n"), ("ó", "o"), ("ř", "r"), ("š", "s"), ("ť", "t"), ("ú", "u"),
                    ("ů", "u"), ("ý", "y"), ("ž", "z"))
            for a, b in repl:
                s = s.replace(a, b)
            import re
            s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
            if not s or not s[0].isalpha():
                s = f"f-{s or 'neznamy'}"
            return s

        try:
            base_date = datetime.strptime(q.get("date", ""), "%Y-%m-%d").date()
        except Exception:
            base_date = dj_tz.localdate()

        mode = q.get("view", "week")
        start_day = base_date if mode == "day" else (base_date - timedelta(days=base_date.weekday()))
        end_day = start_day if mode == "day" else (start_day + timedelta(days=6))

        start_dt = dj_tz.make_aware(datetime.combine(start_day, time.min))
        end_dt = dj_tz.make_aware(datetime.combine(end_day, time.max))

        trainer_id = q.get("trener") or ""
        qs = (
            Trening.objects
            .filter(datum__range=(start_dt, end_dt))
            .select_related("trener")
            .prefetch_related("dochazky__hrac")
            .order_by("datum")
        )
        if trainer_id:
            qs = qs.filter(trener_id=trainer_id)

        day_start_min = 6 * 60
        hours = list(range(6, 23))

        day_count = (end_day - start_day).days + 1
        days = []
        for i in range(day_count):
            d = start_day + timedelta(days=i)
            label = f"{CZECH_DOW[d.weekday()]} {d.strftime('%d.%m.')}"
            days.append({"date": d, "label": label, "events": []})
        idx_by_date = {(start_day + timedelta(days=i)): i for i in range(day_count)}

        for t in qs:
            local = dj_tz.localtime(t.datum) if dj_tz.is_aware(t.datum) else t.datum
            d = local.date()
            i = idx_by_date.get(d)
            if i is None:
                continue

            start_min = local.hour * 60 + local.minute
            offset = max(0, start_min - day_start_min)
            dur = int(t.delka_minut)

            fmt_label = t.get_format_display()
            fmt_slug = _slug(fmt_label)

            ev = {
                "id": t.id,
                "offset_min": offset,
                "dur_min": dur,
                "end_min": offset + dur,
                "title": ", ".join(
                    dch.hrac.jmeno for dch in t.dochazky.select_related("hrac").filter(prisel=True)
                ) or "—",
                "sub": "",  # pouze jména hráčů v title, bez formátu/kurtu
                "fmt": fmt_slug,
                "fmt_label": fmt_label,
            }
            days[i]["events"].append(ev)

        def assign_lanes(evs):
            if not evs:
                return
            evs.sort(key=lambda e: (e["offset_min"], e["dur_min"]))

            cluster = []
            cluster_max_end = -1

            def finalize_cluster(cluster_events):
                lanes_end = []
                for e in cluster_events:
                    placed = False
                    for idx, end in enumerate(lanes_end):
                        if e["offset_min"] >= end:
                            e["lane"] = idx
                            lanes_end[idx] = e["end_min"]
                            placed = True
                            break
                    if not placed:
                        lanes_end.append(e["end_min"])
                        e["lane"] = len(lanes_end) - 1
                total = len(lanes_end)
                for e in cluster_events:
                    e["lanes"] = total

            for e in evs:
                if not cluster:
                    cluster = [e]
                    cluster_max_end = e["end_min"]
                    continue
                if e["offset_min"] < cluster_max_end:
                    cluster.append(e)
                    if e["end_min"] > cluster_max_end:
                        cluster_max_end = e["end_min"]
                else:
                    finalize_cluster(cluster)
                    cluster = [e]
                    cluster_max_end = e["end_min"]

            if cluster:
                finalize_cluster(cluster)

        for day in days:
            assign_lanes(day["events"])

        step = 7 if mode == "week" else 1
        prev_week_day = base_date - timedelta(days=7)
        copy_day_url = (
            reverse("admin:core_trening_add")
            + f"?copy=1&copy-scope=day&copy-source_date={prev_week_day.isoformat()}&copy-target_date={base_date.isoformat()}"
        )
        copy_week_url = (
            reverse("admin:core_trening_add")
            + f"?copy=1&copy-scope=week&copy-source_date={(start_day - timedelta(days=7)).isoformat()}&copy-target_date={start_day.isoformat()}"
        )
        if trainer_id:
            copy_day_url += f"&copy-trener={trainer_id}"
            copy_week_url += f"&copy-trener={trainer_id}"
        ctx = dict(self.admin_site.each_context(request))
        ctx.update({
            "title": "Rozvrh tréninků",
            "active_menu": "rozvrh",
            "view_mode": mode,
            "trainers": User.objects.order_by("username"),
            "selected_trainer": int(trainer_id) if trainer_id else "",
            "date_value": base_date.strftime("%Y-%m-%d"),
            "prev_date": (base_date - timedelta(days=step)).strftime("%Y-%m-%d"),
            "next_date": (base_date + timedelta(days=step)).strftime("%Y-%m-%d"),
            "copy_day_url": copy_day_url,
            "copy_week_url": copy_week_url,
            "hours": hours,
            "day_start_min": day_start_min,
            "days": days,
        })
        return TemplateResponse(request, "admin/core/trening/kalendar.html", ctx)

    def treneri_summary_view(self, request):
        dfrom, dto = _period_from_request(request)

        base_qs = Trening.objects.all()
        if dfrom:
            base_qs = base_qs.filter(datum__date__gte=dfrom)
        if dto:
            base_qs = base_qs.filter(datum__date__lte=dto)

        users = {
            u.id: u
            for u in User.objects.filter(pk__in=_all_trener_ids()).order_by(
                "last_name", "first_name", "username"
            )
        }

        rows = []
        total_pocet = 0
        total_hodiny = Decimal("0.00")
        total_castka = Decimal("0.00")

        for uid in sorted(users.keys(), key=lambda i: (users[i].get_full_name() or users[i].username).lower()):
            u = users[uid]
            tqs = list(
                base_qs.filter(trener_id=uid).order_by("datum").prefetch_related("dochazky__hrac")
            )
            stats = _aggregate_trener_trainings(u, tqs)
            total_pocet += stats["pocet"]
            total_hodiny += stats["hodiny_raw"]
            total_castka += stats["castka_raw"]

            q = []
            if dfrom:
                q.append(f"from={dfrom.isoformat()}")
            if dto:
                q.append(f"to={dto.isoformat()}")
            detail_qs = ("?" + "&".join(q)) if q else ""

            rows.append({
                "trener": (u.get_full_name() or u.username),
                "detail_url": reverse("admin:core_treneri_detail", args=[u.id]) + detail_qs,
                "pocet": stats["pocet"],
                "hodiny": stats["hodiny"],
                "castka": stats["castka"],
            })

        ctx = dict(
            self.admin_site.each_context(request),
            title="Trenéři – souhrn",
            rows=rows,
            total_pocet=total_pocet,
            total_hodiny=f"{total_hodiny:.2f}",
            total_castka=f"{total_castka.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.0f} Kč",
            dfrom=dfrom, dto=dto,
            active_menu="treneri",
        )
        return TemplateResponse(request, "admin/core/trening/treneri_summary.html", ctx)

    def trener_detail_view(self, request, user_id: int):
        u = User.objects.get(pk=user_id)

        if request.method == "POST" and "_nastavit_sazbu" in request.POST:
            date_raw = (request.POST.get("rate_from") or "").strip()
            amt_raw = (request.POST.get("rate_amount") or "").strip()

            try:
                eff_from = datetime.strptime(date_raw, "%Y-%m-%d").date()
            except Exception:
                messages.error(request, "Neplatné datum 'Od'.")
                return redirect(request.get_full_path())

            try:
                amount = Decimal(amt_raw.replace(",", "."))
                if amount <= 0:
                    raise ValueError()
            except Exception:
                messages.error(request, "Neplatná částka sazby.")
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

        dfrom = _parse_admin_date(request.GET.get("from", ""))
        dto = _parse_admin_date(request.GET.get("to", ""))

        tqs = Trening.objects.filter(trener=u)
        if dfrom:
            tqs = tqs.filter(datum__date__gte=dfrom)
        if dto:
            tqs = tqs.filter(datum__date__lte=dto)
        tqs = list(tqs.prefetch_related("dochazky__hrac").order_by("-datum"))

        stats = _aggregate_trener_trainings(u, tqs)
        training_months = _group_trainings_by_month(u, tqs)

        rate_today = sazba_trenera_k_datu(u, dj_tz.now())
        rate_today_amount = f"{rate_today:.0f}"
        rate_today_date = dj_tz.localdate().strftime("%Y-%m-%d")
        rate_form_initial_date = rate_today_date

        sazby = (
            TrenerSazba.objects.filter(user=u).order_by("-platnost_od")
            .values("id", "platnost_od", "platnost_do", "sazba_za_hodinu")
        )
        finance = _trener_financial_overview(u)

        ctx = dict(
            self.admin_site.each_context(request),
            title=f"Trenér – {u.get_full_name() or u.username}",
            trener=u,
            pocet=stats["pocet"],
            total_hours=f"{stats['hodiny']} h",
            total_castka=stats["castka"],
            celkova_castka=finance["celkova_castka"],
            mesic_label=finance["mesic_label"],
            mesic_castka=finance["mesic_castka"],
            dluzna_castka=finance["dluzna_castka"],
            mesice=stats["mesice"],
            training_months=training_months,
            rate_today_amount=rate_today_amount,
            rate_today_date=rate_today_date,
            rate_form_initial_date=rate_form_initial_date,
            sazby=sazby,
            summary_url=reverse("admin:core_treneri_summary"),
            dfrom=dfrom, dto=dto,
            active_menu="treneri",
        )
        return TemplateResponse(request, "admin/core/trening/trener_detail.html", ctx)
