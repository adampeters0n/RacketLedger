"""Custom admin site views (dashboard, analytika)."""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import date, datetime, time, timedelta

from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.db.models import Sum, Case, When, F, Value, DecimalField, Q
from django.db.models.functions import TruncMonth
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone as dj_tz

from .admin_utils import month_range
from .analytika_data import build_analytika_context
from .models import (
    Dochazka,
    Hrac,
    OstatniNaklad,
    TrenerPlatba,
    Transakce,
    Trening,
    sazba_trenera_k_datu,
)

User = get_user_model()

ANALYTIKA_SECTIONS = (
    "prehled",
    "aktivita",
    "finance",
    "ucetnictvi",
    "hraci",
    "treneri",
    "naklady",
)

ANALYTIKA_SECTION_META = {
    "prehled": ("Přehled", "Klíčové ukazatele tenisového systému za aktuální měsíc"),
    "aktivita": ("Aktivita", "Odehrané hodiny, tréninky a denní trend"),
    "finance": ("Finance", "Naúčtování, platby a finanční srovnání"),
    "ucetnictvi": ("Účetnictví", "Cash flow, zisky, marže a výnosy na hodinu"),
    "hraci": ("Hráči", "Kredity, dluhy a přeplatky hráčů"),
    "treneri": ("Trenéři", "Náklady na trenéry – hodiny, nároky a výplaty"),
    "naklady": ("Ostatní náklady", "Provozní náklady mimo výplaty trenérů – započítávají se do čistého zisku"),
}


def admin_analytika_index_view(request):
    """Přesměrování /admin/analytika/ → /admin/analytika/prehled/."""
    return redirect("admin:analytika_section", section="prehled")


def _month_stats_for_range(month_start, month_end):
    """Statistiky za jeden kalendářní měsíc (hodiny accrual, platby cash)."""
    month_trainings = Trening.objects.filter(
        datum__date__gte=month_start, datum__date__lte=month_end,
    )
    month_total_min = month_trainings.aggregate(s=Sum("delka_minut"))["s"] or 0
    month_hours = (Decimal(month_total_min) / Decimal(60)).quantize(Decimal("0.01"))

    month_charged = Decimal("0.00")
    for tr in month_trainings:
        tr_charges = Transakce.objects.filter(
            trening=tr,
            typ=Transakce.Typ.NAUCTOVANO,
        ).aggregate(s=Sum("castka"))["s"] or 0
        month_charged += Decimal(tr_charges)

    month_paid = Transakce.objects.filter(
        vytvoreno__date__gte=month_start,
        vytvoreno__date__lte=month_end,
        typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
    ).aggregate(s=Sum("castka"))["s"] or Decimal("0")

    return month_hours, month_charged, month_paid


def _month_end_from_start(month_start):
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1, day=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1, day=1)
    return next_month_start - timedelta(days=1)


def _monthly_chart_series(today, czech_months, num_months):
    """Posledních N měsíců (od nejstaršího po nejnovější)."""
    data = []
    current_day = today
    for _ in range(num_months):
        month_start = current_day.replace(day=1)
        month_end = _month_end_from_start(month_start)
        label = f"{czech_months[month_start.month]} '{month_start.strftime('%y')}"
        hours, charged, paid = _month_stats_for_range(month_start, month_end)
        data.append({
            "label": label,
            "hours": float(hours),
            "charged": float(charged),
            "paid": float(paid),
        })
        current_day = month_start - timedelta(days=1)
    data.reverse()
    return data


def _alltime_monthly_chart_series(today, czech_months):
    """Všechny měsíce od prvního tréninku po aktuální měsíc."""
    first_dt = Trening.objects.order_by("datum").values_list("datum", flat=True).first()
    if not first_dt:
        return []
    first_date = dj_tz.localtime(first_dt).date() if dj_tz.is_aware(first_dt) else first_dt.date()
    month_start = first_date.replace(day=1)
    end_month = today.replace(day=1)

    data = []
    while month_start <= end_month:
        month_end = _month_end_from_start(month_start)
        if month_end > today:
            month_end = today
        label = f"{czech_months[month_start.month]} '{month_start.strftime('%y')}"
        hours, charged, paid = _month_stats_for_range(month_start, month_end)
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


