"""Optimalizované sestavení dat pro admin analytiku."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from django.contrib.auth import get_user_model
from django.db.models import Sum, Case, When, F, Value, DecimalField, Q, Count, Min, Max
from django.db.models.functions import TruncMonth
from django.urls import reverse
from django.utils import timezone as dj_tz

from .admin_utils import month_range
from .models import (
    Cenik,
    Dochazka,
    Hrac,
    OstatniNaklad,
    Pronajem,
    SystemNastaveni,
    TrenerPlatba,
    TrenerProfil,
    TrenerSazba,
    Transakce,
    Trening,
)

ANALYTIKA_ZDROJ_CHOICES = ("vse", "treningy", "pronajmy")


def parse_analytika_zdroj(request) -> str:
    raw = ""
    if request is not None:
        raw = (request.GET.get("zdroj") or "").strip().lower()
    if raw not in ANALYTIKA_ZDROJ_CHOICES:
        return "vse"
    return raw

User = get_user_model()

CZECH_MONTHS = {
    1: "Led", 2: "Úno", 3: "Bře", 4: "Dub", 5: "Kvě", 6: "Čer",
    7: "Čvc", 8: "Srp", 9: "Zář", 10: "Říj", 11: "Lis", 12: "Pro",
}


class TrenerRateLookup:
    """Sazby trenérů k datu – načtené hromadně, bez dotazu na každý trénink."""

    DEFAULT_HOURLY = Decimal("500.00")
    DEFAULT_VYPLET = Decimal("300.00")

    def __init__(self, user_ids: list[int]):
        ids = [i for i in user_ids if i]
        profiles = list(TrenerProfil.objects.filter(user_id__in=ids))
        self._profiles = {p.user_id: p.sazba_za_hodinu for p in profiles}
        self._vyplet = {
            p.user_id: getattr(p, "sazba_za_vyplet", None) or self.DEFAULT_VYPLET
            for p in profiles
        }
        self._sazby: dict[int, list] = defaultdict(list)
        for s in TrenerSazba.objects.filter(user_id__in=ids).order_by("-platnost_od"):
            self._sazby[s.user_id].append(s)
        self._cache: dict[tuple[int, date], Decimal] = {}

    def for_user_date(self, user_id: int | None, dt) -> Decimal:
        if not user_id:
            return self.DEFAULT_HOURLY
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
            rate = self._profiles.get(user_id, self.DEFAULT_HOURLY)
        self._cache[key] = rate
        return rate

    def vyplet_for_user(self, user_id: int | None) -> Decimal:
        if not user_id:
            return self.DEFAULT_VYPLET
        return Decimal(self._vyplet.get(user_id, self.DEFAULT_VYPLET))

    def earned_for(
        self,
        user_id: int | None,
        dt,
        delka_minut: int | None,
        format_kod: str | None = "",
        kurt: str | None = "",
    ) -> Decimal:
        """Odměna za jeden trénink: výplet = paušál, jinak hodiny × sazba."""
        if Cenik.je_sluzba(format_kod, kurt):
            return self.vyplet_for_user(user_id).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        mins = int(delka_minut or 0)
        if not user_id or mins <= 0:
            return Decimal("0.00")
        rate = self.for_user_date(user_id, dt)
        return (Decimal(mins) / Decimal(60) * rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def earned_from_rows(self, rows) -> Decimal:
        total = Decimal("0.00")
        for row in rows:
            if isinstance(row, dict):
                uid = row.get("trener_id")
                dt = row.get("datum")
                mins = row.get("delka_minut")
                fmt = row.get("format") or ""
                kurt = row.get("kurt") or ""
            else:
                uid = row[0]
                dt = row[1]
                mins = row[2]
                fmt = row[3] if len(row) > 3 else ""
                kurt = row[4] if len(row) > 4 else ""
            if not uid:
                continue
            total += self.earned_for(uid, dt, mins, fmt, kurt)
        return total


def month_end_from_start(month_start: date) -> date:
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1, day=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1, day=1)
    return next_month - timedelta(days=1)


def charges_sum_between(day_from: date, day_to: date) -> Decimal:
    """Naúčtování z tréninků (Transakce NAUCTOVANO)."""
    return Decimal(
        Transakce.objects.filter(
            trening__datum__date__gte=day_from,
            trening__datum__date__lte=day_to,
            typ=Transakce.Typ.NAUCTOVANO,
        ).aggregate(s=Sum("castka"))["s"]
        or 0
    )


def pronajmy_sum_between(day_from: date, day_to: date) -> Decimal:
    """Přímé příjmy z pronájmů kurtu/haly."""
    return Decimal(
        Pronajem.objects.filter(
            datum__date__gte=day_from,
            datum__date__lte=day_to,
        ).aggregate(s=Sum("cena"))["s"]
        or 0
    )


def _hours_from_mins(mins) -> Decimal:
    return (Decimal(mins or 0) / Decimal(60)).quantize(Decimal("0.01"))


def _fmt_hours(mins) -> str:
    return f"{_hours_from_mins(mins):.2f} h"


def _fmt_kc(val) -> str:
    return f"{Decimal(val or 0):.0f} Kč"


def _pronajem_agg_maps(qs):
    """Vrátí mapy agregací: sezona → (mins, cena, count), misto → …"""
    by_sezona: dict[str, dict] = defaultdict(
        lambda: {"mins": 0, "cena": Decimal("0"), "count": 0}
    )
    by_misto: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"mins": 0, "cena": Decimal("0"), "count": 0}
    )
    for row in qs.values("kurt", "kurt_misto").annotate(
        mins=Sum("delka_minut"),
        cena=Sum("cena"),
        count=Count("id"),
    ):
        kurt = row["kurt"] or ""
        misto = row["kurt_misto"] or ""
        mins = int(row["mins"] or 0)
        cena = Decimal(row["cena"] or 0)
        count = int(row["count"] or 0)
        by_sezona[kurt]["mins"] += mins
        by_sezona[kurt]["cena"] += cena
        by_sezona[kurt]["count"] += count
        by_misto[(kurt, misto)]["mins"] += mins
        by_misto[(kurt, misto)]["cena"] += cena
        by_misto[(kurt, misto)]["count"] += count
    return by_sezona, by_misto


def build_pronajem_prehled(m_from: date, m_to: date, today: date) -> dict:
    """Rozpad pronájmů pro Přehled (jen filtr Pronájmy) – Hala/Venku + konkrétní kurty."""
    sezona_labels = dict(Pronajem._meta.get_field("kurt").choices)
    misto_labels = dict(Pronajem.KurtMisto.choices)

    qs_month = Pronajem.objects.filter(datum__date__gte=m_from, datum__date__lte=m_to)
    qs_all = Pronajem.objects.filter(datum__date__lte=today)
    month_sezona, month_misto = _pronajem_agg_maps(qs_month)
    all_sezona, all_misto = _pronajem_agg_maps(qs_all)

    def sezona_rows(month_map, all_map):
        rows = []
        for code in ("HALA", "VENEK"):
            m = month_map.get(code) or {"mins": 0, "cena": Decimal("0"), "count": 0}
            a = all_map.get(code) or {"mins": 0, "cena": Decimal("0"), "count": 0}
            rows.append(
                {
                    "code": code,
                    "label": str(sezona_labels.get(code, code)),
                    "hours_month": _fmt_hours(m["mins"]),
                    "hours_month_value": float(_hours_from_mins(m["mins"])),
                    "cena_month": _fmt_kc(m["cena"]),
                    "cena_month_value": float(m["cena"]),
                    "count_month": m["count"],
                    "hours_total": _fmt_hours(a["mins"]),
                    "cena_total": _fmt_kc(a["cena"]),
                    "count_total": a["count"],
                }
            )
        return rows

    def misto_rows(month_map, all_map):
        rows = []
        seen: set[tuple[str, str]] = set()
        ordered: list[tuple[str, str]] = []
        for sezona, codes in Pronajem.KURT_MISTO_BY_SEZONA.items():
            for code in codes:
                key = (sezona, code)
                ordered.append(key)
                seen.add(key)
        for key in month_map.keys() | all_map.keys():
            if key not in seen:
                ordered.append(key)
        for sezona, misto in ordered:
            m = month_map.get((sezona, misto)) or {
                "mins": 0,
                "cena": Decimal("0"),
                "count": 0,
            }
            a = all_map.get((sezona, misto)) or {
                "mins": 0,
                "cena": Decimal("0"),
                "count": 0,
            }
            if m["count"] == 0 and a["count"] == 0:
                continue
            label = str(misto_labels.get(misto, misto or "—"))
            sezona_label = str(sezona_labels.get(sezona, sezona))
            rows.append(
                {
                    "sezona": sezona,
                    "sezona_label": sezona_label,
                    "misto": misto,
                    "label": label,
                    "hours_month": _fmt_hours(m["mins"]),
                    "hours_month_value": float(_hours_from_mins(m["mins"])),
                    "cena_month": _fmt_kc(m["cena"]),
                    "cena_month_value": float(m["cena"]),
                    "count_month": m["count"],
                    "hours_total": _fmt_hours(a["mins"]),
                    "cena_total": _fmt_kc(a["cena"]),
                    "count_total": a["count"],
                    "avg_rate_month": (
                        _fmt_kc(
                            (Decimal(m["cena"]) / _hours_from_mins(m["mins"])).quantize(
                                Decimal("1"), rounding=ROUND_HALF_UP
                            )
                        )
                        if m["mins"]
                        else "—"
                    ),
                }
            )
        return rows

    month_tot = qs_month.aggregate(mins=Sum("delka_minut"), cena=Sum("cena"), count=Count("id"))
    all_tot = qs_all.aggregate(mins=Sum("delka_minut"), cena=Sum("cena"), count=Count("id"))
    month_hours = _hours_from_mins(month_tot["mins"])
    month_cena = Decimal(month_tot["cena"] or 0)
    all_hours = _hours_from_mins(all_tot["mins"])
    all_cena = Decimal(all_tot["cena"] or 0)
    avg_rate_month = (
        (month_cena / month_hours).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if month_hours > 0
        else Decimal("0")
    )
    avg_duration_month = (
        (Decimal(month_tot["mins"] or 0) / Decimal(month_tot["count"]))
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if month_tot["count"]
        else Decimal("0")
    )

    return {
        "sezona_rows": sezona_rows(month_sezona, all_sezona),
        "misto_rows": misto_rows(month_misto, all_misto),
        "avg_rate_month": _fmt_kc(avg_rate_month),
        "avg_duration_month": f"{avg_duration_month:.0f} min",
        "count_month": int(month_tot["count"] or 0),
        "count_total": int(all_tot["count"] or 0),
        "hours_month": _fmt_hours(month_tot["mins"]),
        "cena_month": _fmt_kc(month_cena),
        "hours_total": _fmt_hours(all_tot["mins"]),
        "cena_total": _fmt_kc(all_cena),
    }


def revenue_sum_between(day_from: date, day_to: date, zdroj: str = "vse") -> Decimal:
    """Příjmy podle filtru analytiky (tréninky / pronájmy / vše)."""
    if zdroj == "pronajmy":
        return pronajmy_sum_between(day_from, day_to)
    treningy = charges_sum_between(day_from, day_to)
    if zdroj == "treningy":
        return treningy
    return treningy + pronajmy_sum_between(day_from, day_to)


def payments_sum_between(day_from: date, day_to: date) -> Decimal:
    return Decimal(
        Transakce.objects.filter(
            vytvoreno__date__gte=day_from,
            vytvoreno__date__lte=day_to,
            typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
        ).aggregate(s=Sum("castka"))["s"]
        or 0
    )


def month_stats_for_range(month_start: date, month_end: date, zdroj: str = "vse"):
    if zdroj == "pronajmy":
        month_hours = Decimal("0.00")
    else:
        month_trainings = Trening.objects.filter(
            datum__date__gte=month_start,
            datum__date__lte=month_end,
        )
        month_total_min = month_trainings.aggregate(s=Sum("delka_minut"))["s"] or 0
        month_hours = (Decimal(month_total_min) / Decimal(60)).quantize(Decimal("0.01"))
    month_charged = revenue_sum_between(month_start, month_end, zdroj)
    month_paid = (
        Decimal("0.00")
        if zdroj == "pronajmy"
        else payments_sum_between(month_start, month_end)
    )
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


def _pronajem_hours_by_month(today: date) -> dict[date, Decimal]:
    rows = (
        Pronajem.objects.annotate(month=TruncMonth("datum"))
        .values("month")
        .annotate(mins=Sum("delka_minut"))
    )
    out: dict[date, Decimal] = {}
    for row in rows:
        ms = _month_start(row["month"])
        out[ms] = (Decimal(row["mins"] or 0) / Decimal(60)).quantize(Decimal("0.01"))
    return out


def _pronajmy_by_month(today: date) -> dict[date, Decimal]:
    rows = (
        Pronajem.objects.annotate(month=TruncMonth("datum"))
        .values("month")
        .annotate(total=Sum("cena"))
    )
    out: dict[date, Decimal] = {}
    for row in rows:
        key = _month_start(row["month"])
        out[key] = Decimal(row["total"] or 0)
    return out


def _month_stats_maps(today: date, zdroj: str = "vse"):
    trening_charged = _sum_by_month(
        Transakce.objects.filter(typ=Transakce.Typ.NAUCTOVANO),
        "trening__datum",
    )
    pronajem_charged = _pronajmy_by_month(today)
    trening_hours = _hours_by_month(today)
    pronajem_hours = _pronajem_hours_by_month(today)
    school_paid = _sum_by_month(
        Transakce.objects.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]),
        "vytvoreno",
    )
    if zdroj == "pronajmy":
        charged = pronajem_charged
        hours = pronajem_hours
        # Platba na místě = tržba (bez kreditního systému školy).
        paid = dict(pronajem_charged)
        trening_charged_out: dict[date, Decimal] = {}
        trening_hours_out: dict[date, Decimal] = {}
        school_paid_out: dict[date, Decimal] = {}
    elif zdroj == "treningy":
        charged = trening_charged
        hours = trening_hours
        paid = school_paid
        trening_charged_out = trening_charged
        trening_hours_out = trening_hours
        school_paid_out = school_paid
        pronajem_charged = {}
        pronajem_hours = {}
    else:
        charged = dict(trening_charged)
        for ms, val in pronajem_charged.items():
            charged[ms] = (charged.get(ms, Decimal("0")) + val).quantize(Decimal("0.01"))
        hours = dict(trening_hours)
        for ms, val in pronajem_hours.items():
            hours[ms] = (hours.get(ms, Decimal("0")) + val).quantize(Decimal("0.01"))
        # Příjmy celkem = platby školy + tržby pronájmů (platba na místě).
        paid = dict(school_paid)
        for ms, val in pronajem_charged.items():
            paid[ms] = (paid.get(ms, Decimal("0")) + val).quantize(Decimal("0.01"))
        trening_charged_out = trening_charged
        trening_hours_out = trening_hours
        school_paid_out = school_paid
    return {
        "hours": hours,
        "charged": charged,
        "paid": paid,
        "pronajmy": pronajem_charged,
        "treningy_charged": trening_charged_out,
        "treningy_hours": trening_hours_out,
        "school_paid": school_paid_out,
        "pronajem_hours": pronajem_hours,
        "split": zdroj == "vse",
    }


def _month_stats_entry(month_start: date, maps) -> tuple[Decimal, Decimal, Decimal]:
    hours = maps["hours"].get(month_start, Decimal("0"))
    charged = maps["charged"].get(month_start, Decimal("0"))
    paid = maps["paid"].get(month_start, Decimal("0"))
    return hours, charged, paid


def _chart_point(month_start: date, maps) -> dict:
    label = f"{CZECH_MONTHS[month_start.month]} '{month_start.strftime('%y')}"
    hours, charged, paid = _month_stats_entry(month_start, maps)
    point = {
        "label": label,
        "hours": float(hours),
        "charged": float(charged),
        "paid": float(paid),
    }
    if maps.get("split"):
        t_ch = float(maps["treningy_charged"].get(month_start, Decimal("0")))
        p_ch = float(maps["pronajmy"].get(month_start, Decimal("0")))
        t_h = float(maps["treningy_hours"].get(month_start, Decimal("0")))
        p_h = float(maps["pronajem_hours"].get(month_start, Decimal("0")))
        s_paid = float(maps["school_paid"].get(month_start, Decimal("0")))
        point.update({
            "split": True,
            "treningy_charged": t_ch,
            "pronajmy": p_ch,
            "treningy_hours": t_h,
            "pronajem_hours": p_h,
            "school_paid": s_paid,
        })
    return point


def monthly_chart_series(today: date, num_months: int, maps=None):
    if maps is None:
        maps = _month_stats_maps(today)
    data = []
    current_day = today
    for _ in range(num_months):
        month_start = current_day.replace(day=1)
        data.append(_chart_point(month_start, maps))
        current_day = month_start - timedelta(days=1)
    data.reverse()
    return data


def alltime_monthly_chart_series(today: date, maps=None):
    first_dt = Trening.objects.order_by("datum").values_list("datum", flat=True).first()
    first_p = Pronajem.objects.order_by("datum").values_list("datum", flat=True).first()
    candidates = [d for d in (first_dt, first_p) if d]
    if not candidates:
        return []
    first_dt = min(candidates)
    first_date = dj_tz.localtime(first_dt).date() if dj_tz.is_aware(first_dt) else first_dt.date()
    month_start = first_date.replace(day=1)
    end_month = today.replace(day=1)
    if maps is None:
        maps = _month_stats_maps(today)
    data = []
    while month_start <= end_month:
        data.append(_chart_point(month_start, maps))
        if month_start.month == 12:
            month_start = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            month_start = month_start.replace(month=month_start.month + 1, day=1)
    return data


def revenue_by_year_series(today: date, maps=None) -> list[dict]:
    """Souhrn tržeb po letech – každý rok obsahuje měsíční rozpad pro drill."""
    if maps is None:
        maps = _month_stats_maps(today)
    first_dt = Trening.objects.order_by("datum").values_list("datum", flat=True).first()
    first_p = Pronajem.objects.order_by("datum").values_list("datum", flat=True).first()
    candidates = [d for d in (first_dt, first_p) if d]
    if not candidates:
        return []
    first_dt = min(candidates)
    first_date = dj_tz.localtime(first_dt).date() if dj_tz.is_aware(first_dt) else first_dt.date()
    month_start = first_date.replace(day=1)
    end_month = today.replace(day=1)
    by_year: dict[str, dict] = {}
    while month_start <= end_month:
        point = _chart_point(month_start, maps)
        point["year"] = month_start.year
        point["month"] = month_start.month
        ykey = str(month_start.year)
        bucket = by_year.get(ykey)
        if not bucket:
            bucket = {
                "label": ykey,
                "year": month_start.year,
                "hours": 0.0,
                "charged": 0.0,
                "paid": 0.0,
                "treningy_charged": 0.0,
                "pronajmy": 0.0,
                "treningy_hours": 0.0,
                "pronajem_hours": 0.0,
                "school_paid": 0.0,
                "split": bool(maps.get("split")),
                "months": [],
            }
            by_year[ykey] = bucket
        bucket["hours"] += point["hours"]
        bucket["charged"] += point["charged"]
        bucket["paid"] += point["paid"]
        if point.get("split"):
            bucket["treningy_charged"] += point.get("treningy_charged") or 0
            bucket["pronajmy"] += point.get("pronajmy") or 0
            bucket["treningy_hours"] += point.get("treningy_hours") or 0
            bucket["pronajem_hours"] += point.get("pronajem_hours") or 0
            bucket["school_paid"] += point.get("school_paid") or 0
        bucket["months"].append(point)
        if month_start.month == 12:
            month_start = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            month_start = month_start.replace(month=month_start.month + 1, day=1)
    # Zaokrouhlení floatů
    rows = []
    for y in sorted(by_year.keys()):
        b = by_year[y]
        for key in (
            "hours",
            "charged",
            "paid",
            "treningy_charged",
            "pronajmy",
            "treningy_hours",
            "pronajem_hours",
            "school_paid",
        ):
            b[key] = round(float(b[key]), 2)
        rows.append(b)
    return rows


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
    for row in Trening.objects.values("trener_id", "datum", "delka_minut", "format", "kurt"):
        dt = row["datum"]
        if dj_tz.is_aware(dt):
            d = dj_tz.localtime(dt).date()
        else:
            d = dt.date() if hasattr(dt, "date") else dt
        if d > today:
            continue
        if not row["trener_id"]:
            continue
        ms = d.replace(day=1)
        earned[ms] += rate_lookup.earned_for(
            row["trener_id"], dt, row["delka_minut"], row["format"], row["kurt"]
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


def _accounting_maps(today: date, rate_lookup: TrenerRateLookup, zdroj: str = "vse"):
    other_map = _sum_by_month(OstatniNaklad.objects.all(), "mesic")
    if zdroj == "pronajmy":
        charged_map = _pronajmy_by_month(today)
        # Platba na místě = tržba; bez výplat trenérů školy.
        return charged_map, charged_map, {}, other_map, {}
    paid_map = _sum_by_month(
        Transakce.objects.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]),
        "vytvoreno",
    )
    charged_map = _sum_by_month(
        Transakce.objects.filter(typ=Transakce.Typ.NAUCTOVANO),
        "trening__datum",
    )
    if zdroj == "vse":
        for ms, val in _pronajmy_by_month(today).items():
            charged_map[ms] = (charged_map.get(ms, Decimal("0")) + val).quantize(Decimal("0.01"))
            paid_map[ms] = (paid_map.get(ms, Decimal("0")) + val).quantize(Decimal("0.01"))
    trener_paid_map = _sum_by_month(TrenerPlatba.objects.all(), "vytvoreno")
    earned_map = _trener_earned_by_month(rate_lookup, today)
    return paid_map, charged_map, trener_paid_map, other_map, earned_map


def accounting_entry_for_month(
    month_start: date, today: date, rate_lookup: TrenerRateLookup, zdroj: str = "vse"
):
    paid_map, charged_map, trener_paid_map, other_map, earned_map = _accounting_maps(
        today, rate_lookup, zdroj=zdroj
    )
    return _accounting_entry_from_maps(
        month_start, today, paid_map, charged_map, trener_paid_map, other_map, earned_map
    )


def accounting_series(
    today: date, num_months: int, rate_lookup: TrenerRateLookup, maps=None, zdroj: str = "vse"
):
    if maps is None:
        maps = _accounting_maps(today, rate_lookup, zdroj=zdroj)
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


def accounting_alltime_series(
    today: date, rate_lookup: TrenerRateLookup, maps=None, zdroj: str = "vse"
):
    if zdroj == "pronajmy":
        first_dt = Pronajem.objects.order_by("datum").values_list("datum", flat=True).first()
    else:
        first_dt = Trening.objects.order_by("datum").values_list("datum", flat=True).first()
        if zdroj == "vse" and not first_dt:
            first_dt = Pronajem.objects.order_by("datum").values_list("datum", flat=True).first()
    if not first_dt:
        return []
    first_date = dj_tz.localtime(first_dt).date() if dj_tz.is_aware(first_dt) else first_dt.date()
    month_start = first_date.replace(day=1)
    end_month = today.replace(day=1)

    if maps is None:
        maps = _accounting_maps(today, rate_lookup, zdroj=zdroj)
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


_AGE_BUCKETS = (
    (0, 6, "0–6 let"),
    (7, 10, "7–10 let"),
    (11, 14, "11–14 let"),
    (15, 17, "15–17 let"),
    (18, 25, "18–25 let"),
    (26, 40, "26–40 let"),
    (41, 200, "41+ let"),
)


def _age_bucket_label(age: int | None) -> str:
    if age is None:
        return "Neuvedeno"
    for lo, hi, label in _AGE_BUCKETS:
        if lo <= age <= hi:
            return label
    return "Neuvedeno"


def _hrac_display_name(jmeno: str | None, prijmeni: str | None) -> str:
    return " ".join(p for p in ((jmeno or "").strip(), (prijmeni or "").strip()) if p) or "—"


def _hours_float(mins) -> float:
    return float(_hours_from_mins(mins or 0))


def build_hraci_aktivita_stats(
    today: date | None = None,
    m_from: date | None = None,
    m_to: date | None = None,
) -> dict:
    """Aktivita hráčů: hodiny, retence, noví vs. stávající, riziko odchodu."""
    today = today or dj_tz.localdate()
    if m_from is None or m_to is None:
        m_from, m_to = month_range(today)

    week_start = today - timedelta(days=today.weekday())
    days_28 = today - timedelta(days=27)
    days_90 = today - timedelta(days=89)
    # předchozí kalendářní měsíc
    prev_month_end = m_from - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)

    def _agg(date_from: date, date_to: date):
        return list(
            Dochazka.objects.filter(
                trening__datum__date__gte=date_from,
                trening__datum__date__lte=date_to,
            )
            .values("hrac_id", "hrac__jmeno", "hrac__prijmeni")
            .annotate(mins=Sum("trening__delka_minut"), sessions=Count("id"))
            .order_by("-mins")
        )

    def _top_rows(rows, limit=10, *, per_week_div=1.0):
        out = []
        for i, r in enumerate(rows[:limit], start=1):
            hid = r["hrac_id"]
            hours = _hours_float(r["mins"])
            per_week = hours / per_week_div if per_week_div else hours
            out.append({
                "rank": i,
                "id": hid,
                "name": _hrac_display_name(r["hrac__jmeno"], r["hrac__prijmeni"]),
                "hours": hours,
                "hours_fmt": f"{hours:.1f} h",
                "hours_week": round(per_week, 2),
                "hours_week_fmt": f"{per_week:.1f} h",
                "sessions": int(r["sessions"] or 0),
                "url": reverse("admin:core_hrac_change", args=[hid]),
            })
        return out

    week_rows = _agg(week_start, today)
    month_rows = _agg(m_from, m_to)
    d28_rows = _agg(days_28, today)

    # první a poslední trénink každého hráče
    lifespan = {
        r["hrac_id"]: r
        for r in Dochazka.objects.values("hrac_id").annotate(
            first=Min("trening__datum"),
            last=Max("trening__datum"),
            total_mins=Sum("trening__delka_minut"),
            total_sessions=Count("id"),
        )
    }

    def _as_date(dt):
        if dt is None:
            return None
        if dj_tz.is_aware(dt):
            dt = dj_tz.localtime(dt)
        return dt.date() if hasattr(dt, "date") else dt

    active_prev = {
        r["hrac_id"]
        for r in Dochazka.objects.filter(
            trening__datum__date__gte=prev_month_start,
            trening__datum__date__lte=prev_month_end,
        ).values("hrac_id").distinct()
    }
    active_curr = {r["hrac_id"] for r in month_rows}
    retained = active_prev & active_curr
    churned = active_prev - active_curr
    returned = active_curr - active_prev  # aktivní teď, ne minulý měsíc (noví + návraty)

    new_ids = set()
    for hid, info in lifespan.items():
        first = _as_date(info["first"])
        if first and first >= m_from:
            new_ids.add(hid)
    returning_ids = returned - new_ids

    retention_pct = (
        round(100.0 * len(retained) / len(active_prev), 1) if active_prev else None
    )

    # Noví (první trénink ≤ 90 dní) vs. stávající
    new_cohort: list[int] = []
    established_cohort: list[int] = []
    for hid, info in lifespan.items():
        first = _as_date(info["first"])
        if not first:
            continue
        if first >= days_90:
            new_cohort.append(hid)
        else:
            established_cohort.append(hid)

    d28_by_id = {r["hrac_id"]: r for r in d28_rows}

    def _cohort_stats(ids: list[int]):
        if not ids:
            return {
                "count": 0,
                "avg_hours_28": 0.0,
                "avg_hours_28_fmt": "—",
                "avg_sessions_28": 0.0,
                "avg_tenure_weeks": 0.0,
                "avg_tenure_weeks_fmt": "—",
                "active_28": 0,
            }
        hours_active = []
        sessions_active = []
        tenure_weeks = []
        for hid in ids:
            row = d28_by_id.get(hid)
            if row:
                hours_active.append(_hours_float(row["mins"]))
                sessions_active.append(int(row["sessions"] or 0))
            first = _as_date(lifespan[hid]["first"])
            if first:
                tenure_weeks.append(max(0, (today - first).days) / 7.0)
        active_28 = len(hours_active)
        avg_h = sum(hours_active) / active_28 if active_28 else 0.0
        avg_s = sum(sessions_active) / active_28 if active_28 else 0.0
        avg_t = sum(tenure_weeks) / len(tenure_weeks) if tenure_weeks else 0.0
        return {
            "count": len(ids),
            "avg_hours_28": round(avg_h, 2),
            "avg_hours_28_fmt": f"{avg_h:.1f} h" if active_28 else "—",
            "avg_sessions_28": round(avg_s, 1) if active_28 else 0,
            "avg_tenure_weeks": round(avg_t, 1),
            "avg_tenure_weeks_fmt": f"{avg_t:.1f} týd.",
            "active_28": active_28,
        }

    new_stats = _cohort_stats(new_cohort)
    est_stats = _cohort_stats(established_cohort)

    # Engagment: hodiny za 28 dní → přepočet na týden (÷4)
    engage_buckets = [
        ("0 h / týden", 0, 0),
        ("do 1 h / týden", 0.01, 1.0),
        ("1–2 h / týden", 1.0, 2.0),
        ("2–4 h / týden", 2.0, 4.0),
        ("4+ h / týden", 4.0, 999.0),
    ]
    # hráči s alespoň 1 tréninkem někdy
    ever_ids = set(lifespan.keys())
    # pro engagement bereme hráče aktivní v posledních 90 dnech (relevantní báze)
    recent_90_ids = {
        r["hrac_id"]
        for r in Dochazka.objects.filter(
            trening__datum__date__gte=days_90,
            trening__datum__date__lte=today,
        ).values("hrac_id").distinct()
    }
    engage_counts = [0] * len(engage_buckets)
    for hid in recent_90_ids:
        h28 = _hours_float(d28_by_id.get(hid, {}).get("mins", 0))
        h_week = h28 / 4.0
        placed = False
        for i, (_, lo, hi) in enumerate(engage_buckets):
            if i == 0:
                if h_week <= 0:
                    engage_counts[0] += 1
                    placed = True
                    break
            elif lo <= h_week < hi or (hi >= 999 and h_week >= lo):
                engage_counts[i] += 1
                placed = True
                break
        if not placed:
            engage_counts[0] += 1

    # Riziko neaktivity: dny od posledního tréninku
    inactive_30 = inactive_60 = inactive_90 = 0
    risk_pairs: list[tuple[int, int]] = []  # (gap, hrac_id)
    for hid, info in lifespan.items():
        last = _as_date(info["last"])
        if not last:
            continue
        gap = (today - last).days
        if gap < 30:
            continue
        if gap >= 90:
            inactive_90 += 1
        elif gap >= 60:
            inactive_60 += 1
        else:
            inactive_30 += 1
        risk_pairs.append((gap, hid))
    risk_pairs.sort(key=lambda x: -x[0])
    risk_ids = [hid for _, hid in risk_pairs[:12]]
    name_map = {
        h.id: h.cele_jmeno
        for h in Hrac.objects.filter(pk__in=risk_ids).only("id", "jmeno", "prijmeni")
    }
    risk_top = []
    for gap, hid in risk_pairs[:12]:
        last = _as_date(lifespan[hid]["last"])
        risk_top.append({
            "id": hid,
            "name": name_map.get(hid, f"#{hid}"),
            "days": gap,
            "days_fmt": f"{gap} dní",
            "last_fmt": last.strftime("%d.%m.%Y") if last else "—",
            "url": reverse("admin:core_hrac_change", args=[hid]),
        })

    # průměr h/týden u aktivních (28 dní)
    active_28_count = len(d28_rows)
    total_h28 = sum(_hours_float(r["mins"]) for r in d28_rows)
    avg_h_week = (total_h28 / 4.0 / active_28_count) if active_28_count else 0.0

    # frekvence tréninků v měsíci
    freq_buckets = [("1×", 0), ("2–3×", 0), ("4–6×", 0), ("7+×", 0)]
    for r in month_rows:
        s = int(r["sessions"] or 0)
        if s <= 1:
            freq_buckets[0] = (freq_buckets[0][0], freq_buckets[0][1] + 1)
        elif s <= 3:
            freq_buckets[1] = (freq_buckets[1][0], freq_buckets[1][1] + 1)
        elif s <= 6:
            freq_buckets[2] = (freq_buckets[2][0], freq_buckets[2][1] + 1)
        else:
            freq_buckets[3] = (freq_buckets[3][0], freq_buckets[3][1] + 1)

    return {
        "week_label": f"{week_start.strftime('%d.%m.')} – {today.strftime('%d.%m.')}",
        "month_label": f"{m_from.strftime('%m/%Y')}",
        "d28_label": f"{days_28.strftime('%d.%m.')} – {today.strftime('%d.%m.')}",
        "prev_month_label": f"{prev_month_start.strftime('%m/%Y')}",
        "active_week": len(week_rows),
        "active_month": len(month_rows),
        "active_28": active_28_count,
        "avg_hours_week": round(avg_h_week, 2),
        "avg_hours_week_fmt": f"{avg_h_week:.1f} h" if active_28_count else "—",
        "total_hours_28": round(total_h28, 1),
        "total_hours_28_fmt": f"{total_h28:.1f} h",
        "retention_pct": retention_pct,
        "retention_pct_fmt": f"{retention_pct:.0f} %" if retention_pct is not None else "—",
        "retention_retained": len(retained),
        "retention_prev": len(active_prev),
        "retention_churned": len(churned),
        "retention_new": len(new_ids),
        "retention_returning": len(returning_ids),
        "top_week": _top_rows(week_rows, per_week_div=1.0),
        "top_month": _top_rows(month_rows, per_week_div=4.0),
        "top_28": _top_rows(d28_rows, per_week_div=4.0),
        "new_players": new_stats,
        "established_players": est_stats,
        "engagement_chart": {
            "labels": [b[0] for b in engage_buckets],
            "values": engage_counts,
        },
        "freq_chart": {
            "labels": [b[0] for b in freq_buckets],
            "values": [b[1] for b in freq_buckets],
        },
        "inactive_30": inactive_30,
        "inactive_60": inactive_60,
        "inactive_90": inactive_90,
        "risk_top": risk_top,
        "ever_players": len(ever_ids),
        "recent_90": len(recent_90_ids),
    }


def build_hraci_profil_stats(today: date | None = None) -> dict:
    """Rozložení hráčů podle věku, pohlaví, úrovně a aktivity (pro analytiku)."""
    today = today or dj_tz.localdate()
    qs = Hrac.objects.all().only(
        "id", "rok_narozeni", "pohlavi", "uroven", "aktivni"
    )
    total = qs.count()
    aktivni = 0
    ages: list[int] = []
    age_counts: dict[str, int] = {label: 0 for _, _, label in _AGE_BUCKETS}
    age_counts["Neuvedeno"] = 0
    pohlavi_counts: dict[str, int] = {code: 0 for code, _ in Hrac.Pohlavi.choices}
    pohlavi_counts[""] = 0
    uroven_counts: dict[str, int] = {code: 0 for code, _ in Hrac.Uroven.choices}
    uroven_counts[""] = 0

    for h in qs.iterator():
        if h.aktivni:
            aktivni += 1
        age = None
        if h.rok_narozeni:
            age = today.year - int(h.rok_narozeni)
            if age >= 0:
                ages.append(age)
            else:
                age = None
        # staré hodnoty „Jiné / neuvedeno“ bereme jako neuvedeno
        pohlavi_key = h.pohlavi if h.pohlavi in pohlavi_counts else ""
        age_counts[_age_bucket_label(age)] += 1
        pohlavi_counts[pohlavi_key] += 1
        uroven_counts[h.uroven or ""] += 1

    pohlavi_labels_map = dict(Hrac.Pohlavi.choices)
    pohlavi_labels_map[""] = "Neuvedeno"
    uroven_labels_map = dict(Hrac.Uroven.choices)
    uroven_labels_map[""] = "Neuvedeno"

    def _chart(counts: dict[str, int], labels_map: dict[str, str], *, drop_empty=False):
        labels, values = [], []
        for key, cnt in counts.items():
            if drop_empty and cnt <= 0:
                continue
            labels.append(labels_map.get(key, key or "Neuvedeno"))
            values.append(cnt)
        return {"labels": labels, "values": values}

    # Věk: zachovej pořadí bucketů, neuvedeno na konec; vynech prázdné (kromě Neuvedeno pokud je jediné)
    age_labels, age_values = [], []
    for _, _, label in _AGE_BUCKETS:
        if age_counts[label] > 0:
            age_labels.append(label)
            age_values.append(age_counts[label])
    if age_counts["Neuvedeno"] > 0 or not age_labels:
        age_labels.append("Neuvedeno")
        age_values.append(age_counts["Neuvedeno"])

    avg_age = None
    if ages:
        avg_age = round(sum(ages) / len(ages), 1)

    with_dob = total - age_counts["Neuvedeno"]
    with_pohlavi = total - pohlavi_counts.get("", 0)
    with_uroven = total - uroven_counts.get("", 0)

    return {
        "total": total,
        "aktivni": aktivni,
        "neaktivni": max(0, total - aktivni),
        "avg_age": avg_age,
        "avg_age_fmt": f"{avg_age:.1f}" if avg_age is not None else "—",
        "with_dob": with_dob,
        "with_pohlavi": with_pohlavi,
        "with_uroven": with_uroven,
        "age_chart": {"labels": age_labels, "values": age_values},
        "pohlavi_chart": _chart(pohlavi_counts, pohlavi_labels_map),
        "uroven_chart": _chart(uroven_counts, uroven_labels_map),
        "aktivni_chart": {
            "labels": ["Aktivní", "Neaktivní"],
            "values": [aktivni, max(0, total - aktivni)],
        },
    }


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
            "trener_id", "datum", "delka_minut", "format", "kurt"
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
        mins = 0 if Cenik.je_sluzba(row["format"], row["kurt"]) else (row["delka_minut"] or 0)
        earned = rate_lookup.earned_for(
            uid, row["datum"], row["delka_minut"], row["format"], row["kurt"]
        )
        earned_total[uid] += earned
        mins_total[uid] += mins
        count_total[uid] += 1

    for row in month_rows:
        uid = row["trener_id"]
        mins = 0 if Cenik.je_sluzba(row["format"], row["kurt"]) else (row["delka_minut"] or 0)
        mins_month[uid] += mins
        count_month[uid] += 1
        earned_month[uid] += rate_lookup.earned_for(
            uid, row["datum"], row["delka_minut"], row["format"], row["kurt"]
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


def activity_last_7_days(today: date, zdroj: str = "vse"):
    day_from = today - timedelta(days=6)
    hours_by_day: dict = defaultdict(int)
    charged_by_day: dict = defaultdict(lambda: Decimal("0"))
    paid_by_day: dict = defaultdict(lambda: Decimal("0"))

    if zdroj in ("vse", "treningy"):
        for row in (
            Trening.objects.filter(datum__date__gte=day_from, datum__date__lte=today)
            .annotate(day=F("datum__date"))
            .values("day")
            .annotate(mins=Sum("delka_minut"))
        ):
            hours_by_day[row["day"]] += row["mins"] or 0
        for row in (
            Transakce.objects.filter(
                typ=Transakce.Typ.NAUCTOVANO,
                trening__datum__date__gte=day_from,
                trening__datum__date__lte=today,
            )
            .annotate(day=F("trening__datum__date"))
            .values("day")
            .annotate(total=Sum("castka"))
        ):
            charged_by_day[row["day"]] += Decimal(row["total"] or 0)
        for row in (
            Transakce.objects.filter(
                vytvoreno__date__gte=day_from,
                vytvoreno__date__lte=today,
                typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
            )
            .annotate(day=F("vytvoreno__date"))
            .values("day")
            .annotate(total=Sum("castka"))
        ):
            paid_by_day[row["day"]] += Decimal(row["total"] or 0)

    if zdroj in ("vse", "pronajmy"):
        for row in (
            Pronajem.objects.filter(datum__date__gte=day_from, datum__date__lte=today)
            .annotate(day=F("datum__date"))
            .values("day")
            .annotate(mins=Sum("delka_minut"), cena=Sum("cena"))
        ):
            hours_by_day[row["day"]] += row["mins"] or 0
            cena = Decimal(row["cena"] or 0)
            charged_by_day[row["day"]] += cena
            paid_by_day[row["day"]] += cena

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
    zdroj = parse_analytika_zdroj(request)

    trener_ids = list(
        Trening.objects.exclude(trener_id__isnull=True).values_list("trener_id", flat=True).distinct()
    )
    rate_lookup = TrenerRateLookup(trener_ids)

    ctx: dict = {
        "analytika_zdroj": zdroj,
        "analytika_zdroj_choices": [
            ("vse", "Vše"),
            ("treningy", "Tréninky"),
            ("pronajmy", "Pronájmy"),
        ],
    }

    needs_kpis = section in {"prehled", "aktivita", "finance", "hraci"}
    needs_treneri = section in {"prehled", "treneri", "ucetnictvi"}
    needs_hraci = section in {"prehled", "hraci"}
    needs_charts = section in {"aktivita", "finance"}
    needs_accounting = section == "ucetnictvi"
    needs_naklady = section == "naklady"

    # Trenéři jen z tréninků; hodiny berou tréninky i/nebo pronájmy podle filtru.
    include_treningy = zdroj in ("vse", "treningy")
    include_pronajmy = zdroj in ("vse", "pronajmy")

    tqs_current = Trening.objects.filter(datum__date__gte=m_from, datum__date__lte=m_to)
    hours_current = Decimal("0.00")
    trainings_count_current = 0
    if include_treningy:
        total_min_current = tqs_current.aggregate(s=Sum("delka_minut"))["s"] or 0
        hours_current += (Decimal(total_min_current) / Decimal(60)).quantize(Decimal("0.01"))
        trainings_count_current = tqs_current.count()
    if include_pronajmy:
        pronajem_min_current = (
            Pronajem.objects.filter(datum__date__gte=m_from, datum__date__lte=m_to).aggregate(
                s=Sum("delka_minut")
            )["s"]
            or 0
        )
        hours_current += (Decimal(pronajem_min_current) / Decimal(60)).quantize(Decimal("0.01"))
        if zdroj == "pronajmy":
            trainings_count_current = Pronajem.objects.filter(
                datum__date__gte=m_from, datum__date__lte=m_to
            ).count()

    trening_nac_current = charges_sum_between(m_from, m_to) if include_treningy else Decimal("0")
    pronajem_nac_current = pronajmy_sum_between(m_from, m_to) if include_pronajmy else Decimal("0")
    nac_current = trening_nac_current + pronajem_nac_current

    charges_count_current = 0
    if include_treningy:
        charges_count_current += Transakce.objects.filter(
            typ=Transakce.Typ.NAUCTOVANO,
            trening__datum__date__gte=m_from,
            trening__datum__date__lte=m_to,
        ).count()
    if include_pronajmy:
        charges_count_current += Pronajem.objects.filter(
            datum__date__gte=m_from,
            datum__date__lte=m_to,
        ).count()

    if include_treningy:
        pays_current = payments_sum_between(m_from, m_to)
        payments_count_current = Transakce.objects.filter(
            vytvoreno__date__gte=m_from,
            vytvoreno__date__lte=m_to,
            typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
        ).count()
    else:
        pays_current = Decimal("0")
        payments_count_current = 0

    pronajem_count_current = Pronajem.objects.filter(
        datum__date__gte=m_from, datum__date__lte=m_to
    ).count()

    trener_rows: list = []
    total_trener_to_pay_now = Decimal("0.00")
    if (needs_treneri or needs_kpis) and include_treningy:
        trener_rows, total_trener_to_pay_now = build_trener_rows(m_from, m_to, rate_lookup)

    trener_earned_current = Decimal("0.00")
    if (needs_accounting or needs_kpis) and include_treningy:
        trener_earned_current = rate_lookup.earned_from_rows(
            tqs_current.values("trener_id", "datum", "delka_minut", "format", "kurt")
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

        trening_min_all = (
            Trening.objects.aggregate(s=Sum("delka_minut"))["s"] or 0
        ) if include_treningy else 0
        pronajem_min_all = (
            Pronajem.objects.filter(datum__date__lte=today).aggregate(s=Sum("delka_minut"))["s"] or 0
        ) if include_pronajmy else 0
        total_all_hours = (
            Decimal(trening_min_all + pronajem_min_all) / Decimal(60)
        ).quantize(Decimal("0.01"))
        trening_hours_current = (
            Decimal(
                (tqs_current.aggregate(s=Sum("delka_minut"))["s"] or 0)
            ) / Decimal(60)
        ).quantize(Decimal("0.01")) if include_treningy else Decimal("0.00")
        pronajem_hours_current = (
            Decimal(pronajem_min_current if include_pronajmy else 0) / Decimal(60)
        ).quantize(Decimal("0.01")) if include_pronajmy else Decimal("0.00")

        total_all_trening_charged = (
            charges_sum_between(date(2000, 1, 1), today) if include_treningy else Decimal("0")
        )
        total_all_pronajem = (
            Decimal(Pronajem.objects.filter(datum__date__lte=today).aggregate(s=Sum("cena"))["s"] or 0)
            if include_pronajmy
            else Decimal("0")
        )
        school_paid_all = (
            Decimal(
                Transakce.objects.filter(
                    typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]
                ).aggregate(s=Sum("castka"))["s"]
                or 0
            )
            if include_treningy
            else Decimal("0")
        )
        # Pronájmy = platba na místě → započítat do celkových příjmů u Vše / Pronájmy.
        total_all_paid = school_paid_all + total_all_pronajem
        total_all_charged = total_all_trening_charged + total_all_pronajem

        # Nezaplaceno jen u tréninků (pronájem = přímý příjem)
        unpaid_amount = (trening_nac_current - pays_current) if include_treningy else Decimal("0")
        # Příjmy zobrazené v KPI: škola + pronájmy (u Pronájmy = jen tržby).
        platby_display = (
            pays_current + pronajem_nac_current
            if include_pronajmy
            else pays_current
        ) if include_treningy else nac_current

        ctx["kpis"] = {
            "hours": f"{hours_current:.2f} h",
            "hours_value": float(hours_current),
            "nauctovano": f"{nac_current:.0f} Kč",
            "platby": f"{platby_display:.0f} Kč",
            "k_vyplaceni": f"{total_trener_to_pay_now:.0f} Kč",
            "total_debt": f"{total_debt:.0f} Kč",
            "total_surplus": f"{total_surplus:.0f} Kč",
            "total_debt_value": float(abs(total_debt)),
            "total_surplus_value": float(total_surplus),
            "total_balance": f"{total_balance:.0f} Kč",
            "unpaid": f"{unpaid_amount:.0f} Kč",
            "nauctovano_value": float(nac_current),
            "platby_value": float(platby_display),
            "unpaid_value": float(unpaid_amount),
            "trainings_count_current": trainings_count_current,
            "charges_count_current": charges_count_current,
            "payments_count_current": payments_count_current,
            "pronajmy_current": f"{pronajem_nac_current:.0f} Kč",
            "pronajmy_current_value": float(pronajem_nac_current),
            "pronajmy_count_current": pronajem_count_current,
            "pronajem_hours_current": f"{pronajem_hours_current:.2f} h",
            "treningy_hours_current": f"{trening_hours_current:.2f} h",
            "treningy_nauctovano": f"{trening_nac_current:.0f} Kč",
            "treningy_nauctovano_value": float(trening_nac_current),
            "treningy_platby": f"{pays_current:.0f} Kč",
            "treningy_platby_value": float(pays_current),
            "total_all_hours": f"{total_all_hours:.2f} h",
            "total_all_hours_value": float(total_all_hours),
            "total_all_charged": f"{total_all_charged:.0f} Kč",
            "total_all_charged_value": float(total_all_charged),
            "total_all_paid": f"{total_all_paid:.0f} Kč",
            "total_all_paid_value": float(total_all_paid),
            "total_all_pronajmy": f"{total_all_pronajem:.0f} Kč",
            "total_all_pronajmy_value": float(total_all_pronajem),
            "total_all_treningy_charged": f"{total_all_trening_charged:.0f} Kč",
            "total_school_paid": f"{school_paid_all:.0f} Kč",
            "total_pronajmy_count": Pronajem.objects.count() if include_pronajmy else 0,
            "total_trainings_count": Trening.objects.count() if include_treningy else 0,
            "total_charges_count": (
                Transakce.objects.filter(typ=Transakce.Typ.NAUCTOVANO).count()
                if include_treningy
                else 0
            ) + (Pronajem.objects.count() if include_pronajmy else 0),
            "total_payments_count": Transakce.objects.filter(
                typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]
            ).count() if include_treningy else 0,
        }

    if zdroj == "pronajmy" and section == "prehled":
        ctx["pronajem_prehled"] = build_pronajem_prehled(m_from, m_to, today)

    if zdroj != "pronajmy" and (needs_hraci or section == "prehled"):
        hraci_qs = hraci_kredit_qs()
        debtors = [{
            "name": h.cele_jmeno,
            "kredit": f"{(h._kredit_calculated or 0):.0f} Kč",
            "url": reverse("admin:core_hrac_change", args=[h.id]),
            "kredit_value": float(h._kredit_calculated or 0),
        } for h in SystemNastaveni.load().filter_debtors(hraci_qs).order_by("_kredit_calculated")]
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
        if section == "hraci":
            ctx["hraci_profil"] = build_hraci_profil_stats(today)
            ctx["hraci_aktivita"] = build_hraci_aktivita_stats(today, m_from, m_to)
    elif zdroj == "pronajmy":
        ctx["debtors"] = []
        ctx["top_debtors"] = []
        ctx["top_surplus"] = []
        ctx["debtors_chart_data"] = {"labels": [], "values": []}
        if section == "hraci":
            ctx["hraci_profil"] = build_hraci_profil_stats(today)
            ctx["hraci_aktivita"] = build_hraci_aktivita_stats(today, m_from, m_to)

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
        ctx["activity_data"] = activity_last_7_days(today, zdroj=zdroj)

    if needs_charts or section == "aktivita":
        chart_maps = _month_stats_maps(today, zdroj=zdroj)
        ctx["monthly_chart_data"] = monthly_chart_series(today, 6, chart_maps)
        ctx["yearly_chart_data"] = monthly_chart_series(today, 12, chart_maps)
        if section in ("aktivita", "finance"):
            ctx["alltime_chart_data"] = alltime_monthly_chart_series(today, chart_maps)
            ctx["revenue_by_year_data"] = revenue_by_year_series(today, chart_maps)

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
        ) if include_treningy else Decimal("0")
        total_trener_earned_all = (
            rate_lookup.earned_from_rows(
                Trening.objects.values("trener_id", "datum", "delka_minut", "format", "kurt")
            )
            if include_treningy
            else Decimal("0")
        )
        total_other_costs = Decimal(
            OstatniNaklad.objects.aggregate(s=Sum("castka"))["s"] or 0
        )
        total_all_charged = revenue_sum_between(date(2000, 1, 1), today, zdroj)
        total_all_paid = (
            Decimal(
                Transakce.objects.filter(
                    typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]
                ).aggregate(s=Sum("castka"))["s"]
                or 0
            )
            if include_treningy
            else Decimal("0")
        )
        # Pronájmy = přímý příjem → započítat do cashflow měsíce
        cash_in_month = pays_current + (pronajem_nac_current if include_pronajmy else Decimal("0"))
        total_all_minutes = 0
        if include_treningy:
            total_all_minutes += Trening.objects.aggregate(s=Sum("delka_minut"))["s"] or 0
        if include_pronajmy:
            total_all_minutes += (
                Pronajem.objects.filter(datum__date__lte=today).aggregate(s=Sum("delka_minut"))["s"]
                or 0
            )
        total_all_hours = (Decimal(total_all_minutes) / Decimal(60)).quantize(Decimal("0.01"))

        trener_paid_month = Decimal(
            TrenerPlatba.objects.filter(
                vytvoreno__date__gte=m_from,
                vytvoreno__date__lte=m_to,
            ).aggregate(s=Sum("castka"))["s"]
            or 0
        ) if include_treningy else Decimal("0")
        other_costs_month = ostatni_naklady_sum_for_month(m_from)
        cashflow_month = (cash_in_month - trener_paid_month - other_costs_month).quantize(Decimal("0.01"))
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

        accounting_maps = _accounting_maps(today, rate_lookup, zdroj=zdroj)
        accounting_monthly_data = accounting_series(
            today, 6, rate_lookup, accounting_maps, zdroj=zdroj
        )
        accounting_yearly_data = accounting_series(
            today, 12, rate_lookup, accounting_maps, zdroj=zdroj
        )
        accounting_alltime_data = accounting_alltime_series(
            today, rate_lookup, accounting_maps, zdroj=zdroj
        )

        all_pronajem_cash = (
            Decimal(Pronajem.objects.filter(datum__date__lte=today).aggregate(s=Sum("cena"))["s"] or 0)
            if include_pronajmy
            else Decimal("0")
        )
        net_profit_total = (
            total_all_paid + all_pronajem_cash - total_trener_paid_all - total_other_costs
        ).quantize(Decimal("0.01"))

        ctx["accounting"] = {
            "cashflow_month": f"{cashflow_month:.0f} Kč",
            "gross_profit_month": f"{gross_profit_month:.0f} Kč",
            "margin_month": f"{margin_month_pct:.1f} %",
            "revenue_per_hour_month": f"{revenue_per_hour_month:.0f} Kč",
            "total_trener_paid": f"{total_trener_paid_all:.0f} Kč",
            "total_trener_remaining": f"{(total_trener_earned_all - total_trener_paid_all).quantize(Decimal('0.01')):.0f} Kč",
            "net_profit_total": f"{net_profit_total:.0f} Kč",
            "net_profit_month": f"{cashflow_month:.0f} Kč",
            "other_costs_month": f"{other_costs_month:.0f} Kč",
            "other_costs_total": f"{total_other_costs:.0f} Kč",
            "avg_revenue_per_player_month": f"{avg_revenue_per_player_month:.0f} Kč",
            "gross_profit_total": f"{gross_profit_total:.0f} Kč",
            "margin_total": f"{margin_total_pct:.1f} %",
            "revenue_per_hour_total": f"{revenue_per_hour_total:.0f} Kč",
            "avg_revenue_per_player_total": f"{avg_revenue_per_player_total:.0f} Kč",
            "pronajmy_month": f"{pronajem_nac_current:.0f} Kč",
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
