"""Předpokládaný rozvrh pronájmů: ghosty týdne + materializace do Pronajem."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone as dj_tz

from .models import (
    PredpokladanyPronajemSkip,
    PredpokladanyPronajemSlot,
    Pronajem,
    StalyPronajemSlot,
    SystemNastaveni,
)


def _aware_dt(day: date, cas: time) -> datetime:
    dt = datetime.combine(day, cas)
    if settings.USE_TZ:
        return dj_tz.make_aware(dt, dj_tz.get_current_timezone())
    return dt


def _local_dt(dt: datetime) -> datetime:
    if dj_tz.is_aware(dt):
        return dj_tz.localtime(dt)
    return dt


def existing_pronajem_at(
    day: date,
    cas: time,
    *,
    kurt_misto: str = "",
    kurt: str = "",
) -> Pronajem | None:
    """Stejný začátek + stejný kurt = konflikt. Jiný kurt ve stejný čas je OK."""
    start = _aware_dt(day, cas)
    end = start + timedelta(minutes=1)
    qs = Pronajem.objects.filter(datum__gte=start, datum__lt=end)
    misto = (kurt_misto or "").strip()
    if not misto and kurt:
        misto = Pronajem.default_kurt_misto(kurt)
    if misto:
        qs = qs.filter(kurt_misto=misto)
    return qs.order_by("id").first()


def create_pronajem_from_fields(
    *,
    day: date,
    cas: time,
    delka_minut: int,
    kurt: str,
    rezervujici: str,
    cena,
    format: str = Pronajem.FORMAT_DEFAULT,
    poznamka: str = "",
    kurt_misto: str = "",
) -> Pronajem | None:
    misto = (kurt_misto or "").strip() or Pronajem.default_kurt_misto(kurt)
    if existing_pronajem_at(day, cas, kurt_misto=misto, kurt=kurt):
        return None
    dt = _aware_dt(day, cas)
    with transaction.atomic():
        return Pronajem.objects.create(
            datum=dt,
            delka_minut=int(delka_minut or 60),
            kurt=kurt,
            kurt_misto=misto,
            format=format or Pronajem.FORMAT_DEFAULT,
            rezervujici=(rezervujici or "").strip() or "—",
            cena=Decimal(str(cena)),
            poznamka=poznamka or "",
        )


def create_pronajem_from_staly_slot(slot: StalyPronajemSlot, day: date) -> Pronajem | None:
    if not SystemNastaveni.staly_pronajem_platny_pro(day):
        return None
    if PredpokladanyPronajemSkip.objects.filter(datum=day, staly_slot_id=slot.pk).exists():
        return None
    return create_pronajem_from_fields(
        day=day,
        cas=slot.cas_od,
        delka_minut=int(slot.delka_minut or 60),
        kurt=slot.kurt,
        kurt_misto=getattr(slot, "kurt_misto", "") or "",
        rezervujici=slot.rezervujici,
        cena=slot.cena,
        format=slot.format,
        poznamka=slot.poznamka or "",
    )


def backfill_pronajem_from_staly_slot(
    slot: StalyPronajemSlot,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict:
    """
    Zapiš skutečné Pronajem od začátku platnosti stálého rozvrhu do dneška
    (včetně) pro daný den v týdnu. Budoucí dny zůstávají ghosty v předpokládaném.
    """
    try:
        od, do = SystemNastaveni.load().staly_pronajem_obdobi()
    except Exception:
        od, do = date(2026, 10, 10), date(2027, 4, 9)
    today = dj_tz.localdate()
    start = from_date or od or today
    end = to_date or today
    if do is not None and end > do:
        end = do
    if end > today:
        end = today
    if start > end:
        return {"created": 0, "skipped": 0}

    created = 0
    skipped = 0
    dow = int(slot.den)
    day = start
    # posuň na první den se stejným DOW
    while day.weekday() != dow and day <= end:
        day += timedelta(days=1)
    while day <= end:
        obj = create_pronajem_from_staly_slot(slot, day)
        if obj:
            created += 1
        else:
            skipped += 1
        day += timedelta(days=7)
    return {"created": created, "skipped": skipped}


def backfill_all_staly_pronajem_slots(
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict:
    """Doplň aktuální Pronajem ze všech stálých slotů (od–dnes)."""
    total_created = 0
    total_skipped = 0
    for slot in StalyPronajemSlot.objects.all().order_by("den", "cas_od", "id"):
        result = backfill_pronajem_from_staly_slot(
            slot, from_date=from_date, to_date=to_date
        )
        total_created += result["created"]
        total_skipped += result["skipped"]
    return {"created": total_created, "skipped": total_skipped}


def delete_pronajem_linked_to_staly_slot(slot: StalyPronajemSlot) -> dict:
    """
    Smaž aktuální Pronajem vzniklé ze stálého slotu (stejný DOW + čas + kurt)
    v období platnosti, plus předpokládané override a skipy.
    """
    try:
        od, do = SystemNastaveni.load().staly_pronajem_obdobi()
    except Exception:
        od, do = date(2026, 10, 10), date(2027, 4, 9)

    misto = (getattr(slot, "kurt_misto", "") or "").strip() or Pronajem.default_kurt_misto(
        slot.kurt or ""
    )
    cas = slot.cas_od
    dow = int(slot.den)
    cas_norm = cas.replace(second=0, microsecond=0)

    qs = Pronajem.objects.all()
    if od:
        qs = qs.filter(datum__gte=_aware_dt(od, time.min))
    if do:
        qs = qs.filter(datum__lte=_aware_dt(do, time.max))

    to_delete_ids: list[int] = []
    for p in qs.only("id", "datum", "kurt", "kurt_misto").iterator():
        local = _local_dt(p.datum)
        day = local.date()
        if day.weekday() != dow:
            continue
        if local.time().replace(second=0, microsecond=0) != cas_norm:
            continue
        p_misto = (p.kurt_misto or "").strip() or Pronajem.default_kurt_misto(p.kurt or "")
        if p_misto != misto:
            continue
        to_delete_ids.append(p.pk)

    deleted_pronajem = 0
    if to_delete_ids:
        deleted_pronajem, _ = Pronajem.objects.filter(pk__in=to_delete_ids).delete()

    deleted_predp = PredpokladanyPronajemSlot.objects.filter(zdroj_staly_id=slot.pk).delete()[0]
    deleted_skip = PredpokladanyPronajemSkip.objects.filter(staly_slot_id=slot.pk).delete()[0]

    return {
        "pronajem": deleted_pronajem,
        "predpokladany": deleted_predp,
        "skip": deleted_skip,
    }


def create_pronajem_from_predpokladany_slot(slot: PredpokladanyPronajemSlot) -> Pronajem | None:
    obj = create_pronajem_from_fields(
        day=slot.datum,
        cas=slot.cas_od,
        delka_minut=int(slot.delka_minut or 60),
        kurt=slot.kurt,
        kurt_misto=getattr(slot, "kurt_misto", "") or "",
        rezervujici=slot.rezervujici,
        cena=slot.cena,
        format=slot.format,
        poznamka=slot.poznamka or "",
    )
    if obj:
        slot.delete()
    return obj


def materialize_pronajem_for_date(target_date: date | None = None) -> dict:
    if target_date is None:
        target_date = dj_tz.localdate()

    created = 0
    skipped_exist = 0
    skipped_user = 0
    errors: list[str] = []

    oneoffs = PredpokladanyPronajemSlot.objects.filter(datum=target_date).order_by("cas_od", "id")
    for slot in list(oneoffs):
        try:
            obj = create_pronajem_from_predpokladany_slot(slot)
            if obj:
                created += 1
            else:
                skipped_exist += 1
                slot.delete()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"predpokladany={slot.pk}: {exc}")

    staly_platny = SystemNastaveni.staly_pronajem_platny_pro(target_date)
    if staly_platny:
        dow = target_date.weekday()
        slots = StalyPronajemSlot.objects.filter(den=dow).order_by("cas_od", "id")
        skip_ids = set(
            PredpokladanyPronajemSkip.objects.filter(
                datum=target_date, staly_slot_id__in=slots.values_list("id", flat=True)
            ).values_list("staly_slot_id", flat=True)
        )

        for slot in slots:
            if slot.pk in skip_ids:
                skipped_user += 1
                continue
            misto = (getattr(slot, "kurt_misto", "") or "").strip() or Pronajem.default_kurt_misto(
                slot.kurt or ""
            )
            if existing_pronajem_at(
                target_date, slot.cas_od, kurt_misto=misto, kurt=slot.kurt or ""
            ):
                skipped_exist += 1
                continue
            try:
                obj = create_pronajem_from_staly_slot(slot, target_date)
                if obj:
                    created += 1
                else:
                    skipped_exist += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"slot={slot.pk}: {exc}")

    return {
        "ok": True,
        "date": target_date.isoformat(),
        "created": created,
        "skipped_exist": skipped_exist,
        "skipped_user": skipped_user,
        "errors": errors,
    }


def append_pronajem_ghost_events_for_week(
    days: list[dict],
    *,
    today: date | None = None,
    day_start_min: int = 360,
) -> None:
    if today is None:
        today = dj_tz.localdate()

    future_days = [d for d in days if d["date"] >= today]
    if not future_days:
        return

    date_list = [d["date"] for d in future_days]
    idx_by_date = {d["date"]: i for i, d in enumerate(days)}
    idx_by_dow = {d["dow"]: i for i, d in enumerate(days)}

    # Klíč: (datum, čas, kurt_misto) – více kurtů ve stejný čas je OK
    existing_keys: set[tuple] = set()
    for day in future_days:
        for ev in day.get("events") or []:
            if ev.get("is_staly") or ev.get("is_ghost"):
                continue
            time_key = (ev.get("time") or "").strip()
            misto = (ev.get("kurt_misto") or "").strip()
            if time_key:
                existing_keys.add((day["date"], time_key, misto))

    start_dt = _aware_dt(min(date_list), time.min)
    end_dt = _aware_dt(max(date_list), time.max)
    for p in Pronajem.objects.filter(datum__range=(start_dt, end_dt)).only(
        "id", "datum", "kurt_misto", "kurt"
    ):
        local = _local_dt(p.datum)
        misto = (p.kurt_misto or "").strip() or Pronajem.default_kurt_misto(p.kurt or "")
        existing_keys.add((local.date(), local.strftime("%H:%M"), misto))

    def _ghost(
        *,
        event_id: str,
        ghost_slot_id,
        predpokladany_id,
        day_date: date,
        cas_od: time,
        delka_minut: int,
        rezervujici: str,
        cena,
        kurt: str,
        kurt_misto: str,
        poznamka: str,
        dow: int,
    ) -> dict:
        start_min = cas_od.hour * 60 + cas_od.minute
        offset = max(0, start_min - day_start_min)
        dur = int(delka_minut or 60)
        end_t = (datetime.combine(date.min, cas_od) + timedelta(minutes=dur)).time()
        time_key = cas_od.strftime("%H:%M")
        title = (rezervujici or "").strip() or "—"
        cena_total = Decimal(str(cena))
        misto = (kurt_misto or "").strip() or Pronajem.default_kurt_misto(kurt)
        labels = dict(Pronajem.KurtMisto.choices)
        fmt_label = str(labels.get(misto, misto) or kurt or "—")
        time_range = f"{time_key}–{end_t.strftime('%H:%M')}"
        hours = (Decimal(dur) / Decimal(60)).quantize(Decimal("0.01"))
        sazba = (cena_total / hours) if hours else cena_total
        sazba_str = str(
            sazba.quantize(Decimal("1")) if sazba == sazba.to_integral_value() else sazba
        )
        sazba_label = f"{sazba_str} Kč"
        return {
            "id": event_id,
            "ghost_slot_id": ghost_slot_id or "",
            "predpokladany_id": predpokladany_id or "",
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
            "is_ghost": True,
            "rezervujici": title,
            "cena": str(cena_total),
            "cena_label": sazba_label,
            "cena_hodina": sazba_str,
            "kurt": kurt or "",
            "kurt_misto": misto,
            "poznamka": poznamka or "",
            "time": time_key,
            "dow": dow,
            "date": day_date.isoformat(),
            "format": Pronajem.FORMAT_DEFAULT,
        }

    oneoffs = PredpokladanyPronajemSlot.objects.filter(datum__in=date_list).order_by(
        "datum", "cas_od", "id"
    )
    for slot in oneoffs:
        time_key = slot.cas_od.strftime("%H:%M")
        misto = (getattr(slot, "kurt_misto", "") or "").strip() or Pronajem.default_kurt_misto(
            slot.kurt or ""
        )
        if (slot.datum, time_key, misto) in existing_keys:
            continue
        i = idx_by_date.get(slot.datum)
        if i is None:
            continue
        days[i]["events"].append(
            _ghost(
                event_id=f"predp-p-{slot.pk}",
                ghost_slot_id="",
                predpokladany_id=slot.pk,
                day_date=slot.datum,
                cas_od=slot.cas_od,
                delka_minut=slot.delka_minut,
                rezervujici=slot.rezervujici,
                cena=slot.cena,
                kurt=slot.kurt,
                kurt_misto=misto,
                poznamka=slot.poznamka or "",
                dow=slot.datum.weekday(),
            )
        )
        existing_keys.add((slot.datum, time_key, misto))

    try:
        nast = SystemNastaveni.load()
        staly_od, staly_do = nast.staly_pronajem_obdobi()
    except Exception:
        staly_od, staly_do = date(2026, 10, 10), date(2027, 4, 9)

    dows = {d["dow"] for d in future_days}
    staly_qs = StalyPronajemSlot.objects.filter(den__in=dows).order_by("den", "cas_od", "id")
    skip_pairs = set(
        PredpokladanyPronajemSkip.objects.filter(
            datum__in=date_list,
            staly_slot_id__in=staly_qs.values_list("id", flat=True),
        ).values_list("datum", "staly_slot_id")
    )

    for slot in staly_qs:
        day_date = None
        for d in future_days:
            if d["dow"] == int(slot.den):
                day_date = d["date"]
                break
        if day_date is None:
            continue
        if staly_od and day_date < staly_od:
            continue
        if staly_do and day_date > staly_do:
            continue
        if (day_date, slot.pk) in skip_pairs:
            continue
        time_key = slot.cas_od.strftime("%H:%M")
        misto = (getattr(slot, "kurt_misto", "") or "").strip() or Pronajem.default_kurt_misto(
            slot.kurt or ""
        )
        if (day_date, time_key, misto) in existing_keys:
            continue
        i = idx_by_dow.get(int(slot.den))
        if i is None:
            continue
        days[i]["events"].append(
            _ghost(
                event_id=f"staly-p-{slot.pk}-{day_date.isoformat()}",
                ghost_slot_id=slot.pk,
                predpokladany_id="",
                day_date=day_date,
                cas_od=slot.cas_od,
                delka_minut=slot.delka_minut,
                rezervujici=slot.rezervujici,
                cena=slot.cena,
                kurt=slot.kurt,
                kurt_misto=misto,
                poznamka=slot.poznamka or "",
                dow=int(slot.den),
            )
        )
        existing_keys.add((day_date, time_key, misto))