def _ostatni_naklady_sum_for_month(month_start: date) -> Decimal:
    month_end = _month_end_from_start(month_start)
    return Decimal(
        OstatniNaklad.objects.filter(
            mesic__gte=month_start,
            mesic__lte=month_end,
        ).aggregate(s=Sum("castka"))["s"] or 0
    )


def _ostatni_naklady_total() -> Decimal:
    return Decimal(
        OstatniNaklad.objects.aggregate(s=Sum("castka"))["s"] or 0
    )


def _parse_naklad_castka(raw: str) -> Decimal | None:
    raw = (raw or "").strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if not raw:
        return None
    try:
        val = Decimal(raw)
    except InvalidOperation:
        return None
    if val < 0:
        val = Decimal("0")
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _parse_naklad_datum(raw: str) -> date | None:
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


def _save_ostatni_naklady(request) -> bool:
    den = _parse_naklad_datum(request.POST.get("datum") or request.POST.get("mesic", ""))
    if not den:
        messages.error(request, "Neplatné datum nákladů.")
        return False

    saved = 0
    for key, _label in OstatniNaklad.Kategorie.choices:
        castka = _parse_naklad_castka(request.POST.get(f"naklad_{key}", ""))
        poznamka = (request.POST.get(f"poznamka_{key}") or "").strip()[:240]
        if castka is None:
            OstatniNaklad.objects.filter(mesic=den, kategorie=key).delete()
            continue
        if castka == 0:
            OstatniNaklad.objects.filter(mesic=den, kategorie=key).delete()
            continue
        OstatniNaklad.objects.update_or_create(
            mesic=den,
            kategorie=key,
            defaults={"castka": castka, "poznamka": poznamka},
        )
        saved += 1

    if saved:
        messages.success(request, f"Náklady za {den:%d.%m.%Y} uloženy ({saved} kategorií).")
    else:
        messages.info(request, f"Náklady za {den:%d.%m.%Y} vymazány – nebyla zadána žádná částka.")
    return True


def _naklady_form_rows(den: date):
    existing = {
        row.kategorie: row
        for row in OstatniNaklad.objects.filter(mesic=den)
    }
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


def _naklady_day_items(den: date):
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


def _naklady_day_block(den: date):
    items = _naklady_day_items(den)
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


def _naklady_history(limit: int = 60):
    dates = (
        OstatniNaklad.objects.values_list("mesic", flat=True)
        .distinct()
        .order_by("-mesic")[:limit]
    )
    return [_naklady_day_block(d) for d in dates]


def _serialize_naklady_day(block):
    return {
        "label": block["label"],
        "weekday": block["weekday"],
        "total": float(block["total"]),
        "datum_value": block["datum_value"],
        "items": [
            {
                "label": item["label"],
                "castka": float(item["castka"]),
                "poznamka": item["poznamka"] or "",
            }
            for item in block["items"]
        ],
    }


def _naklady_chart_daily_series(limit: int = 30):
    blocks = list(reversed(_naklady_history(limit)))
    return [_serialize_naklady_day(b) for b in blocks]


def _naklady_chart_monthly_series(limit_months: int = 12):
    czech_months = {
        1: "Led", 2: "Úno", 3: "Bře", 4: "Dub", 5: "Kvě", 6: "Čer",
        7: "Čvc", 8: "Srp", 9: "Zář", 10: "Říj", 11: "Lis", 12: "Pro",
    }
    qs = (
        OstatniNaklad.objects.annotate(month=TruncMonth("mesic"))
        .values("month")
        .annotate(total=Sum("castka"))
        .order_by("-month")[:limit_months]
    )
    rows = []
    for row in qs:
        month_dt = row["month"]
        if hasattr(month_dt, "date"):
            month_start = month_dt.date()
        else:
            month_start = month_dt
        month_end = _month_end_from_start(month_start)
        day_dates = (
            OstatniNaklad.objects.filter(mesic__gte=month_start, mesic__lte=month_end)
            .values_list("mesic", flat=True)
            .distinct()
            .order_by("mesic")
        )
        days = [_serialize_naklady_day(_naklady_day_block(d)) for d in day_dates]
        rows.append({
            "label": f"{czech_months[month_start.month]} '{month_start.strftime('%y')}",
            "total": float(row["total"] or 0),
            "mesic_value": month_start.strftime("%Y-%m"),
            "days": days,
            "items": [
                item
                for day in days
                for item in day["items"]
            ],
        })
    rows.reverse()
    return rows


