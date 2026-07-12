"""Optimalizované sestavení dat pro admin analytiku."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from django.contrib.auth import get_user_model
from django.db.models import Sum, Case, When, F, Value, DecimalField, Q, Count
from django.db.models.functions import TruncMonth
from django.urls import reverse
from django.utils import timezone as dj_tz

from .admin_utils import month_range
from .models import (
    Dochazka,
    Hrac,
    OstatniNaklad,
    TrenerPlatba,
    TrenerProfil,
    TrenerSazba,
    Transakce,
    Trening,
)

User = get_user_model()

CZECH_MONTHS = {
    1: "Led", 2: "Úno", 3: "Bře", 4: "Dub", 5: "Kvě", 6: "Čer",
    7: "Čvc", 8: "Srp", 9: "Zář", 10: "Říj", 11: "Lis", 12: "Pro",
}


class TrenerRateLookup:
    """Sazby trenérů k datu – načtené hromadně, bez dotazu na každý trénink."""

    def __init__(self, user_ids: list[int]):
        ids = [i for i in user_ids if i]
        self._profiles = {
            p.user_id: p.sazba_za_hodinu
            for p in TrenerProfil.objects.filter(user_id__in=ids)
        }
        self._sazby: dict[int, list] = defaultdict(list)
        for s in TrenerSazba.objects.filter(user_id__in=ids).order_by("-platnost_od"):
            self._sazby[s.user_id].append(s)
        self._cache: dict[tuple[int, date], Decimal] = {}

    def for_user_date(self, user_id: int | None, dt) -> Decimal:
        if not user_id:
            return Decimal("500.00")
        if hasattr(dt, "date"):
            if dj_tz.is_aware(dt):
                dt = dj_tz.localtime(dt)
            d = dt.date()
        else:
            d = dt
        key = (user_id, d)
        if key in self._cache:
            return self._cache[key]
        rate = None
        for s in self._sazby.get(user_id, []):
            if s.platnost_od <= d and (s.platnost_do is None or s.platnost_do >= d):
                rate = s.sazba_za_hodinu
                break
        if rate is None:
            rate = self._profiles.get(user_id, Decimal("500.00"))
        self._cache[key] = rate
        return rate

    def earned_from_rows(self, rows) -> Decimal:
        total = Decimal("0.00")
        for row in rows:
            uid = row.get("trener_id") if isinstance(row, dict) else row[0]
            dt = row.get("datum") if isinstance(row, dict) else row[1]
            mins = row.get("delka_minut") if isinstance(row, dict) else row[2]
            if not uid or not mins:
                continue
            rate = self.for_user_date(uid, dt)
            total += (Decimal(mins) / Decimal(60) * rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        return total


def month_end_from_start(month_start: date) -> date:
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1, day=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1, day=1)
    return next_month - timedelta(days=1)


def charges_sum_between(day_from: date, day_to: date) -> Decimal:
    return Decimal(
        Transakce.objects.filter(
            trening__datum__date__gte=day_from,
            trening__datum__date__lte=day_to,
            typ=Transakce.Typ.NAUCTOVANO,
        ).aggregate(s=Sum("castka"))["s"]
        or 0
    )


def payments_sum_between(day_from: date, day_to: date) -> Decimal:
    return Decimal(
        Transakce.objects.filter(
            vytvoreno__date__gte=day_from,
            vytvoreno__date__lte=day_to,
            typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
        ).aggregate(s=Sum("castka"))["s"]
        or 0
    )


def month_stats_for_range(month_start: date, month_end: date):
    month_trainings = Trening.objects.filter(
        datum__date__gte=month_start,
        datum__date__lte=month_end,
    )
    month_total_min = month_trainings.aggregate(s=Sum("delka_minut"))["s"] or 0
    month_hours = (Decimal(month_total_min) / Decimal(60)).quantize(Decimal("0.01"))
    month_charged = charges_sum_between(month_start, month_end)
    month_paid = payments_sum_between(month_start, month_end)
    return month_hours, month_charged, month_paid


def _hours_by_month(today: date) -> dict[date, Decimal]:
    rows = (
        Trening.objects.annotate(month=TruncMonth("datum"))
        .values("month")
        .annotate(mins=Sum("delka_minut"))
    )
    out: dict[date, Decimal] = {}
    for row in rows:
        ms = _month_start(row["month"])
        out[ms] = (Decimal(row["mins"] or 0) / Decimal(60)).quantize(Decimal("0.01"))
    return out


def _month_stats_maps(today: date):
    return {
        "hours": _hours_by_month(today),
        "charged": _sum_by_month(
            Transakce.objects.filter(typ=Transakce.Typ.NAUCTOVANO),
            "trening__datum",
        ),
        "paid": _sum_by_month(
            Transakce.objects.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]),
            "vytvoreno",
        ),
    }


def _month_stats_entry(month_start: date, maps) -> tuple[Decimal, Decimal, Decimal]:
    hours = maps["hours"].get(month_start, Decimal("0"))
    charged = maps["charged"].get(month_start, Decimal("0"))
    paid = maps["paid"].get(month_start, Decimal("0"))
    return hours, charged, paid


def monthly_chart_series(today: date, num_months: int, maps=None):
    if maps is None:
        maps = _month_stats_maps(today)
    data = []
    current_day = today
    for _ in range(num_months):
        month_start = current_day.replace(day=1)
        label = f"{CZECH_MONTHS[month_start.month]} '{month_start.strftime('%y')}"
        hours, charged, paid = _month_stats_entry(month_start, maps)
        data.append({
            "label": label,
            "hours": float(hours),
            "charged": float(charged),
            "paid": float(paid),
        })
        current_day = month_start - timedelta(days=1)
    data.reverse()
    return data


def alltime_monthly_chart_series(today: date, maps=None):
    first_dt = Trening.objects.order_by("datum").values_list("datum", flat=True).first()
    if not first_dt:
        return []
    first_date = dj_tz.localtime(first_dt).date() if dj_tz.is_aware(first_dt) else first_dt.date()
    month_start = first_date.replace(day=1)
    end_month = today.replace(day=1)
    if maps is None:
        maps = _month_stats_maps(today)
    data = []
    while month_start <= end_month:
        label = f"{CZECH_MONTHS[month_start.month]} '{month_start.strftime('%y')}"
        hours, charged, paid = _month_stats_entry(month_start, maps)
        data.append({
            "label": label,
            "hours": float(hours),
            "charged": float(charged),
            "paid": float(paid),
        })
        if month_start.month == 12:
            month_start = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            month_start = month_start.replace(month=month_start.month + 1, day=1)
    return data


def ostatni_naklady_sum_for_month(month_start: date) -> Decimal:
    month_end = month_end_from_start(month_start)
    return Decimal(
        OstatniNaklad.objects.filter(
            mesic__gte=month_start,
            mesic__lte=month_end,
        ).aggregate(s=Sum("castka"))["s"]
        or 0
    )


def _month_start(d) -> date:
    if hasattr(d, "date"):
        d = d.date() if not dj_tz.is_aware(d) else dj_tz.localtime(d).date()
    return d.replace(day=1)


def _sum_by_month(qs, date_field: str) -> dict[date, Decimal]:
    rows = (
        qs.annotate(month=TruncMonth(date_field))
        .values("month")
        .annotate(total=Sum("castka"))
    )
    out: dict[date, Decimal] = {}
    for row in rows:
        month_val = row["month"]
        key = _month_start(month_val)
        out[key] = Decimal(row["total"] or 0)
    return out


def _trener_earned_by_month(rate_lookup: TrenerRateLookup, today: date) -> dict[date, Decimal]:
    earned: dict[date, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in Trening.objects.values("trener_id", "datum", "delka_minut"):
        dt = row["datum"]
        if dj_tz.is_aware(dt):
            d = dj_tz.localtime(dt).date()
        else:
            d = dt.date() if hasattr(dt, "date") else dt
        if d > today:
            continue
        ms = d.replace(day=1)
        mins = row["delka_minut"] or 0
        if not row["trener_id"] or not mins:
            continue
        rate = rate_lookup.for_user_date(row["trener_id"], dt)
        earned[ms] += (Decimal(mins) / Decimal(60) * rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return earned


def _accounting_entry_from_maps(month_start: date, today: date, paid_map, charged_map, trener_paid_map, other_map, earned_map):
    month_end = min(month_end_from_start(month_start), today)
    label = f"{CZECH_MONTHS[month_start.month]} '{month_start.strftime('%y')}"

    m_paid = paid_map.get(month_start, Decimal("0"))
    m_charged = charged_map.get(month_start, Decimal("0"))
    m_trener_paid = trener_paid_map.get(month_start, Decimal("0"))
    m_trener_earned = earned_map.get(month_start, Decimal("0"))
    m_other = other_map.get(month_start, Decimal("0"))
    m_cashflow = float((m_paid - m_trener_paid - m_other).quantize(Decimal("0.01")))
    m_gross = float((m_charged - m_trener_earned).quantize(Decimal("0.01")))

    return {
        "label": label,
        "cashflow": m_cashflow,
        "gross_profit": m_gross,
        "net_profit": m_cashflow,
        "paid": float(m_paid),
        "charged": float(m_charged),
        "trener_paid": float(m_trener_paid),
        "trener_earned": float(m_trener_earned),
        "other_costs": float(m_other),
    }


def _accounting_maps(today: date, rate_lookup: TrenerRateLookup):
    paid_map = _sum_by_month(
        Transakce.objects.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]),
        "vytvoreno",
    )
    charged_map = _sum_by_month(
        Transakce.objects.filter(typ=Transakce.Typ.NAUCTOVANO),
        "trening__datum",
    )
    trener_paid_map = _sum_by_month(TrenerPlatba.objects.all(), "vytvoreno")
    other_map = _sum_by_month(OstatniNaklad.objects.all(), "mesic")
    earned_map = _trener_earned_by_month(rate_lookup, today)
    return paid_map, charged_map, trener_paid_map, other_map, earned_map


def accounting_entry_for_month(month_start: date, today: date, rate_lookup: TrenerRateLookup):
    paid_map, charged_map, trener_paid_map, other_map, earned_map = _accounting_maps(today, rate_lookup)
    return _accounting_entry_from_maps(
        month_start, today, paid_map, charged_map, trener_paid_map, other_map, earned_map
    )


def accounting_series(today: date, num_months: int, rate_lookup: TrenerRateLookup, maps=None):
    if maps is None:
        maps = _accounting_maps(today, rate_lookup)
    paid_map, charged_map, trener_paid_map, other_map, earned_map = maps
    data = []
    current_day = today
    for _ in range(num_months):
        month_start = current_day.replace(day=1)
        data.append(_accounting_entry_from_maps(
            month_start, today, paid_map, charged_map, trener_paid_map, other_map, earned_map
        ))
        current_day = month_start - timedelta(days=1)
    data.reverse()
    return data


def accounting_alltime_series(today: date, rate_lookup: TrenerRateLookup, maps=None):
    first_dt = Trening.objects.order_by("datum").values_list("datum", flat=True).first()
    if not first_dt:
        return []
    first_date = dj_tz.localtime(first_dt).date() if dj_tz.is_aware(first_dt) else first_dt.date()
    month_start = first_date.replace(day=1)
    end_month = today.replace(day=1)

    if maps is None:
        maps = _accounting_maps(today, rate_lookup)
    paid_map, charged_map, trener_paid_map, other_map, earned_map = maps
    data = []
    while month_start <= end_month:
        data.append(_accounting_entry_from_maps(
            month_start, today, paid_map, charged_map, trener_paid_map, other_map, earned_map
        ))
        if month_start.month == 12:
            month_start = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            month_start = month_start.replace(month=month_start.month + 1, day=1)
    return data


def hraci_kredit_qs():
    return Hrac.objects.annotate(
        _kredit_calculated=Sum(
            Case(
                When(transakce__typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA], then=F("transakce__castka")),
                When(transakce__typ=Transakce.Typ.NAUCTOVANO, then=-F("transakce__castka")),
                default=Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
    ).filter(_kredit_calculated__isnull=False)


def build_trener_rows(m_from: date, m_to: date, rate_lookup: TrenerRateLookup):
    users = {
        u.id: u
        for u in User.objects.filter(
            pk__in=Trening.objects.values_list("trener_id", flat=True).distinct()
        ).order_by("last_name", "first_name", "username")
    }
    if not users:
        return [], Decimal("0.00")

    all_rows = list(
        Trening.objects.filter(trener_id__in=users.keys()).values(
            "trener_id", "datum", "delka_minut"
        )
    )
    def _training_day(dt):
        if dj_tz.is_aware(dt):
            return dj_tz.localtime(dt).date()
        return dt.date() if hasattr(dt, "date") else dt

    month_rows = [r for r in all_rows if m_from <= _training_day(r["datum"]) <= m_to]

    earned_total: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
    earned_month: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
    mins_total: dict[int, int] = defaultdict(int)
    mins_month: dict[int, int] = defaultdict(int)
    count_total: dict[int, int] = defaultdict(int)
    count_month: dict[int, int] = defaultdict(int)

    for row in all_rows:
        uid = row["trener_id"]
        mins = row["delka_minut"] or 0
        rate = rate_lookup.for_user_date(uid, row["datum"])
        earned = (Decimal(mins) / Decimal(60) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        earned_total[uid] += earned
        mins_total[uid] += mins
        count_total[uid] += 1

    for row in month_rows:
        uid = row["trener_id"]
        mins_month[uid] += row["delka_minut"] or 0
        count_month[uid] += 1
        rate = rate_lookup.for_user_date(uid, row["datum"])
        earned_month[uid] += (Decimal(row["delka_minut"] or 0) / Decimal(60) * rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    paid_map = {
        uid: Decimal(val or 0)
        for uid, val in TrenerPlatba.objects.filter(user_id__in=users.keys())
        .values("user_id")
        .annotate(s=Sum("castka"))
        .values_list("user_id", "s")
    }

    rows = []
    total_to_pay = Decimal("0.00")
    for uid, u in users.items():
        balance = (earned_total[uid] - paid_map.get(uid, Decimal("0"))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        total_to_pay += balance
        hours_month = (Decimal(mins_month[uid]) / Decimal(60)).quantize(Decimal("0.01"))
        hours_total = (Decimal(mins_total[uid]) / Decimal(60)).quantize(Decimal("0.01"))
        rows.append({
            "name": u.get_full_name() or u.username,
            "balance": f"{balance:.0f} Kč",
            "balance_value": float(balance),
            "hours_month": f"{hours_month:.1f} h",
            "hours_month_value": float(hours_month),
            "hours_total": f"{hours_total:.1f} h",
            "hours_total_value": float(hours_total),
            "trainings_month": count_month[uid],
            "trainings_total": count_total[uid],
            "earned_month": f"{earned_month[uid]:.0f} Kč",
            "url": reverse("admin:core_treneri_detail", args=[u.id]),
        })
    rows.sort(key=lambda r: r["balance_value"], reverse=True)
    return rows, total_to_pay


def activity_last_7_days(today: date):
    day_from = today - timedelta(days=6)
    hours_by_day = {
        row["day"]: row["mins"] or 0
        for row in Trening.objects.filter(datum__date__gte=day_from, datum__date__lte=today)
        .annotate(day=F("datum__date"))
        .values("day")
        .annotate(mins=Sum("delka_minut"))
    }
    charged_by_day = {
        row["day"]: Decimal(row["total"] or 0)
        for row in Transakce.objects.filter(
            typ=Transakce.Typ.NAUCTOVANO,
            trening__datum__date__gte=day_from,
            trening__datum__date__lte=today,
        )
        .annotate(day=F("trening__datum__date"))
        .values("day")
        .annotate(total=Sum("castka"))
    }
    paid_by_day = {
        row["day"]: Decimal(row["total"] or 0)
        for row in Transakce.objects.filter(
            vytvoreno__date__gte=day_from,
            vytvoreno__date__lte=today,
            typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
        )
        .annotate(day=F("vytvoreno__date"))
        .values("day")
        .annotate(total=Sum("castka"))
    }

    data = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_hours = (Decimal(hours_by_day.get(day, 0)) / Decimal(60)).quantize(Decimal("0.01"))
        data.append({
            "date": day.strftime("%d.%m"),
            "day_name": day.strftime("%a"),
            "hours": float(day_hours),
            "charged": float(charged_by_day.get(day, Decimal("0"))),
            "paid": float(paid_by_day.get(day, Decimal("0"))),
        })
    return data


def naklady_chart_monthly_series(limit_months: int = 12):
    qs = (
        OstatniNaklad.objects.annotate(month=TruncMonth("mesic"))
        .values("month")
        .annotate(total=Sum("castka"))
        .order_by("-month")[:limit_months]
    )
    month_list = list(qs)
    if not month_list:
        return []

    bounds = []
    for row in month_list:
        month_dt = row["month"]
        month_start = month_dt.date() if hasattr(month_dt, "date") else month_dt
        bounds.append((month_start, month_end_from_start(month_start)))

    global_start = min(b[0] for b in bounds)
    global_end = max(b[1] for b in bounds)
    all_items = OstatniNaklad.objects.filter(
        mesic__gte=global_start,
        mesic__lte=global_end,
    ).order_by("mesic", "kategorie").values("mesic", "kategorie", "castka", "poznamka")

    kat_labels = dict(OstatniNaklad.Kategorie.choices)
    by_date: dict[date, list] = defaultdict(list)
    for item in all_items:
        d = item["mesic"]
        by_date[d].append({
            "label": kat_labels.get(item["kategorie"], item["kategorie"]),
            "castka": float(item["castka"]),
            "poznamka": item["poznamka"] or "",
        })

    weekdays = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
    rows = []
    for row, (month_start, month_end) in zip(month_list, bounds):
        day_dates = sorted(d for d in by_date.keys() if month_start <= d <= month_end)
        days = []
        for d in day_dates:
            items = by_date[d]
            total = sum(i["castka"] for i in items)
            days.append({
                "label": d.strftime("%d.%m.%Y"),
                "weekday": weekdays[d.weekday()],
                "total": total,
                "datum_value": d.strftime("%Y-%m-%d"),
                "items": items,
            })
        rows.append({
            "label": f"{CZECH_MONTHS[month_start.month]} '{month_start.strftime('%y')}",
            "total": float(row["total"] or 0),
            "mesic_value": month_start.strftime("%Y-%m"),
            "days": days,
            "items": [item for day in days for item in day["items"]],
        })
    rows.reverse()
    return rows


def parse_naklad_datum(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        year_s, month_s, day_s = raw.split("-", 2)
        return date(int(year_s), int(month_s), int(day_s))
    except (ValueError, TypeError):
        return None
    try:
        year_s, month_s = raw.split("-", 1)
        return date(int(year_s), int(month_s), 1)
    except (ValueError, TypeError):
        return None


def naklady_form_rows(den: date):
    existing = {row.kategorie: row for row in OstatniNaklad.objects.filter(mesic=den)}
    rows = []
    for key, label in OstatniNaklad.Kategorie.choices:
        row = existing.get(key)
        rows.append({
            "key": key,
            "label": label,
            "castka": f"{row.castka:.0f}" if row else "",
            "poznamka": row.poznamka if row else "",
        })
    return rows


def naklady_day_items(den: date):
    kat_labels = dict(OstatniNaklad.Kategorie.choices)
    return [
        {
            "kategorie": item["kategorie"],
            "label": kat_labels.get(item["kategorie"], item["kategorie"]),
            "castka": item["castka"],
            "castka_fmt": f"{Decimal(item['castka']):.0f} Kč",
            "poznamka": item["poznamka"],
        }
        for item in OstatniNaklad.objects.filter(mesic=den).order_by("kategorie").values(
            "kategorie", "castka", "poznamka"
        )
    ]


def naklady_day_block(den: date):
    items = naklady_day_items(den)
    total = sum(Decimal(str(i["castka"])) for i in items)
    weekdays = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
    return {
        "datum": den,
        "datum_value": den.strftime("%Y-%m-%d"),
        "label": den.strftime("%d.%m.%Y"),
        "weekday": weekdays[den.weekday()],
        "total": total,
        "total_fmt": f"{total:.0f} Kč",
        "items": items,
    }


def naklady_history(limit: int = 60):
    dates = (
        OstatniNaklad.objects.values_list("mesic", flat=True)
        .distinct()
        .order_by("-mesic")[:limit]
    )
    return [naklady_day_block(d) for d in dates]


def build_analytika_context(section: str, request) -> dict:
    """Sestaví kontext pouze pro aktivní sekci analytiky."""
    today = dj_tz.localdate()
    m_from, m_to = month_range(today)

    trener_ids = list(
        Trening.objects.exclude(trener_id__isnull=True).values_list("trener_id", flat=True).distinct()
    )
    rate_lookup = TrenerRateLookup(trener_ids)

    ctx: dict = {}

    needs_kpis = section in {"prehled", "aktivita", "finance", "hraci"}
    needs_treneri = section in {"prehled", "treneri", "ucetnictvi"}
    needs_hraci = section in {"prehled", "hraci"}
    needs_charts = section in {"aktivita", "finance"}
    needs_accounting = section == "ucetnictvi"
    needs_naklady = section == "naklady"

    tqs_current = Trening.objects.filter(datum__date__gte=m_from, datum__date__lte=m_to)
    total_min_current = tqs_current.aggregate(s=Sum("delka_minut"))["s"] or 0
    hours_current = (Decimal(total_min_current) / Decimal(60)).quantize(Decimal("0.01"))
    trainings_count_current = tqs_current.count()

    nac_current = charges_sum_between(m_from, m_to)
    charges_count_current = Transakce.objects.filter(
        typ=Transakce.Typ.NAUCTOVANO,
        trening__datum__date__gte=m_from,
        trening__datum__date__lte=m_to,
    ).count()
    pays_current = payments_sum_between(m_from, m_to)
    payments_count_current = Transakce.objects.filter(
        vytvoreno__date__gte=m_from,
        vytvoreno__date__lte=m_to,
        typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
    ).count()

    trener_rows: list = []
    total_trener_to_pay_now = Decimal("0.00")
    if needs_treneri or needs_kpis:
        trener_rows, total_trener_to_pay_now = build_trener_rows(m_from, m_to, rate_lookup)

    trener_earned_current = Decimal("0.00")
    if needs_accounting or needs_kpis:
        trener_earned_current = rate_lookup.earned_from_rows(
            tqs_current.values("trener_id", "datum", "delka_minut")
        )

    if needs_kpis:
        hraci_qs = hraci_kredit_qs()
        agregace = hraci_qs.aggregate(
            celkem=Sum("_kredit_calculated"),
            dluhy=Sum("_kredit_calculated", filter=Q(_kredit_calculated__lt=Decimal(0))),
            prebytky=Sum("_kredit_calculated", filter=Q(_kredit_calculated__gt=Decimal(0))),
        )
        total_balance = agregace.get("celkem") or Decimal(0)
        total_debt = agregace.get("dluhy") or Decimal(0)
        total_surplus = agregace.get("prebytky") or Decimal(0)

        total_all_minutes = Trening.objects.aggregate(s=Sum("delka_minut"))["s"] or 0
        total_all_hours = (Decimal(total_all_minutes) / Decimal(60)).quantize(Decimal("0.01"))
        total_all_charged = charges_sum_between(date(2000, 1, 1), today)
        total_all_paid = Decimal(
            Transakce.objects.filter(
                typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]
            ).aggregate(s=Sum("castka"))["s"]
            or 0
        )
        unpaid_amount = nac_current - pays_current

        ctx["kpis"] = {
            "hours": f"{hours_current:.2f} h",
            "nauctovano": f"{nac_current:.0f} Kč",
            "platby": f"{pays_current:.0f} Kč",
            "k_vyplaceni": f"{total_trener_to_pay_now:.0f} Kč",
            "total_debt": f"{total_debt:.0f} Kč",
            "total_surplus": f"{total_surplus:.0f} Kč",
            "total_balance": f"{total_balance:.0f} Kč",
            "unpaid": f"{unpaid_amount:.0f} Kč",
            "nauctovano_value": float(nac_current),
            "platby_value": float(pays_current),
            "unpaid_value": float(unpaid_amount),
            "trainings_count_current": trainings_count_current,
            "charges_count_current": charges_count_current,
            "payments_count_current": payments_count_current,
            "total_all_hours": f"{total_all_hours:.2f} h",
            "total_all_hours_value": float(total_all_hours),
            "total_all_charged": f"{total_all_charged:.0f} Kč",
            "total_all_charged_value": float(total_all_charged),
            "total_all_paid": f"{total_all_paid:.0f} Kč",
            "total_all_paid_value": float(total_all_paid),
            "total_trainings_count": Trening.objects.count(),
            "total_charges_count": Transakce.objects.filter(typ=Transakce.Typ.NAUCTOVANO).count(),
            "total_payments_count": Transakce.objects.filter(
                typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]
            ).count(),
        }

    if needs_hraci or section == "prehled":
        hraci_qs = hraci_kredit_qs()
        debtors = [{
            "name": h.cele_jmeno,
            "kredit": f"{(h._kredit_calculated or 0):.0f} Kč",
            "url": reverse("admin:core_hrac_change", args=[h.id]),
            "kredit_value": float(h._kredit_calculated or 0),
        } for h in hraci_qs.filter(_kredit_calculated__lt=0).order_by("_kredit_calculated")]
        ctx["debtors"] = debtors
        ctx["top_debtors"] = debtors[:5]
        ctx["top_surplus"] = [{
            "name": h.cele_jmeno,
            "kredit": f"+{(h._kredit_calculated or 0):.0f} Kč",
            "url": reverse("admin:core_hrac_change", args=[h.id]),
        } for h in hraci_qs.filter(_kredit_calculated__gt=0).order_by("-_kredit_calculated")[:5]]
        ctx["debtors_chart_data"] = {
            "labels": [d["name"] for d in debtors[:10]],
            "values": [abs(d["kredit_value"]) for d in debtors[:10]],
        }

    if needs_treneri:
        ctx["treneri"] = trener_rows
        trener_positive = [t for t in trener_rows if t["balance_value"] > 0][:10]
        ctx["trener_chart_data"] = {
            "labels": [t["name"] for t in trener_positive],
            "values": [t["balance_value"] for t in trener_positive],
        }
        trener_hours_top = sorted(trener_rows, key=lambda r: r["hours_month_value"], reverse=True)[:10]
        ctx["trener_hours_chart_data"] = {
            "labels": [t["name"] for t in trener_hours_top],
            "values": [t["hours_month_value"] for t in trener_hours_top],
        }

    if section == "aktivita":
        ctx["activity_data"] = activity_last_7_days(today)

    if needs_charts or section == "aktivita":
        chart_maps = _month_stats_maps(today)
        ctx["monthly_chart_data"] = monthly_chart_series(today, 6, chart_maps)
        ctx["yearly_chart_data"] = monthly_chart_series(today, 12, chart_maps)
        if section == "aktivita":
            ctx["alltime_chart_data"] = alltime_monthly_chart_series(today, chart_maps)

    if section == "finance":
        platby_breakdown = Transakce.objects.filter(
            vytvoreno__date__gte=m_from,
            vytvoreno__date__lte=m_to,
            typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
        ).values("typ").annotate(total=Sum("castka"))
        payment_types_data = {"labels": [], "values": []}
        for item in platby_breakdown:
            if item["typ"] == Transakce.Typ.PLATBA:
                payment_types_data["labels"].append("Platby")
                payment_types_data["values"].append(float(item["total"] or 0))
            elif item["typ"] == Transakce.Typ.VRATKA:
                payment_types_data["labels"].append("Vrátky")
                payment_types_data["values"].append(float(item["total"] or 0))
        ctx["payment_types_data"] = payment_types_data

    if needs_accounting:
        total_trener_paid_all = Decimal(
            TrenerPlatba.objects.aggregate(s=Sum("castka"))["s"] or 0
        )
        total_trener_earned_all = rate_lookup.earned_from_rows(
            Trening.objects.values("trener_id", "datum", "delka_minut")
        )
        total_other_costs = Decimal(
            OstatniNaklad.objects.aggregate(s=Sum("castka"))["s"] or 0
        )
        total_all_charged = charges_sum_between(date(2000, 1, 1), today)
        total_all_paid = Decimal(
            Transakce.objects.filter(
                typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]
            ).aggregate(s=Sum("castka"))["s"]
            or 0
        )
        total_all_minutes = Trening.objects.aggregate(s=Sum("delka_minut"))["s"] or 0
        total_all_hours = (Decimal(total_all_minutes) / Decimal(60)).quantize(Decimal("0.01"))

        trener_paid_month = Decimal(
            TrenerPlatba.objects.filter(
                vytvoreno__date__gte=m_from,
                vytvoreno__date__lte=m_to,
            ).aggregate(s=Sum("castka"))["s"]
            or 0
        )
        other_costs_month = ostatni_naklady_sum_for_month(m_from)
        cashflow_month = (pays_current - trener_paid_month - other_costs_month).quantize(Decimal("0.01"))
        gross_profit_month = (nac_current - trener_earned_current).quantize(Decimal("0.01"))
        margin_month_pct = (
            (gross_profit_month / nac_current * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            if nac_current > 0 else Decimal("0.0")
        )
        revenue_per_hour_month = (
            (nac_current / hours_current).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if hours_current > 0 else Decimal("0.00")
        )
        active_players_month = (
            Dochazka.objects.filter(
                trening__datum__date__gte=m_from,
                trening__datum__date__lte=m_to,
                prisel=True,
            ).values("hrac_id").distinct().count()
        )
        avg_revenue_per_player_month = (
            (nac_current / Decimal(active_players_month)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if active_players_month > 0 else Decimal("0.00")
        )

        gross_profit_total = (total_all_charged - total_trener_earned_all).quantize(Decimal("0.01"))
        margin_total_pct = (
            (gross_profit_total / total_all_charged * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            if total_all_charged > 0 else Decimal("0.0")
        )
        revenue_per_hour_total = (
            (total_all_charged / total_all_hours).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if total_all_hours > 0 else Decimal("0.00")
        )
        total_players_count = Hrac.objects.count()
        avg_revenue_per_player_total = (
            (total_all_charged / Decimal(total_players_count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if total_players_count > 0 else Decimal("0.00")
        )

        accounting_maps = _accounting_maps(today, rate_lookup)
        accounting_monthly_data = accounting_series(today, 6, rate_lookup, accounting_maps)
        accounting_yearly_data = accounting_series(today, 12, rate_lookup, accounting_maps)
        accounting_alltime_data = accounting_alltime_series(today, rate_lookup, accounting_maps)

        ctx["accounting"] = {
            "cashflow_month": f"{cashflow_month:.0f} Kč",
            "gross_profit_month": f"{gross_profit_month:.0f} Kč",
            "margin_month": f"{margin_month_pct:.1f} %",
            "revenue_per_hour_month": f"{revenue_per_hour_month:.0f} Kč",
            "total_trener_paid": f"{total_trener_paid_all:.0f} Kč",
            "total_trener_remaining": f"{(total_trener_earned_all - total_trener_paid_all).quantize(Decimal('0.01')):.0f} Kč",
            "net_profit_total": f"{(total_all_paid - total_trener_paid_all - total_other_costs).quantize(Decimal('0.01')):.0f} Kč",
            "net_profit_month": f"{cashflow_month:.0f} Kč",
            "other_costs_month": f"{other_costs_month:.0f} Kč",
            "other_costs_total": f"{total_other_costs:.0f} Kč",
            "avg_revenue_per_player_month": f"{avg_revenue_per_player_month:.0f} Kč",
            "gross_profit_total": f"{gross_profit_total:.0f} Kč",
            "margin_total": f"{margin_total_pct:.1f} %",
            "revenue_per_hour_total": f"{revenue_per_hour_total:.0f} Kč",
            "avg_revenue_per_player_total": f"{avg_revenue_per_player_total:.0f} Kč",
            "cashflow_month_value": float(cashflow_month),
            "gross_profit_month_value": float(gross_profit_month),
            "net_profit_month_value": float(cashflow_month),
            "other_costs_month_value": float(other_costs_month),
            "other_costs_total_value": float(total_other_costs),
        }
        ctx["accounting_monthly_data"] = accounting_monthly_data
        ctx["accounting_yearly_data"] = accounting_yearly_data
        ctx["accounting_alltime_data"] = accounting_alltime_data
        ctx["accounting_charts_data"] = {
            "m6": accounting_monthly_data,
            "y12": accounting_yearly_data,
            "all": accounting_alltime_data,
        }

    if needs_naklady:
        naklady_form_datum_raw = request.GET.get("datum") or request.GET.get("mesic") or today.strftime("%Y-%m-%d")
        naklady_form_datum = parse_naklad_datum(naklady_form_datum_raw) or today
        if naklady_form_datum > today:
            naklady_form_datum = today

        first_training = Trening.objects.order_by("datum").values_list("datum", flat=True).first()
        if first_training:
            fd = dj_tz.localtime(first_training).date() if dj_tz.is_aware(first_training) else first_training.date()
            naklady_year_from = fd.year
        else:
            naklady_year_from = today.year - 2

        naklady_chart_data = naklady_chart_monthly_series(12)
        naklady_alltime_chart_data = naklady_chart_monthly_series(120)
        days_blocks = list(reversed(naklady_history(30)))
        naklady_daily_chart_data = [
            {
                "label": b["label"],
                "weekday": b["weekday"],
                "total": float(b["total"]),
                "datum_value": b["datum_value"],
                "items": [
                    {"label": i["label"], "castka": float(i["castka"]), "poznamka": i["poznamka"] or ""}
                    for i in b["items"]
                ],
            }
            for b in days_blocks
        ]

        ctx.update({
            "naklady_form_datum": naklady_form_datum.strftime("%Y-%m-%d"),
            "naklady_form_year": naklady_form_datum.year,
            "naklady_form_month": naklady_form_datum.month,
            "naklady_form_day": naklady_form_datum.day,
            "naklady_year_choices": list(range(naklady_year_from, today.year + 2)),
            "naklady_form_rows": naklady_form_rows(naklady_form_datum),
            "naklady_history": naklady_history(),
            "naklady_chart_data": naklady_chart_data,
            "naklady_alltime_chart_data": naklady_alltime_chart_data,
            "naklady_daily_chart_data": naklady_daily_chart_data,
            "naklady_charts_data": {
                "m12": naklady_chart_data,
                "all": naklady_alltime_chart_data,
                "daily": naklady_daily_chart_data,
            },
            "naklad_kategorie": OstatniNaklad.Kategorie.choices,
        })

    return ctx
