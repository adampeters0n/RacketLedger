"""Pronájem kurtu/haly – admin + týdenní rozvrh (jen platform_admin)."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from django.conf import settings
from django.contrib import admin
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone as dj_tz
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from ..admin_mixins import ConfigurableListPerPageMixin
from ..admin_utils import format_czech_datetime, parse_czech_date_parts, filter_queryset_by_parsed_date
from ..models import (
    Cenik,
    PredpokladanyPronajemSkip,
    PredpokladanyPronajemSlot,
    Pronajem,
    StalyPronajemSlot,
    SystemNastaveni,
)
from ..predpokladany_pronajem import (
    append_pronajem_ghost_events_for_week,
    backfill_all_staly_pronajem_slots,
    backfill_pronajem_from_staly_slot,
    delete_pronajem_linked_to_staly_slot,
    materialize_pronajem_for_date,
)
from ..roles import is_platform_admin


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    repl = (
        ("á", "a"), ("č", "c"), ("ď", "d"), ("é", "e"), ("ě", "e"), ("í", "i"),
        ("ň", "n"), ("ó", "o"), ("ř", "r"), ("š", "s"), ("ť", "t"), ("ú", "u"),
        ("ů", "u"), ("ý", "y"), ("ž", "z"),
    )
    for a, b in repl:
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if not s or not s[0].isalpha():
        s = f"f-{s or 'neznamy'}"
    return s


def _assign_lanes(evs):
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


def _parse_time(raw: str):
    raw = (raw or "").strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).time()
        except (TypeError, ValueError):
            continue
    return None


def _parse_cena(raw) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _allowed_delka() -> set[int]:
    return {c[0] for c in SystemNastaveni.PRONAJEM_DELKA_MINUT_CHOICES}


def _hodiny_z_delky(delka_minut: int) -> Decimal:
    return (Decimal(int(delka_minut or 60)) / Decimal(60)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _cena_celkem(sazba: Decimal, delka_minut: int) -> Decimal:
    """Sazba Kč/h × počet hodin → celková cena k uložení."""
    return (sazba * _hodiny_z_delky(delka_minut)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _sazba_z_celkem(celkem: Decimal, delka_minut: int, allowed: list[Decimal] | None = None) -> Decimal:
    """Odhad hodinové sazby z uložené celkové ceny (pro výběr chipu při editaci)."""
    hours = _hodiny_z_delky(delka_minut)
    if hours <= 0:
        return celkem
    rate = (celkem / hours).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if allowed:
        for a in allowed:
            if abs(a - rate) <= Decimal("0.05"):
                return a
            # starší flat uložení: celkem = sazba (bez × hodin)
            if abs(a - celkem) <= Decimal("0.05") and hours != 1:
                return a
    return rate


def _cena_option(c: Decimal) -> dict:
    value = c.quantize(Decimal("1")) if c == c.to_integral_value() else c
    return {"value": str(value), "label": f"{value} Kč/h"}


def _normalize_kurt_misto(sezona: str, kurt_misto: str) -> str | None:
    code = (kurt_misto or "").strip()
    allowed = {c[0] for c in Pronajem.kurt_misto_choices_for(sezona)}
    if code in allowed:
        return code
    return None


def _kurt_misto_label(code: str, sezona: str = "") -> str:
    if not code:
        return dict(Cenik.Kurt.choices).get(sezona, sezona) or "—"
    labels = dict(Pronajem.KurtMisto.choices)
    return str(labels.get(code, code))


def _event_payload(obj: Pronajem, day_start_min: int) -> dict:
    local = dj_tz.localtime(obj.datum) if dj_tz.is_aware(obj.datum) else obj.datum
    dur = int(obj.delka_minut or 60)
    end_local = local + timedelta(minutes=dur)
    start_min = local.hour * 60 + local.minute
    offset = max(0, start_min - day_start_min)
    title = (obj.rezervujici or "").strip() or "—"
    cena_total = Decimal(obj.cena)
    cena_str = f"{cena_total:.0f} Kč"
    misto = (obj.kurt_misto or "").strip() or Pronajem.default_kurt_misto(obj.kurt)
    fmt_label = _kurt_misto_label(misto, obj.kurt)
    time_range = f"{local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}"
    sazba = _sazba_z_celkem(
        cena_total, dur, SystemNastaveni.pronajem_ceny_choices(obj.kurt)
    )
    sazba_str = str(
        sazba.quantize(Decimal("1")) if sazba == sazba.to_integral_value() else sazba
    )
    sazba_label = f"{sazba_str} Kč"
    return {
        "id": obj.pk,
        "date": local.date().isoformat(),
        "offset_min": offset,
        "dur_min": dur,
        "end_min": offset + dur,
        "names": [title],
        "title": title,
        "sub": f"{time_range} · {sazba_label}",
        "time_range": time_range,
        "fmt": "rezervace",
        "fmt_code": "kurt-tre",
        "fmt_label": fmt_label,
        "is_staly": False,
        "is_ghost": False,
        "rezervujici": title,
        "cena": str(cena_total),
        "cena_label": sazba_label,
        "cena_hodina": sazba_str,
        "kurt": obj.kurt,
        "kurt_misto": misto,
        "poznamka": obj.poznamka or "",
        "time": local.strftime("%H:%M"),
        "change_url": reverse("admin:core_pronajem_change", args=[obj.pk]),
    }


def _staly_event_payload(slot: StalyPronajemSlot, day_start_min: int) -> dict:
    dur = int(slot.delka_minut or 60)
    end_t = (datetime.combine(date.min, slot.cas_od) + timedelta(minutes=dur)).time()
    start_min = slot.cas_od.hour * 60 + slot.cas_od.minute
    offset = max(0, start_min - day_start_min)
    title = (slot.rezervujici or "").strip() or "—"
    cena_total = Decimal(slot.cena)
    cena_str = f"{cena_total:.0f} Kč"
    misto = (slot.kurt_misto or "").strip() or Pronajem.default_kurt_misto(slot.kurt)
    fmt_label = _kurt_misto_label(misto, slot.kurt)
    time_range = f"{slot.cas_od.strftime('%H:%M')}–{end_t.strftime('%H:%M')}"
    sazba = _sazba_z_celkem(
        cena_total, dur, SystemNastaveni.pronajem_ceny_choices(slot.kurt)
    )
    sazba_str = str(
        sazba.quantize(Decimal("1")) if sazba == sazba.to_integral_value() else sazba
    )
    sazba_label = f"{sazba_str} Kč"
    return {
        "id": slot.pk,
        "offset_min": offset,
        "dur_min": dur,
        "end_min": offset + dur,
        "names": [title],
        "title": title,
        "sub": f"{time_range} · {sazba_label}",
        "time_range": time_range,
        "fmt": "rezervace",
        "fmt_code": "kurt-tre",
        "fmt_label": fmt_label,
        "is_staly": True,
        "is_ghost": False,
        "rezervujici": title,
        "cena": str(cena_total),
        "cena_label": sazba_label,
        "cena_hodina": sazba_str,
        "kurt": slot.kurt,
        "kurt_misto": misto,
        "poznamka": slot.poznamka or "",
        "time": slot.cas_od.strftime("%H:%M"),
        "dow": int(slot.den),
        "format": slot.format or Pronajem.FORMAT_DEFAULT,
    }


@admin.register(Pronajem)
class PronajemAdmin(ConfigurableListPerPageMixin, admin.ModelAdmin):
    list_display = ("datum_display", "rezervujici", "kurt", "kurt_misto", "delka_minut", "cena", "poznamka")
    list_filter = ("kurt", "kurt_misto")
    search_fields = ("rezervujici", "poznamka")
    ordering = ("-datum",)
    fields = ("datum", "delka_minut", "kurt", "kurt_misto", "rezervujici", "cena", "poznamka", "format")
    readonly_fields = ("format",)

    def has_module_permission(self, request):
        return is_platform_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def has_add_permission(self, request):
        return is_platform_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_platform_admin(request.user)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not is_platform_admin(request.user):
            return qs.none()
        return qs

    def get_search_results(self, request, queryset, search_term):
        parts = parse_czech_date_parts(search_term)
        if parts:
            return filter_queryset_by_parsed_date(queryset, parts, "datum"), False
        return super().get_search_results(request, queryset, search_term)

    @admin.display(description=_("Datum"), ordering="datum")
    def datum_display(self, obj):
        dt = dj_tz.localtime(obj.datum) if dj_tz.is_aware(obj.datum) else obj.datum
        date_str, time_str = format_czech_datetime(dt)
        url = reverse("admin:core_pronajem_change", args=[obj.pk])
        return format_html(
            '<a href="{}"><span class="tx-datum" data-iso-date="{}">{}</span>'
            ' <span style="color:#888;font-size:0.9em">{}</span></a>',
            url,
            dt.strftime("%Y-%m-%d"),
            date_str,
            time_str,
        )

    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path("schedule/", self.admin_site.admin_view(self.schedule_view), name="core_pronajem_schedule"),
            path(
                "schedule/quick-add/",
                self.admin_site.admin_view(self.schedule_quick_add_view),
                name="core_pronajem_schedule_quick_add",
            ),
            path(
                "schedule/delete/",
                self.admin_site.admin_view(self.schedule_delete_view),
                name="core_pronajem_schedule_delete",
            ),
            path(
                "schedule/move/",
                self.admin_site.admin_view(self.schedule_move_view),
                name="core_pronajem_schedule_move",
            ),
            path(
                "schedule/cena/",
                self.admin_site.admin_view(self.schedule_cena_view),
                name="core_pronajem_schedule_cena",
            ),
            path(
                "schedule/staly/",
                self.admin_site.admin_view(self.schedule_staly_save_view),
                name="core_pronajem_schedule_staly_save",
            ),
            path(
                "schedule/staly/<int:slot_id>/delete/",
                self.admin_site.admin_view(self.schedule_staly_delete_view),
                name="core_pronajem_schedule_staly_delete",
            ),
            path(
                "schedule/materialize/",
                self.admin_site.admin_view(self.schedule_materialize_view),
                name="core_pronajem_schedule_materialize",
            ),
            path(
                "schedule/predpokladany/skip/",
                self.admin_site.admin_view(self.schedule_predpokladany_skip_view),
                name="core_pronajem_schedule_predpokladany_skip",
            ),
        ]
        return extra + urls

    def _forbid_unless_platform(self, request):
        if not is_platform_admin(request.user):
            return HttpResponseForbidden(_("Tento rozvrh je dostupný jen administrátorovi."))
        return None

    def _quick_add_options(self, base_date, nast):
        defaults = SystemNastaveni.training_defaults(for_date=base_date) if nast else {
            "delka_minut": 60,
            "kurt": Cenik.Kurt.VENEK,
        }
        default_sezona = (defaults.get("kurt") or "").strip()
        if default_sezona not in (Cenik.Kurt.VENEK, Cenik.Kurt.HALA):
            default_sezona = Cenik.Kurt.VENEK
        ceny_hala = SystemNastaveni.pronajem_ceny_choices(Cenik.Kurt.HALA)
        ceny_venek = SystemNastaveni.pronajem_ceny_choices(Cenik.Kurt.VENEK)
        ceny = SystemNastaveni.pronajem_ceny_choices(default_sezona)
        default_cena = ceny[0] if ceny else Decimal("420.00")
        default_misto = Pronajem.default_kurt_misto(default_sezona)
        return {
            "trainers": [],
            "formats": [],
            "players": [],
            "sezony": [
                {"value": Cenik.Kurt.VENEK, "label": str(dict(Cenik.Kurt.choices)[Cenik.Kurt.VENEK])},
                {"value": Cenik.Kurt.HALA, "label": str(dict(Cenik.Kurt.choices)[Cenik.Kurt.HALA])},
            ],
            "kurty": [
                {"value": c[0], "label": c[1]}
                for c in Pronajem.kurt_misto_choices_for(default_sezona)
            ],
            "kurty_by_sezona": {
                Cenik.Kurt.HALA: [
                    {"value": c[0], "label": c[1]}
                    for c in Pronajem.kurt_misto_choices_for(Cenik.Kurt.HALA)
                ],
                Cenik.Kurt.VENEK: [
                    {"value": c[0], "label": c[1]}
                    for c in Pronajem.kurt_misto_choices_for(Cenik.Kurt.VENEK)
                ],
            },
            "delky": [
                {"value": c[0], "label": str(c[1])}
                for c in SystemNastaveni.PRONAJEM_DELKA_MINUT_CHOICES
            ],
            "ceny": [_cena_option(c) for c in ceny],
            "ceny_by_sezona": {
                Cenik.Kurt.HALA: [_cena_option(c) for c in ceny_hala],
                Cenik.Kurt.VENEK: [_cena_option(c) for c in ceny_venek],
            },
            "defaults": {
                "delka_minut": int(defaults.get("delka_minut") or 60),
                "sezona": default_sezona,
                "kurt": default_misto,
                "cena": str(
                    default_cena.quantize(Decimal("1"))
                    if default_cena == default_cena.to_integral_value()
                    else default_cena
                ),
            },
        }

    def schedule_view(self, request):
        forbidden = self._forbid_unless_platform(request)
        if forbidden:
            return forbidden

        q = request.GET
        CZECH_DOW = ["po", "út", "st", "čt", "pá", "so", "ne"]

        try:
            base_date = datetime.strptime(q.get("date", ""), "%Y-%m-%d").date()
        except Exception:
            base_date = dj_tz.localdate()

        try:
            nast = SystemNastaveni.load()
        except Exception:
            nast = None

        rozvrh_mode = (q.get("rozvrh") or "aktualni").strip().lower()
        if rozvrh_mode not in ("aktualni", "staly", "predpokladany"):
            rozvrh_mode = "aktualni"
        is_staly = rozvrh_mode == "staly"
        is_predpokladany = rozvrh_mode == "predpokladany"

        start_day = base_date - timedelta(days=base_date.weekday())
        end_day = start_day + timedelta(days=6)
        hours = nast.schedule_hours() if nast else list(range(6, 23))
        day_start_min = hours[0] * 60 if hours else 6 * 60
        hour_count = len(hours) if hours else 16

        days = []
        for i in range(7):
            d = start_day + timedelta(days=i)
            if is_staly:
                label = CZECH_DOW[d.weekday()]
            else:
                label = f"{CZECH_DOW[d.weekday()]} {d.strftime('%d.%m.')}"
            days.append({
                "date": d,
                "dow": d.weekday(),
                "label": label,
                "events": [],
            })
        idx_by_date = {start_day + timedelta(days=i): i for i in range(7)}
        idx_by_dow = {days[i]["dow"]: i for i in range(7)}

        if is_staly:
            for slot in StalyPronajemSlot.objects.order_by("den", "cas_od", "id"):
                i = idx_by_dow.get(int(slot.den))
                if i is None:
                    continue
                days[i]["events"].append(_staly_event_payload(slot, day_start_min))
        else:
            # Stálý → doplň chybějící Pronajem od data platnosti do dneška
            # (budoucnost v předpokládaném zůstane přerušovaně jako ghost).
            backfill_all_staly_pronajem_slots()
            start_dt = dj_tz.make_aware(datetime.combine(start_day, time.min))
            end_dt = dj_tz.make_aware(datetime.combine(end_day, time.max))
            for obj in Pronajem.objects.filter(datum__range=(start_dt, end_dt)).order_by("datum"):
                local = dj_tz.localtime(obj.datum) if dj_tz.is_aware(obj.datum) else obj.datum
                i = idx_by_date.get(local.date())
                if i is None:
                    continue
                days[i]["events"].append(_event_payload(obj, day_start_min))

            if is_predpokladany:
                append_pronajem_ghost_events_for_week(
                    days,
                    today=dj_tz.localdate(),
                    day_start_min=day_start_min,
                )

        for day in days:
            _assign_lanes(day["events"])

        today = dj_tz.localdate()
        if is_staly:
            title = _("Stálý rozvrh pronájmů")
        elif is_predpokladany:
            title = _("Předpokládaný rozvrh pronájmů")
        else:
            title = _("Rozvrh pronájmů")

        staly_od = getattr(nast, "staly_pronajem_od", None) if nast else date(2026, 10, 10)
        staly_do = getattr(nast, "staly_pronajem_do", None) if nast else date(2027, 4, 9)
        staly_od_label = staly_od.strftime("%d.%m.%Y") if staly_od else "—"
        staly_do_label = staly_do.strftime("%d.%m.%Y") if staly_do else "—"
        staly_platny_dnes = bool(nast.staly_pronajem_platny(today)) if nast else True

        ctx = dict(self.admin_site.each_context(request))
        ctx.update({
            "title": title,
            "active_menu": "rozvrh",
            "view_mode": "week",
            "rozvrh_mode": rozvrh_mode,
            "is_staly": is_staly,
            "is_predpokladany": is_predpokladany,
            "is_platform_admin": is_platform_admin(request.user),
            "date_value": base_date.strftime("%Y-%m-%d"),
            "prev_date": (base_date - timedelta(days=7)).strftime("%Y-%m-%d"),
            "next_date": (base_date + timedelta(days=7)).strftime("%Y-%m-%d"),
            "quick_add_url": reverse("admin:core_pronajem_schedule_quick_add"),
            "delete_url": reverse("admin:core_pronajem_schedule_delete"),
            "move_url": reverse("admin:core_pronajem_schedule_move"),
            "cena_url": reverse("admin:core_pronajem_schedule_cena"),
            "staly_save_url": reverse("admin:core_pronajem_schedule_staly_save"),
            "staly_delete_url_template": reverse(
                "admin:core_pronajem_schedule_staly_delete", args=[0]
            ).replace("/0/", "/{id}/"),
            "materialize_url": reverse("admin:core_pronajem_schedule_materialize"),
            "predpokladany_skip_url": reverse("admin:core_pronajem_schedule_predpokladany_skip"),
            "today_label": today.strftime("%d.%m.%Y"),
            "staly_pronajem_od_label": staly_od_label,
            "staly_pronajem_do_label": staly_do_label,
            "staly_pronajem_platny_dnes": staly_platny_dnes,
            "changelist_url": reverse("admin:core_pronajem_changelist"),
            "quick_add_options_json": json.dumps(
                self._quick_add_options(base_date, nast), ensure_ascii=False
            ),
            "hours": hours,
            "day_start_min": day_start_min,
            "hour_count": hour_count,
            "sched_start_hour": hours[0] if hours else 6,
            "days": days,
        })
        return TemplateResponse(request, "admin/core/pronajem/kalendar.html", ctx)

    def schedule_cena_view(self, request):
        forbidden = self._forbid_unless_platform(request)
        if forbidden:
            return forbidden
        ceny = SystemNastaveni.pronajem_ceny_choices()
        default = ceny[0] if ceny else Decimal("420.00")
        return JsonResponse({"ok": True, "cena": str(default), "cena_label": f"{default:.0f} Kč"})

    def schedule_quick_add_view(self, request):
        forbidden = self._forbid_unless_platform(request)
        if forbidden:
            return forbidden
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": _("Method not allowed.")}, status=405)

        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            payload = request.POST.dict()

        date_raw = (payload.get("date") or "").strip()
        time_raw = (payload.get("time") or "").strip()
        rezervujici = (payload.get("rezervujici") or "").strip()
        sezona = (payload.get("sezona") or "").strip()
        kurt_raw = (payload.get("kurt") or "").strip()
        kurt_misto_raw = (payload.get("kurt_misto") or "").strip()
        poznamka = (payload.get("poznamka") or "").strip()[:240]
        delka_raw = payload.get("delka_minut", 60)
        cena = _parse_cena(payload.get("cena"))
        obj_id = payload.get("id")

        # Kompatibilita: dřív `kurt` = VENEK/HALA; teď `sezona` + `kurt`/`kurt_misto` = konkrétní kurt.
        if sezona not in (Cenik.Kurt.VENEK, Cenik.Kurt.HALA):
            if kurt_raw in (Cenik.Kurt.VENEK, Cenik.Kurt.HALA):
                sezona = kurt_raw
            else:
                sezona = ""
        if not kurt_misto_raw:
            if kurt_raw and kurt_raw not in (Cenik.Kurt.VENEK, Cenik.Kurt.HALA):
                kurt_misto_raw = kurt_raw

        try:
            day = datetime.strptime(date_raw, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatné datum.")}, status=400)

        cas = _parse_time(time_raw)
        if cas is None:
            return JsonResponse({"ok": False, "error": _("Neplatný čas.")}, status=400)
        if not rezervujici:
            return JsonResponse({"ok": False, "error": _("Zadejte jméno rezervujícího.")}, status=400)

        try:
            delka = int(delka_raw)
        except (TypeError, ValueError):
            delka = 60
        if delka not in _allowed_delka():
            if delka < 15 or delka > 420:
                return JsonResponse({"ok": False, "error": _("Neplatná délka.")}, status=400)

        if sezona not in (Cenik.Kurt.VENEK, Cenik.Kurt.HALA):
            return JsonResponse({"ok": False, "error": _("Vyberte sezónu.")}, status=400)
        kurt_misto = _normalize_kurt_misto(sezona, kurt_misto_raw)
        if not kurt_misto:
            return JsonResponse({"ok": False, "error": _("Vyberte kurt.")}, status=400)
        sazba = cena
        if sazba is None:
            ceny = SystemNastaveni.pronajem_ceny_choices(sezona)
            sazba = ceny[0] if ceny else Decimal("420.00")
        # `cena` v payloadu = Kč/h; do DB ukládáme celkovou částku.
        cena = _cena_celkem(sazba, delka)
        kurt = sezona

        try:
            hours = SystemNastaveni.load().schedule_hours()
        except Exception:
            hours = list(range(6, 23))
        day_start_min = (hours[0] if hours else 6) * 60

        as_projected = bool(
            payload.get("as_projected")
            or (payload.get("mode") or "").strip() == "predpokladany"
        )
        today = dj_tz.localdate()
        save_as_ghost = as_projected and day >= today

        if save_as_ghost:
            predp_id = payload.get("predpokladany_id")
            ghost_staly_raw = payload.get("ghost_slot_id") or payload.get("staly_slot_id")
            zdroj_staly = None
            if ghost_staly_raw not in (None, ""):
                try:
                    zdroj_staly = StalyPronajemSlot.objects.filter(pk=int(ghost_staly_raw)).first()
                except (TypeError, ValueError):
                    zdroj_staly = None

            with transaction.atomic():
                slot = None
                if predp_id not in (None, ""):
                    try:
                        slot = PredpokladanyPronajemSlot.objects.filter(pk=int(predp_id)).first()
                    except (TypeError, ValueError):
                        slot = None
                if slot is None:
                    slot = PredpokladanyPronajemSlot(datum=day)
                slot.datum = day
                slot.cas_od = cas
                slot.delka_minut = delka
                slot.kurt = kurt
                slot.kurt_misto = kurt_misto
                slot.format = Pronajem.FORMAT_DEFAULT
                slot.rezervujici = rezervujici
                slot.cena = cena
                slot.poznamka = poznamka
                if zdroj_staly and not slot.zdroj_staly_id:
                    slot.zdroj_staly = zdroj_staly
                slot.save()
                if zdroj_staly:
                    PredpokladanyPronajemSkip.objects.get_or_create(
                        datum=day, staly_slot=zdroj_staly
                    )

            end_t = (datetime.combine(date.min, cas) + timedelta(minutes=delka)).time()
            start_min = cas.hour * 60 + cas.minute
            offset = max(0, start_min - day_start_min)
            fmt_label = _kurt_misto_label(kurt_misto, kurt)
            time_range = f"{cas.strftime('%H:%M')}–{end_t.strftime('%H:%M')}"
            sazba_str = str(
                sazba.quantize(Decimal("1")) if sazba == sazba.to_integral_value() else sazba
            )
            sazba_label = f"{sazba_str} Kč"
            return JsonResponse(
                {
                    "ok": True,
                    "projected": True,
                    "id": f"predp-p-{slot.pk}",
                    "predpokladany_id": slot.pk,
                    "event": {
                        "id": f"predp-p-{slot.pk}",
                        "date": day.isoformat(),
                        "offset_min": offset,
                        "dur_min": delka,
                        "names": [rezervujici],
                        "title": rezervujici,
                        "sub": f"{time_range} · {sazba_label}",
                        "time_range": time_range,
                        "fmt": "rezervace",
                        "fmt_code": "kurt-tre",
                        "fmt_label": fmt_label,
                        "is_ghost": True,
                        "predpokladany_id": slot.pk,
                        "rezervujici": rezervujici,
                        "cena": str(cena),
                        "cena_label": sazba_label,
                        "cena_hodina": sazba_str,
                        "kurt": kurt,
                        "kurt_misto": kurt_misto,
                        "poznamka": poznamka,
                        "time": cas.strftime("%H:%M"),
                    },
                }
            )

        dt = datetime.combine(day, cas)
        if settings.USE_TZ:
            dt = dj_tz.make_aware(dt, dj_tz.get_current_timezone())

        obj = None
        if obj_id not in (None, ""):
            try:
                obj = Pronajem.objects.filter(pk=int(obj_id)).first()
            except (TypeError, ValueError):
                obj = None
        if obj is None:
            obj = Pronajem()
        obj.datum = dt
        obj.delka_minut = delka
        obj.kurt = kurt
        obj.kurt_misto = kurt_misto
        obj.format = Pronajem.FORMAT_DEFAULT
        obj.rezervujici = rezervujici
        obj.cena = cena
        obj.poznamka = poznamka
        obj.save()

        ghost_staly_raw = payload.get("ghost_slot_id") or payload.get("staly_slot_id")
        if ghost_staly_raw not in (None, ""):
            try:
                staly = StalyPronajemSlot.objects.filter(pk=int(ghost_staly_raw)).first()
                if staly:
                    PredpokladanyPronajemSkip.objects.get_or_create(datum=day, staly_slot=staly)
            except (TypeError, ValueError):
                pass

        event = _event_payload(obj, day_start_min)
        return JsonResponse({"ok": True, "id": obj.pk, "event": event})

    def schedule_delete_view(self, request):
        forbidden = self._forbid_unless_platform(request)
        if forbidden:
            return forbidden
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": _("Method not allowed.")}, status=405)
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            payload = request.POST.dict()
        try:
            obj_id = int(payload.get("id"))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatný záznam.")}, status=400)
        deleted, _ = Pronajem.objects.filter(pk=obj_id).delete()
        if not deleted:
            return JsonResponse({"ok": False, "error": _("Záznam nenalezen.")}, status=404)
        return JsonResponse({"ok": True, "id": obj_id})

    def schedule_move_view(self, request):
        forbidden = self._forbid_unless_platform(request)
        if forbidden:
            return forbidden
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": _("Method not allowed.")}, status=405)
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            payload = request.POST.dict()
        try:
            obj_id = int(payload.get("id"))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatný záznam.")}, status=400)
        date_raw = (payload.get("date") or "").strip()
        time_raw = (payload.get("time") or "").strip()
        try:
            day = datetime.strptime(date_raw, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatné datum.")}, status=400)
        cas = _parse_time(time_raw)
        if cas is None:
            return JsonResponse({"ok": False, "error": _("Neplatný čas.")}, status=400)
        obj = Pronajem.objects.filter(pk=obj_id).first()
        if not obj:
            return JsonResponse({"ok": False, "error": _("Záznam nenalezen.")}, status=404)
        dt = datetime.combine(day, cas)
        if settings.USE_TZ:
            dt = dj_tz.make_aware(dt, dj_tz.get_current_timezone())
        obj.datum = dt
        obj.save(update_fields=["datum"])
        try:
            hours = SystemNastaveni.load().schedule_hours()
        except Exception:
            hours = list(range(6, 23))
        day_start_min = (hours[0] if hours else 6) * 60
        return JsonResponse({"ok": True, "id": obj.pk, "event": _event_payload(obj, day_start_min)})

    def schedule_staly_save_view(self, request):
        forbidden = self._forbid_unless_platform(request)
        if forbidden:
            return forbidden
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": _("Method not allowed.")}, status=405)
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            payload = request.POST.dict()

        slot_id = payload.get("id")
        move_only = bool(payload.get("move_only"))

        if move_only and slot_id not in (None, "", "null"):
            try:
                slot = StalyPronajemSlot.objects.filter(pk=int(slot_id)).first()
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
            cas = _parse_time(payload.get("time") or "")
            if cas is None:
                return JsonResponse({"ok": False, "error": _("Neplatný čas.")}, status=400)
            slot.den = dow
            slot.cas_od = cas
            slot.save(update_fields=["den", "cas_od"])
            backfill_pronajem_from_staly_slot(slot)
            return JsonResponse(self._staly_slot_json(slot))

        try:
            dow = int(payload.get("dow"))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatný den.")}, status=400)
        if dow < 0 or dow > 6:
            return JsonResponse({"ok": False, "error": _("Neplatný den.")}, status=400)

        cas = _parse_time(payload.get("time") or "")
        if cas is None:
            return JsonResponse({"ok": False, "error": _("Neplatný čas.")}, status=400)

        rezervujici = (payload.get("rezervujici") or "").strip()
        if not rezervujici:
            return JsonResponse({"ok": False, "error": _("Zadejte jméno rezervujícího.")}, status=400)

        try:
            delka = int(payload.get("delka_minut") or 60)
        except (TypeError, ValueError):
            delka = 60
        if delka not in _allowed_delka() and (delka < 15 or delka > 420):
            return JsonResponse({"ok": False, "error": _("Neplatná délka.")}, status=400)

        sezona = (payload.get("sezona") or "").strip()
        kurt_raw = (payload.get("kurt") or "").strip()
        kurt_misto_raw = (payload.get("kurt_misto") or "").strip()
        if sezona not in (Cenik.Kurt.VENEK, Cenik.Kurt.HALA):
            if kurt_raw in (Cenik.Kurt.VENEK, Cenik.Kurt.HALA):
                sezona = kurt_raw
            else:
                sezona = ""
        if not kurt_misto_raw and kurt_raw and kurt_raw not in (Cenik.Kurt.VENEK, Cenik.Kurt.HALA):
            kurt_misto_raw = kurt_raw
        if sezona not in (Cenik.Kurt.VENEK, Cenik.Kurt.HALA):
            return JsonResponse({"ok": False, "error": _("Vyberte sezónu.")}, status=400)
        kurt_misto = _normalize_kurt_misto(sezona, kurt_misto_raw)
        if not kurt_misto:
            return JsonResponse({"ok": False, "error": _("Vyberte kurt.")}, status=400)

        sazba = _parse_cena(payload.get("cena"))
        if sazba is None:
            ceny = SystemNastaveni.pronajem_ceny_choices(sezona)
            sazba = ceny[0] if ceny else Decimal("420.00")
        cena = _cena_celkem(sazba, delka)

        poznamka = (payload.get("poznamka") or "").strip()[:240]

        slot = None
        if slot_id not in (None, "", "null"):
            try:
                slot = StalyPronajemSlot.objects.filter(pk=int(slot_id)).first()
            except (TypeError, ValueError):
                slot = None
            if slot is None:
                return JsonResponse({"ok": False, "error": _("Slot nenalezen.")}, status=404)
        if slot is None:
            slot = StalyPronajemSlot()

        slot.den = dow
        slot.cas_od = cas
        slot.delka_minut = delka
        slot.kurt = sezona
        slot.kurt_misto = kurt_misto
        slot.format = Pronajem.FORMAT_DEFAULT
        slot.rezervujici = rezervujici
        slot.cena = cena
        slot.poznamka = poznamka
        slot.save()
        # Od data platnosti do dneška → aktuální (Pronajem);
        # budoucnost zůstane přerušovaně v předpokládaném (ghosty).
        backfill_pronajem_from_staly_slot(slot)
        return JsonResponse(self._staly_slot_json(slot))

    def _staly_slot_json(self, slot: StalyPronajemSlot) -> dict:
        dur = int(slot.delka_minut or 60)
        end_t = (datetime.combine(date.min, slot.cas_od) + timedelta(minutes=dur)).time()
        title = (slot.rezervujici or "").strip() or "—"
        misto = (slot.kurt_misto or "").strip() or Pronajem.default_kurt_misto(slot.kurt)
        fmt_label = _kurt_misto_label(misto, slot.kurt)
        cena_total = Decimal(slot.cena)
        time_range = f"{slot.cas_od.strftime('%H:%M')}–{end_t.strftime('%H:%M')}"
        sazba = _sazba_z_celkem(
            cena_total, dur, SystemNastaveni.pronajem_ceny_choices(slot.kurt)
        )
        sazba_str = str(
            sazba.quantize(Decimal("1")) if sazba == sazba.to_integral_value() else sazba
        )
        sazba_label = f"{sazba_str} Kč"
        return {
            "ok": True,
            "id": slot.pk,
            "dow": int(slot.den),
            "time": slot.cas_od.strftime("%H:%M"),
            "delka_minut": dur,
            "kurt": slot.kurt or "",
            "kurt_misto": misto,
            "poznamka": slot.poznamka or "",
            "rezervujici": title,
            "cena": str(cena_total),
            "cena_label": sazba_label,
            "cena_hodina": sazba_str,
            "title": title,
            "sub": f"{time_range} · {sazba_label}",
            "time_range": time_range,
            "names": [title],
            "fmt_label": fmt_label,
        }

    def schedule_staly_delete_view(self, request, slot_id: int):
        forbidden = self._forbid_unless_platform(request)
        if forbidden:
            return forbidden
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": _("Method not allowed.")}, status=405)
        slot = StalyPronajemSlot.objects.filter(pk=slot_id).first()
        if slot is None:
            return JsonResponse({"ok": False, "error": _("Slot nenalezen.")}, status=404)
        linked = delete_pronajem_linked_to_staly_slot(slot)
        slot.delete()
        return JsonResponse({"ok": True, "id": slot_id, "linked": linked})

    def schedule_materialize_view(self, request):
        forbidden = self._forbid_unless_platform(request)
        if forbidden:
            return forbidden
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
        return JsonResponse(materialize_pronajem_for_date(target))

    def schedule_predpokladany_skip_view(self, request):
        forbidden = self._forbid_unless_platform(request)
        if forbidden:
            return forbidden
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
            deleted, _ = PredpokladanyPronajemSlot.objects.filter(pk=predp_id, datum=day).delete()
            if not deleted:
                return JsonResponse({"ok": False, "error": _("Slot nenalezen.")}, status=404)
            return JsonResponse({"ok": True, "date": day.isoformat(), "predpokladany_id": predp_id})

        try:
            slot_id = int(payload.get("staly_slot_id") or payload.get("ghost_slot_id"))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": _("Neplatný slot.")}, status=400)
        staly = StalyPronajemSlot.objects.filter(pk=slot_id).first()
        if not staly:
            return JsonResponse({"ok": False, "error": _("Slot nenalezen.")}, status=404)
        PredpokladanyPronajemSkip.objects.get_or_create(datum=day, staly_slot=staly)
        return JsonResponse({"ok": True, "date": day.isoformat(), "staly_slot_id": slot_id})