def _accounting_entry_for_month(month_start, today, czech_months):
    """Účetní ukazatele za jeden kalendářní měsíc."""
    month_end = _month_end_from_start(month_start)
    if month_end > today:
        month_end = today

    label = f"{czech_months[month_start.month]} '{month_start.strftime('%y')}"

    m_paid = Decimal(
        Transakce.objects.filter(
            vytvoreno__date__gte=month_start,
            vytvoreno__date__lte=month_end,
            typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
        ).aggregate(s=Sum("castka"))["s"] or 0
    )

    m_charged = Decimal("0.00")
    m_tqs = Trening.objects.filter(
        datum__date__gte=month_start,
        datum__date__lte=month_end,
    )
    for tr in m_tqs:
        tr_charges = Transakce.objects.filter(
            trening=tr,
            typ=Transakce.Typ.NAUCTOVANO,
        ).aggregate(s=Sum("castka"))["s"] or 0
        m_charged += Decimal(tr_charges)

    m_trener_paid = Decimal(
        TrenerPlatba.objects.filter(
            vytvoreno__date__gte=month_start,
            vytvoreno__date__lte=month_end,
        ).aggregate(s=Sum("castka"))["s"] or 0
    )

    m_trener_earned = Decimal("0.00")
    for uid in m_tqs.values_list("trener_id", flat=True).distinct():
        if uid is None:
            continue
        try:
            u_obj = User.objects.get(pk=uid)
        except User.DoesNotExist:
            continue
        for tr in m_tqs.filter(trener_id=uid):
            rate = sazba_trenera_k_datu(u_obj, tr.datum)
            h = Decimal(tr.delka_minut) / Decimal(60)
            m_trener_earned += (h * rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

    m_other = _ostatni_naklady_sum_for_month(month_start)
    m_cashflow = float((m_paid - m_trener_paid - m_other).quantize(Decimal("0.01")))
    m_gross = float((m_charged - m_trener_earned).quantize(Decimal("0.01")))
    m_net = float((m_paid - m_trener_paid - m_other).quantize(Decimal("0.01")))

    return {
        "label": label,
        "cashflow": m_cashflow,
        "gross_profit": m_gross,
        "net_profit": m_net,
        "paid": float(m_paid),
        "charged": float(m_charged),
        "trener_paid": float(m_trener_paid),
        "trener_earned": float(m_trener_earned),
        "other_costs": float(m_other),
    }


def _accounting_series(today, czech_months, num_months):
    """Účetní data za posledních N měsíců (od nejstaršího po nejnovější)."""
    data = []
    current_day = today
    for _ in range(num_months):
        month_start = current_day.replace(day=1)
        data.append(_accounting_entry_for_month(month_start, today, czech_months))
        current_day = month_start - timedelta(days=1)
    data.reverse()
    return data


def _accounting_alltime_series(today, czech_months):
    """Účetní data za všechny měsíce od prvního tréninku."""
    first_dt = Trening.objects.order_by("datum").values_list("datum", flat=True).first()
    if not first_dt:
        return []
    first_date = dj_tz.localtime(first_dt).date() if dj_tz.is_aware(first_dt) else first_dt.date()
    month_start = first_date.replace(day=1)
    end_month = today.replace(day=1)

    data = []
    while month_start <= end_month:
        data.append(_accounting_entry_for_month(month_start, today, czech_months))
        if month_start.month == 12:
            month_start = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            month_start = month_start.replace(month=month_start.month + 1, day=1)
    return data


def admin_analytika_view(request, section="prehled"):
    """Analytická stránka – data se načítají jen pro aktivní sekci."""
    if section not in ANALYTIKA_SECTIONS:
        raise Http404

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_naklady":
            _save_ostatni_naklady(request)
            datum_q = (request.POST.get("datum") or "").strip()
            url = reverse("admin:analytika_section", kwargs={"section": "naklady"})
            if datum_q:
                url = f"{url}?datum={datum_q}"
            return redirect(url)

    section_title, section_subtitle = ANALYTIKA_SECTION_META[section]
    ctx = dict(
        admin.site.each_context(request),
        title="Analytika",
        **build_analytika_context(section, request),
        analytika_section=section,
        analytika_section_title=section_title,
        analytika_section_subtitle=section_subtitle,
        analytika_section_urls={
            slug: reverse("admin:analytika_section", kwargs={"section": slug})
            for slug in ANALYTIKA_SECTIONS
        },
    )
    return TemplateResponse(request, "admin/analytika.html", ctx)



def admin_dashboard_view(request):
    """Hlavní dashboard."""
    today = dj_tz.localdate()
    m_from, m_to = month_range(today)
    tqs = Trening.objects.filter(datum__date__gte=m_from, datum__date__lte=m_to)

    trener_rows = []
    trener_ids = list(tqs.values_list("trener_id", flat=True).distinct())
    
    for uid in trener_ids:
        u = User.objects.get(pk=uid)
        
        # Earned za všechny tréninky
        due = Decimal("0.00")
        for tr in Trening.objects.filter(trener_id=uid):
            rate = sazba_trenera_k_datu(u, tr.datum)
            h = Decimal(tr.delka_minut) / Decimal(60)
            due += (h * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Celkem vyplaceno
        paid = Decimal(
            TrenerPlatba.objects.filter(user=u).aggregate(s=Sum("castka"))["s"] or 0
        )
        
        balance = (due - paid).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        trener_rows.append({
            "name": u.get_full_name() or u.username,
            "balance": f"{balance:.0f} Kč",
            "url": reverse("admin:core_treneri_detail", args=[u.id]),
        })
    
    trener_rows.sort(key=lambda r: Decimal(r["balance"].split()[0]), reverse=True)
    trener_rows = trener_rows[:5]

    hraci_s_kreditem = Hrac.objects.annotate(
        _kredit_calculated=Sum(
            Case(
                When(transakce__typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA], then=F("transakce__castka")),
                When(transakce__typ=Transakce.Typ.NAUCTOVANO, then=-F("transakce__castka")),
                default=Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
    ).filter(_kredit_calculated__isnull=False)

    debtors_qs = hraci_s_kreditem.filter(_kredit_calculated__lt=0).order_by("_kredit_calculated")[:8]
    debtors = [{
        "name": h.cele_jmeno,
        "kredit": f"{(h._kredit_calculated or 0):.0f} Kč",
        "url": reverse("admin:core_hrac_change", args=[h.id]),
    } for h in debtors_qs]

    posledni_platby = [
        {
            "when": (dj_tz.localtime(p.vytvoreno) if dj_tz.is_aware(p.vytvoreno) else p.vytvoreno).strftime("%d.%m.%Y %H:%M"),
            "hrac": p.hrac.cele_jmeno,
            "castka": f"{Decimal(p.castka):.0f} Kč",
            "url": reverse("admin:core_transakce_change", args=[p.id]),
        }
        for p in Transakce.objects.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).select_related("hrac").order_by("-vytvoreno")[:5]
    ]

    posledni_treninky = []
    for t in Trening.objects.select_related("trener").order_by("-datum")[:5]:
        dt = dj_tz.localtime(t.datum) if dj_tz.is_aware(t.datum) else t.datum
        posledni_treninky.append({
            "when": dt.strftime("%d.%m.%Y %H:%M"),
            "trener": (t.trener.get_full_name() or t.trener.username),
            "format": t.get_format_display(),
            "url": reverse("admin:core_trening_change", args=[t.id]),
        })

    ctx = dict(
        admin.site.each_context(request),
        title="Přehled",
        quick={
            "add_training": reverse("admin:core_trening_add"),
            "add_payment": reverse("admin:core_transakce_add"),
            "add_player": reverse("admin:core_hrac_add"),
            "coaches": reverse("admin:core_treneri_summary"),
        },
        debtors=debtors,
        treneri=trener_rows,
        posledni_platby=posledni_platby,
        posledni_treninky=posledni_treninky,
    )
    return TemplateResponse(request, "admin/dashboard.html", ctx)
