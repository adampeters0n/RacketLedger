"""Předpokládaný rozvrh: sestavení týdne + materializace slotů do tréninků."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone as dj_tz

from .models import Dochazka, PredpokladanySkip, PredpokladanySlot, StalyRozvrhSlot, Trening
from .schedule_colors import color_for_format, format_slug


def _aware_dt(day: date, cas: time) -> datetime:
    dt = datetime.combine(day, cas)
    if settings.USE_TZ:
        return dj_tz.make_aware(dt, dj_tz.get_current_timezone())
    return dt


def _local_dt(dt: datetime) -> datetime:
    if dj_tz.is_aware(dt):
        return dj_tz.localtime(dt)
    return dt


def existing_trening_at(trener_id: int, day: date, cas: time) -> Trening | None:
    start = _aware_dt(day, cas)
    end = start + timedelta(minutes=1)
    return (
        Trening.objects.filter(trener_id=trener_id, datum__gte=start, datum__lt=end)
        .order_by("id")
        .first()
    )


def existing_trening_for_slot(slot: StalyRozvrhSlot, day: date) -> Trening | None:
    return existing_trening_at(slot.trener_id, day, slot.cas_od)


def create_trening_from_fields(
    *,
    trener,
    day: date,
    cas: time,
    delka_minut: int,
    format: str,
    kurt: str,
    poznamka: str = "",
    hraci=None,
) -> Trening | None:
    """Vytvoří Trening + Dochazku. Vrátí None pokud už existuje stejný trenér+čas."""
    if existing_trening_at(trener.pk, day, cas):
        return None

    dt = _aware_dt(day, cas)
    with transaction.atomic():
        trening = Trening.objects.create(
            trener=trener,
            datum=dt,
            delka_minut=int(delka_minut or 60),
            format=format,
            kurt=kurt,
            poznamka=poznamka or "",
        )
        for hrac in hraci or []:
            Dochazka.objects.create(trening=trening, hrac=hrac, prisel=True)
    return trening


def create_trening_from_staly_slot(slot: StalyRozvrhSlot, day: date) -> Trening | None:
    """Vytvoří Trening + Dochazku ze stálého slotu. Vrátí None pokud už existuje / skip."""
    if PredpokladanySkip.objects.filter(datum=day, staly_slot_id=slot.pk).exists():
        return None
    return create_trening_from_fields(
        trener=slot.trener,
        day=day,
        cas=slot.cas_od,
        delka_minut=int(slot.delka_minut or 60),
        format=slot.format,
        kurt=slot.kurt,
        poznamka=slot.poznamka or "",
        hraci=list(slot.hraci.all()),
    )


def create_trening_from_predpokladany_slot(slot: PredpokladanySlot) -> Trening | None:
    """Vytvoří Trening z jednorázového předpokládaného slotu a slot smaže."""
    trening = create_trening_from_fields(
        trener=slot.trener,
        day=slot.datum,
        cas=slot.cas_od,
        delka_minut=int(slot.delka_minut or 60),
        format=slot.format,
        kurt=slot.kurt,
        poznamka=slot.poznamka or "",
        hraci=list(slot.hraci.all()),
    )
    if trening:
        slot.delete()
    return trening


def materialize_for_date(target_date: date | None = None, *, trainer_id: int | str | None = None) -> dict:
    """
    Ze stálého + jednorázového předpokládaného vytvoří chybějící tréninky
    na daný den (default dnes).
    """
    if target_date is None:
        target_date = dj_tz.localdate()

    created = 0
    skipped_exist = 0
    skipped_user = 0
    errors: list[str] = []

    # 1) Jednorázové předpokládané sloty na tento den
    oneoffs = (
        PredpokladanySlot.objects.filter(datum=target_date)
        .select_related("trener")
        .prefetch_related("hraci")
        .order_by("cas_od", "id")
    )
    if trainer_id not in (None, ""):
        oneoffs = oneoffs.filter(trener_id=int(trainer_id))

    for slot in list(oneoffs):
        try:
            trening = create_trening_from_predpokladany_slot(slot)
            if trening:
                created += 1
            else:
                skipped_exist += 1
                slot.delete()
        except Exception as exc:  # noqa: BLE001 – batch job continues
            errors.append(f"predpokladany={slot.pk}: {exc}")

    # 2) Stálý rozvrh pro den v týdnu
    dow = target_date.weekday()
    slots = (
        StalyRozvrhSlot.objects.filter(den=dow)
        .select_related("trener")
        .prefetch_related("hraci")
        .order_by("cas_od", "id")
    )
    if trainer_id not in (None, ""):
        slots = slots.filter(trener_id=int(trainer_id))

    skip_ids = set(
        PredpokladanySkip.objects.filter(
            datum=target_date, staly_slot_id__in=slots.values_list("id", flat=True)
        ).values_list("staly_slot_id", flat=True)
    )

    for slot in slots:
        if slot.pk in skip_ids:
            skipped_user += 1
            continue
        if existing_trening_for_slot(slot, target_date):
            skipped_exist += 1
            continue
        try:
            trening = create_trening_from_staly_slot(slot, target_date)
            if trening:
                created += 1
            else:
                skipped_exist += 1
        except Exception as exc:  # noqa: BLE001 – batch job continues
            errors.append(f"slot={slot.pk}: {exc}")

    return {
        "ok": True,
        "date": target_date.isoformat(),
        "created": created,
        "skipped_exist": skipped_exist,
        "skipped_user": skipped_user,
        "errors": errors,
    }


def _ghost_event_dict(
    *,
    event_id: str,
    ghost_slot_id: int | None,
    predpokladany_id: int | None,
    day_date: date,
    cas_od: time,
    delka_minut: int,
    fmt_label: str,
    fmt_code: str,
    fmt_slug: str,
    format_val: str,
    kurt: str,
    poznamka: str,
    trener_id,
    players: list,
    player_ids: list,
    day_start_min: int,
    dow: int,
) -> dict:
    start_min = cas_od.hour * 60 + cas_od.minute
    offset = max(0, start_min - day_start_min)
    dur = int(delka_minut or 60)
    end_t = (datetime.combine(date.min, cas_od) + timedelta(minutes=dur)).time()
    time_key = cas_od.strftime("%H:%M")
    return {
        "id": event_id,
        "ghost_slot_id": ghost_slot_id or "",
        "predpokladany_id": predpokladany_id or "",
        "offset_min": offset,
        "dur_min": dur,
        "end_min": offset + dur,
        "names": players,
        "title": ", ".join(players) or fmt_label or "—",
        "sub": f"{time_key}–{end_t.strftime('%H:%M')}",
        "fmt": fmt_slug,
        "fmt_code": fmt_code,
        "fmt_label": fmt_label,
        "color": color_for_format(fmt_label),
        "is_staly": False,
        "is_ghost": True,
        "trener_id": trener_id or "",
        "format": format_val or "",
        "kurt": kurt or "",
        "poznamka": poznamka or "",
        "hraci_ids": player_ids,
        "time": time_key,
        "dow": dow,
        "date": day_date.isoformat(),
    }


def append_ghost_events_for_week(
    days: list[dict],
    *,
    today: date | None = None,
    trainer_id: int | str | None = "",
    day_start_min: int = 360,
    slug_fn=None,
) -> None:
    """
    Do budoucích dnů (včetně dnes) přidá duchy ze StalyRozvrhSlot a PredpokladanySlot,
    pokud ještě není trénink se stejným trenérem+časem a není skip.
    Mutuje days[].events in place.
    """
    if today is None:
        today = dj_tz.localdate()

    future_days = [d for d in days if d["date"] >= today]
    if not future_days:
        return

    dows = {d["dow"] for d in future_days}
    date_list = [d["date"] for d in future_days]
    date_by_dow = {d["dow"]: d["date"] for d in future_days}
    idx_by_dow = {d["dow"]: i for i, d in enumerate(days)}
    idx_by_date = {d["date"]: i for i, d in enumerate(days)}

    # Index existujících tréninků: (date, trener_id, HH:MM)
    existing_keys: set[tuple] = set()
    for day in future_days:
        for ev in day.get("events") or []:
            if ev.get("is_staly") or ev.get("is_ghost"):
                continue
            time_key = (ev.get("time") or "").strip()
            if not time_key and ev.get("sub"):
                time_key = str(ev["sub"]).split("–")[0].strip()
            if time_key:
                existing_keys.add((day["date"], ev.get("trener_id") or "", time_key))

    start_dt = _aware_dt(min(date_list), time.min)
    end_dt = _aware_dt(max(date_list), time.max)
    tqs = Trening.objects.filter(datum__range=(start_dt, end_dt)).only("id", "trener_id", "datum")
    if trainer_id not in (None, ""):
        tqs = tqs.filter(trener_id=int(trainer_id))
    for t in tqs:
        local = _local_dt(t.datum)
        existing_keys.add((local.date(), t.trener_id, local.strftime("%H:%M")))

    def _slug(label: str) -> str:
        if slug_fn:
            return slug_fn(label)
        return format_slug(label or "staly")

    # 1) Jednorázové předpokládané sloty
    oneoffs = (
        PredpokladanySlot.objects.filter(datum__in=date_list)
        .select_related("trener")
        .prefetch_related("hraci")
        .order_by("datum", "cas_od", "id")
    )
    if trainer_id not in (None, ""):
        oneoffs = oneoffs.filter(trener_id=int(trainer_id))

    for slot in oneoffs:
        time_key = slot.cas_od.strftime("%H:%M")
        if (slot.datum, slot.trener_id, time_key) in existing_keys:
            continue
        i = idx_by_date.get(slot.datum)
        if i is None:
            continue
        fmt_label = slot.get_format_display()
        fmt_slug = _slug(fmt_label)
        fmt_code = (slot.format or "").lower().replace("_", "-")
        players = []
        player_ids = []
        for hrac in slot.hraci.all():
            label = (hrac.prijmeni or "").strip() or (hrac.jmeno or "").strip() or hrac.cele_jmeno
            players.append(label)
            player_ids.append(hrac.pk)
        days[i]["events"].append(
            _ghost_event_dict(
                event_id=f"predp-{slot.pk}",
                ghost_slot_id=None,
                predpokladany_id=slot.pk,
                day_date=slot.datum,
                cas_od=slot.cas_od,
                delka_minut=int(slot.delka_minut or 60),
                fmt_label=fmt_label,
                fmt_code=fmt_code,
                fmt_slug=fmt_slug,
                format_val=slot.format or "",
                kurt=slot.kurt or "",
                poznamka=slot.poznamka or "",
                trener_id=slot.trener_id,
                players=players,
                player_ids=player_ids,
                day_start_min=day_start_min,
                dow=slot.datum.weekday(),
            )
        )
        existing_keys.add((slot.datum, slot.trener_id, time_key))

    # 2) Stálý rozvrh (pokud není skip / trénink / jednorázový override na stejném čase)
    slots = (
        StalyRozvrhSlot.objects.filter(den__in=dows)
        .select_related("trener")
        .prefetch_related("hraci")
        .order_by("den", "cas_od", "id")
    )
    if trainer_id not in (None, ""):
        slots = slots.filter(trener_id=int(trainer_id))

    skip_pairs = set(
        PredpokladanySkip.objects.filter(datum__in=date_list).values_list("datum", "staly_slot_id")
    )

    for slot in slots:
        day_date = date_by_dow.get(int(slot.den))
        if day_date is None or day_date < today:
            continue
        if (day_date, slot.pk) in skip_pairs:
            continue
        time_key = slot.cas_od.strftime("%H:%M")
        if (day_date, slot.trener_id, time_key) in existing_keys:
            continue

        i = idx_by_dow.get(int(slot.den))
        if i is None:
            continue

        fmt_label = slot.get_format_display()
        fmt_slug = _slug(fmt_label)
        fmt_code = (slot.format or "").lower().replace("_", "-")
        players = []
        player_ids = []
        for hrac in slot.hraci.all():
            label = (hrac.prijmeni or "").strip() or (hrac.jmeno or "").strip() or hrac.cele_jmeno
            players.append(label)
            player_ids.append(hrac.pk)

        days[i]["events"].append(
            _ghost_event_dict(
                event_id=f"ghost-{slot.pk}-{day_date.isoformat()}",
                ghost_slot_id=slot.pk,
                predpokladany_id=None,
                day_date=day_date,
                cas_od=slot.cas_od,
                delka_minut=int(slot.delka_minut or 60),
                fmt_label=fmt_label,
                fmt_code=fmt_code,
                fmt_slug=fmt_slug,
                format_val=slot.format or "",
                kurt=slot.kurt or "",
                poznamka=slot.poznamka or "",
                trener_id=slot.trener_id,
                players=players,
                player_ids=player_ids,
                day_start_min=day_start_min,
                dow=int(slot.den),
            )
        )
        existing_keys.add((day_date, slot.trener_id, time_key))
