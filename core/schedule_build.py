"""Sdílené sestavení dat pro rozvrh tréninků (týden / den)."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone as dj_tz

from .admin_utils import trener_label
from .models import Cenik, CenikFormat, Hrac, StalyRozvrhSlot, SystemNastaveni, Trening
from .predpokladany import append_ghost_events_for_week

User = get_user_model()

CZECH_DOW = ["po", "út", "st", "čt", "pá", "so", "ne"]


def format_slug(s: str) -> str:
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


def assign_event_lanes(evs: list[dict]) -> None:
    if not evs:
        return
    evs.sort(key=lambda e: (e["offset_min"], e["dur_min"]))

    cluster: list[dict] = []
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


def build_quick_add_options(*, trainer_id: str | int | None = "", for_date: date | None = None) -> dict:
    nast = None
    try:
        nast = SystemNastaveni.load()
    except Exception:
        pass
    defaults = (
        SystemNastaveni.training_defaults(for_date=for_date or dj_tz.localdate())
        if nast
        else {"delka_minut": 60, "kurt": ""}
    )
    trainers_qs = User.objects.order_by("username")
    return {
        "trainers": [{"id": u.pk, "label": trener_label(u)} for u in trainers_qs],
        "formats": [
            {"value": c[0], "label": c[1]}
            for c in CenikFormat.choices()
            if c[0]
        ],
        "sezony": [],
        "kurty": [
            {"value": c[0], "label": str(c[1])}
            for c in Cenik.Kurt.choices
            if c[0]
        ],
        "delky": [
            {"value": c[0], "label": str(c[1])}
            for c in SystemNastaveni.DELKA_MINUT_CHOICES
        ],
        "players": [
            {"id": h.pk, "jmeno": h.cele_jmeno}
            for h in Hrac.objects.order_by("prijmeni", "jmeno")[:800]
        ],
        "defaults": {
            "delka_minut": int(defaults.get("delka_minut") or 60),
            "sezona": "",
            "kurt": (defaults.get("kurt") or "").strip(),
            "trener": int(trainer_id) if trainer_id else None,
        },
    }


def build_trening_schedule(
    *,
    base_date: date | None = None,
    rozvrh_mode: str = "aktualni",
    trainer_id: str | int | None = "",
    mode: str = "week",
) -> dict:
    """
    Sestaví dny + eventy pro rozvrh.
    mode: 'week' | 'day'
    rozvrh_mode: aktualni | staly | predpokladany
    """
    if base_date is None:
        base_date = dj_tz.localdate()
    rozvrh_mode = (rozvrh_mode or "aktualni").strip().lower()
    if rozvrh_mode not in ("aktualni", "staly", "predpokladany"):
        rozvrh_mode = "aktualni"
    is_staly = rozvrh_mode == "staly"
    is_predpokladany = rozvrh_mode == "predpokladany"
    if mode not in ("week", "day"):
        mode = "week"

    try:
        nast = SystemNastaveni.load()
    except Exception:
        nast = None

    hours = nast.schedule_hours() if nast else list(range(6, 23))
    day_start_min = hours[0] * 60 if hours else 6 * 60
    hour_count = len(hours) if hours else 16

    start_day = base_date if mode == "day" else (base_date - timedelta(days=base_date.weekday()))
    end_day = start_day if mode == "day" else (start_day + timedelta(days=6))

    days = []
    for i in range((end_day - start_day).days + 1):
        d = start_day + timedelta(days=i)
        if is_staly:
            label = CZECH_DOW[d.weekday()]
        else:
            label = f"{CZECH_DOW[d.weekday()]} {d.strftime('%d.%m.')}"
        days.append({"date": d, "dow": d.weekday(), "label": label, "events": []})
    idx_by_date = {(start_day + timedelta(days=i)): i for i in range(len(days))}
    idx_by_dow = {days[i]["dow"]: i for i in range(len(days))}

    if is_staly:
        slots_qs = (
            StalyRozvrhSlot.objects.select_related("trener")
            .prefetch_related("hraci")
            .order_by("den", "cas_od", "id")
        )
        if trainer_id:
            slots_qs = slots_qs.filter(trener_id=trainer_id)
        for slot in slots_qs:
            i = idx_by_dow.get(int(slot.den))
            if i is None:
                continue
            start_min = slot.cas_od.hour * 60 + slot.cas_od.minute
            offset = max(0, start_min - day_start_min)
            dur = int(slot.delka_minut or 60)
            end_t = (
                datetime.combine(date.min, slot.cas_od) + timedelta(minutes=dur)
            ).time()
            fmt_label = slot.get_format_display()
            fmt_slug = format_slug(fmt_label)
            fmt_code = (slot.format or "").lower().replace("_", "-")
            players = []
            player_ids = []
            for hrac in slot.hraci.all():
                label = (hrac.prijmeni or "").strip() or (hrac.jmeno or "").strip() or hrac.cele_jmeno
                players.append(label)
                player_ids.append(hrac.pk)
            days[i]["events"].append({
                "id": slot.id,
                "offset_min": offset,
                "dur_min": dur,
                "end_min": offset + dur,
                "names": players,
                "title": ", ".join(players) or fmt_label or "—",
                "sub": f"{slot.cas_od.strftime('%H:%M')}–{end_t.strftime('%H:%M')}",
                "fmt": fmt_slug,
                "fmt_code": fmt_code,
                "fmt_label": fmt_label,
                "is_staly": True,
                "is_ghost": False,
                "trener_id": slot.trener_id or "",
                "format": slot.format or "",
                "kurt": slot.kurt or "",
                "poznamka": slot.poznamka or "",
                "hraci_ids": player_ids,
                "time": slot.cas_od.strftime("%H:%M"),
                "dow": int(slot.den),
            })
    else:
        start_dt = dj_tz.make_aware(datetime.combine(start_day, time.min))
        end_dt = dj_tz.make_aware(datetime.combine(end_day, time.max))
        qs = (
            Trening.objects.filter(datum__range=(start_dt, end_dt))
            .select_related("trener")
            .prefetch_related("dochazky__hrac")
            .order_by("datum", "id")
        )
        if trainer_id:
            qs = qs.filter(trener_id=trainer_id)
        for t in qs:
            local = dj_tz.localtime(t.datum) if dj_tz.is_aware(t.datum) else t.datum
            day = local.date()
            i = idx_by_date.get(day)
            if i is None:
                continue
            start_min = local.hour * 60 + local.minute
            offset = max(0, start_min - day_start_min)
            dur = int(t.delka_minut)
            end_local = local + timedelta(minutes=dur)
            fmt_label = t.get_format_display()
            fmt_slug = format_slug(fmt_label)
            fmt_code = (t.format or "").lower().replace("_", "-")
            players = []
            player_ids = []
            for dch in t.dochazky.all():
                if not dch.prisel:
                    continue
                hrac = dch.hrac
                label = (hrac.prijmeni or "").strip() or (hrac.jmeno or "").strip() or hrac.cele_jmeno
                players.append(label)
                player_ids.append(hrac.pk)
            days[i]["events"].append({
                "id": t.id,
                "offset_min": offset,
                "dur_min": dur,
                "end_min": offset + dur,
                "names": players,
                "title": ", ".join(players) or "—",
                "sub": f"{local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}",
                "fmt": fmt_slug,
                "fmt_code": fmt_code,
                "fmt_label": fmt_label,
                "is_staly": False,
                "is_ghost": False,
                "trener_id": t.trener_id or "",
                "format": t.format or "",
                "kurt": t.kurt or "",
                "poznamka": t.poznamka or "",
                "hraci_ids": player_ids,
                "date": local.strftime("%Y-%m-%d"),
                "time": local.strftime("%H:%M"),
            })

        if is_predpokladany:
            append_ghost_events_for_week(
                days,
                today=dj_tz.localdate(),
                trainer_id=trainer_id,
                day_start_min=day_start_min,
                slug_fn=format_slug,
            )

    for day in days:
        assign_event_lanes(day["events"])

    quick_add_options = build_quick_add_options(trainer_id=trainer_id, for_date=base_date)
    trainers_qs = User.objects.order_by("username")
    today = dj_tz.localdate()
    tomorrow = today + timedelta(days=1)
    step = 7 if mode == "week" else 1

    return {
        "view_mode": mode,
        "rozvrh_mode": rozvrh_mode,
        "is_staly": is_staly,
        "is_predpokladany": is_predpokladany,
        "trainers": trainers_qs,
        "selected_trainer": int(trainer_id) if trainer_id else "",
        "date_value": base_date.strftime("%Y-%m-%d"),
        "prev_date": (base_date - timedelta(days=step)).strftime("%Y-%m-%d"),
        "next_date": (base_date + timedelta(days=step)).strftime("%Y-%m-%d"),
        "add_training_url": reverse("admin:core_trening_add"),
        "quick_add_url": reverse("admin:core_trening_schedule_quick_add"),
        "move_url": reverse("admin:core_trening_schedule_move"),
        "delete_url": reverse("admin:core_trening_schedule_delete"),
        "staly_save_url": reverse("admin:core_trening_schedule_staly_save"),
        "staly_delete_url_template": reverse(
            "admin:core_trening_schedule_staly_delete", args=[0]
        ).replace("/0/", "/{id}/"),
        "materialize_url": reverse("admin:core_trening_schedule_materialize"),
        "predpokladany_skip_url": reverse("admin:core_trening_schedule_predpokladany_skip"),
        "today_label": today.strftime("%d.%m.%Y"),
        "tomorrow_label": tomorrow.strftime("%d.%m.%Y"),
        "quick_add_options_json": json.dumps(quick_add_options, ensure_ascii=False),
        "hours": hours,
        "day_start_min": day_start_min,
        "hour_count": hour_count,
        "sched_start_hour": hours[0] if hours else 6,
        "days": days,
        "event_count": sum(len(d["events"]) for d in days),
    }
