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


# ✅ OPRAVENÁ ANALYTICKÁ FUNKCE S KONZISTENTNÍMI VÝPOČTY
def admin_analytika_view(request, section="prehled"):
    """Analytická stránka s opravenou logikou výpočtů - vše na accrual základně."""
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

    today = dj_tz.localdate()
    
    czech_months = {1: 'Led', 2: 'Úno', 3: 'Bře', 4: 'Dub', 5: 'Kvě', 6: 'Čer', 
                    7: 'Čvc', 8: 'Srp', 9: 'Zář', 10: 'Říj', 11: 'Lis', 12: 'Pro'}

    m_from_current, m_to_current = month_range(today)
    
    # === AKTUÁLNÍ MĚSÍC - KPI ===
    tqs_current = Trening.objects.filter(datum__date__gte=m_from_current, datum__date__lte=m_to_current)
    total_min_current = tqs_current.aggregate(s=Sum("delka_minut"))["s"] or 0
    hours_current = (Decimal(total_min_current) / Decimal(60)).quantize(Decimal("0.01"))
    trainings_count_current = tqs_current.count()

    # === OPRAVA: Naúčtováno podle DATUM tréninku (accrual basis) ===
    nac_current = Decimal("0.00")
    charges_count_current = 0
    for tr in tqs_current:
        tr_charges = Transakce.objects.filter(
            trening=tr,
            typ=Transakce.Typ.NAUCTOVANO,
        )
        charges_count_current += tr_charges.count()
        tr_sum = tr_charges.aggregate(s=Sum("castka"))["s"] or 0
        nac_current += Decimal(tr_sum)

    pays_current = Transakce.objects.filter(
        vytvoreno__date__gte=m_from_current, vytvoreno__date__lte=m_to_current,
        typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
    ).aggregate(s=Sum("castka"))["s"] or Decimal("0")
    payments_count_current = Transakce.objects.filter(
        vytvoreno__date__gte=m_from_current, vytvoreno__date__lte=m_to_current,
        typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
    ).count()

    # === OPRAVA: trener_earned_current (accrual) místo trener_due_current ===
    trener_earned_current = Decimal("0.00")  # Přejmenováno pro jasnost
    trener_ids_current = list(tqs_current.values_list("trener_id", flat=True).distinct())
    for uid in trener_ids_current:
        if uid is None:
            continue
        try:
            u = User.objects.get(pk=uid)
        except User.DoesNotExist:
            continue
            
        for tr in tqs_current.filter(trener_id=uid):
            rate = sazba_trenera_k_datu(u, tr.datum)
            h = Decimal(tr.delka_minut) / Decimal(60)
            trener_earned_current += (h * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # === CELKOVÉ STATISTIKY ===
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

    agregace_kreditu = hraci_s_kreditem.aggregate(
        celkem=Sum('_kredit_calculated'),
        dluhy=Sum('_kredit_calculated', filter=Q(_kredit_calculated__lt=Decimal(0))),
        prebytky=Sum('_kredit_calculated', filter=Q(_kredit_calculated__gt=Decimal(0)))
    )
    
    total_balance = agregace_kreditu.get('celkem') or Decimal(0)
    total_debt = agregace_kreditu.get('dluhy') or Decimal(0)
    total_surplus = agregace_kreditu.get('prebytky') or Decimal(0)

    # === TRENÉŘI - K vyplacení nyní (earned - paid, ne balance month!) ===
    trener_rows = []
    all_trener_ids = list(Trening.objects.values_list("trener_id", flat=True).distinct())
    
    total_trener_to_pay_now = Decimal("0.00")  # Celkem k vyplacení TEĎ
    
    for uid in all_trener_ids:
        if uid is None: 
            continue
        try:
            u = User.objects.get(pk=uid)
        except User.DoesNotExist: 
            continue

        all_tr = Trening.objects.filter(trener_id=uid)
        month_tr = all_tr.filter(datum__date__gte=m_from_current, datum__date__lte=m_to_current)

        # Spočítáme CELKOVÉ earned za všechny tréninky
        due_total = Decimal("0.00")
        earned_month = Decimal("0.00")
        for tr in all_tr:
            rate = sazba_trenera_k_datu(u, tr.datum)
            h = Decimal(tr.delka_minut) / Decimal(60)
            due_total += (h * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        for tr in month_tr:
            rate = sazba_trenera_k_datu(u, tr.datum)
            h = Decimal(tr.delka_minut) / Decimal(60)
            earned_month += (h * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        month_min = month_tr.aggregate(s=Sum("delka_minut"))["s"] or 0
        total_min = all_tr.aggregate(s=Sum("delka_minut"))["s"] or 0
        hours_month = (Decimal(month_min) / Decimal(60)).quantize(Decimal("0.01"))
        hours_total = (Decimal(total_min) / Decimal(60)).quantize(Decimal("0.01"))
        
        # Celkem vyplaceno
        paid_total = Decimal(
            TrenerPlatba.objects.filter(user=u).aggregate(s=Sum("castka"))["s"] or 0
        )
        
        # K vyplacení = earned - paid (pro celé období, ne jen měsíc!)
        balance_to_pay = (due_total - paid_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        total_trener_to_pay_now += balance_to_pay
        
        trener_rows.append({
            "name": u.get_full_name() or u.username,
            "balance": f"{balance_to_pay:.0f} Kč",
            "balance_value": float(balance_to_pay),
            "hours_month": f"{hours_month:.1f} h",
            "hours_month_value": float(hours_month),
            "hours_total": f"{hours_total:.1f} h",
            "trainings_month": month_tr.count(),
            "trainings_total": all_tr.count(),
            "earned_month": f"{earned_month:.0f} Kč",
            "url": reverse("admin:core_treneri_detail", args=[u.id]),
        })
    
    trener_rows.sort(key=lambda r: r["balance_value"], reverse=True)

    # === DLUŽNÍCI ===
    debtors_qs = hraci_s_kreditem.filter(_kredit_calculated__lt=0).order_by("_kredit_calculated")
    debtors = [{
        "name": h.cele_jmeno,
        "kredit": f"{(h._kredit_calculated or 0):.0f} Kč",
        "url": reverse("admin:core_hrac_change", args=[h.id]),
        "kredit_value": float(h._kredit_calculated or 0),
    } for h in debtors_qs]

    top_debtors = debtors[:5]
    surplus_qs = hraci_s_kreditem.filter(_kredit_calculated__gt=0).order_by("-_kredit_calculated")[:5]
    top_surplus = [{
        "name": h.cele_jmeno,
        "kredit": f"+{(h._kredit_calculated or 0):.0f} Kč",
        "url": reverse("admin:core_hrac_change", args=[h.id]),
    } for h in surplus_qs]

    # === GRAFY DATA ===
    top_debtors_for_chart = debtors[:10]
    debtors_chart_data = {
        "labels": [d["name"] for d in top_debtors_for_chart],
        "values": [abs(d["kredit_value"]) for d in top_debtors_for_chart],
    }
    
    trener_rows_positive = [t for t in trener_rows if t["balance_value"] > 0][:10]
    trener_chart_data = {
        "labels": [t["name"] for t in trener_rows_positive],
        "values": [t["balance_value"] for t in trener_rows_positive],
    }

    trener_hours_top = sorted(trener_rows, key=lambda r: r["hours_month_value"], reverse=True)[:10]
    trener_hours_chart_data = {
        "labels": [t["name"] for t in trener_hours_top],
        "values": [t["hours_month_value"] for t in trener_hours_top],
    }
    
    platby_breakdown = Transakce.objects.filter(
        vytvoreno__date__gte=m_from_current, vytvoreno__date__lte=m_to_current,
        typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
    ).values('typ').annotate(total=Sum('castka'))
    
    payment_types_data = { "labels": [], "values": [] }
    for item in platby_breakdown:
        if item['typ'] == Transakce.Typ.PLATBA:
            payment_types_data["labels"].append("Platby")
            payment_types_data["values"].append(float(item['total'] or 0))
        elif item['typ'] == Transakce.Typ.VRATKA:
            payment_types_data["labels"].append("Vrátky")
            payment_types_data["values"].append(float(item['total'] or 0))
    
    # === AKTIVITA ZA 7 DNÍ ===
    activity_data = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_trainings = Trening.objects.filter(datum__date=day)
        day_hours = (Decimal(day_trainings.aggregate(s=Sum("delka_minut"))["s"] or 0) / Decimal(60)).quantize(Decimal("0.01"))
        
        # === OPRAVA: Naúčtováno podle DATUM tréninku (accrual basis) ===
        day_charged = Decimal("0.00")
        for tr in day_trainings:
            tr_charges = Transakce.objects.filter(
                trening=tr,
                typ=Transakce.Typ.NAUCTOVANO,
            ).aggregate(s=Sum("castka"))["s"] or 0
            day_charged += Decimal(tr_charges)
        
        # Platby zůstávají podle vytvoreno (cash basis)
        day_paid = Transakce.objects.filter(vytvoreno__date=day, typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).aggregate(s=Sum("castka"))["s"] or Decimal("0")
        
        activity_data.append({
            "date": day.strftime("%d.%m"),
            "day_name": day.strftime("%a"),
            "hours": float(day_hours),
            "charged": float(day_charged),
            "paid": float(day_paid),
        })
    
    unpaid_amount = nac_current - pays_current
    
    # === CELKOVÉ HODNOTY ===
    total_all_minutes = Trening.objects.aggregate(s=Sum("delka_minut"))["s"] or 0
    total_all_hours = (Decimal(total_all_minutes) / Decimal(60)).quantize(Decimal("0.01"))
    
    # === OPRAVA: Naúčtováno celkem podle DATUM tréninku (accrual basis) ===
    # Pro konzistenci s měsíčními daty používáme datum tréninku, ne vytvoreno transakce
    total_all_charged = Decimal("0.00")
    for tr in Trening.objects.all():
        tr_charges = Transakce.objects.filter(
            trening=tr,
            typ=Transakce.Typ.NAUCTOVANO,
        ).aggregate(s=Sum("castka"))["s"] or 0
        total_all_charged += Decimal(tr_charges)
    
    total_all_paid = Transakce.objects.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).aggregate(s=Sum("castka"))["s"] or Decimal("0")
    total_trainings_count = Trening.objects.count()
    total_charges_count = Transakce.objects.filter(typ=Transakce.Typ.NAUCTOVANO).count()
    total_payments_count = Transakce.objects.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).count()
    
    # === GRAFY MĚSÍČNÍHO PŘEHLEDU ===
    monthly_chart_data = _monthly_chart_series(today, czech_months, 6)
    yearly_chart_data = _monthly_chart_series(today, czech_months, 12)
    alltime_chart_data = _alltime_monthly_chart_series(today, czech_months)

    # ============================================================
    # === ÚČETNÍ UKAZATELE (OPRAVENÉ NA ACCRUAL) ===
    # ============================================================

    # 1. Celkové výplaty trenérům
    total_trener_paid_all = Decimal(
        TrenerPlatba.objects.aggregate(s=Sum("castka"))["s"] or 0
    )

    # 2. Celkové náklady earned trenérům (accrual)
    total_trener_earned_all = Decimal("0.00")
    for uid in all_trener_ids:
        if uid is None:
            continue
        try:
            u_obj = User.objects.get(pk=uid)
        except User.DoesNotExist:
            continue
        for tr in Trening.objects.filter(trener_id=uid):
            rate = sazba_trenera_k_datu(u_obj, tr.datum)
            h = Decimal(tr.delka_minut) / Decimal(60)
            total_trener_earned_all += (h * rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

    # 3. Zbývá vyplatit celkem (totéž jako total_trener_to_pay_now)
    total_trener_remaining = (
        total_trener_earned_all - total_trener_paid_all
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 4. Čistý zisk celkem = platby − výplaty trenérům − ostatní náklady (CASH BASIS)
    total_other_costs = _ostatni_naklady_total()
    net_profit_total = (
        Decimal(total_all_paid) - total_trener_paid_all - total_other_costs
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 5. Cash Flow měsíc = přijaté platby − výplaty trenérům − ostatní náklady v měsíci
    trener_paid_month = Decimal(
        TrenerPlatba.objects.filter(
            vytvoreno__date__gte=m_from_current,
            vytvoreno__date__lte=m_to_current,
        ).aggregate(s=Sum("castka"))["s"] or 0
    )
    other_costs_month = _ostatni_naklady_sum_for_month(m_from_current)
    cashflow_month = (pays_current - trener_paid_month - other_costs_month).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    net_profit_month = cashflow_month

    # 6. Hrubý zisk měsíc = naúčtováno − earned trenérů (accrual)
    gross_profit_month = (
        Decimal(nac_current) - trener_earned_current
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 7. Marže měsíc (%)
    if Decimal(nac_current) > 0:
        margin_month_pct = (
            gross_profit_month / Decimal(nac_current) * 100
        ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    else:
        margin_month_pct = Decimal("0.0")

    # 8. Výnosy na odehranou hodinu (měsíc)
    if hours_current > 0:
        revenue_per_hour_month = (
            Decimal(nac_current) / hours_current
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        revenue_per_hour_month = Decimal("0.00")

    # 9. Průměrný příjem / aktivní hráč (měsíc)
    active_players_month = (
        Dochazka.objects.filter(
            trening__datum__date__gte=m_from_current,
            trening__datum__date__lte=m_to_current,
            prisel=True,
        )
        .values("hrac_id")
        .distinct()
        .count()
    )
    if active_players_month > 0:
        avg_revenue_per_player_month = (
            Decimal(nac_current) / Decimal(active_players_month)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        avg_revenue_per_player_month = Decimal("0.00")

    # === CELKOVÉ UKAZATELE ===
    # 1. Hrubý zisk (celkem) = naúčtováno celkem − earned trenérů celkem
    gross_profit_total = (
        Decimal(total_all_charged) - total_trener_earned_all
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 2. Marže (celkem)
    if Decimal(total_all_charged) > 0:
        margin_total_pct = (
            gross_profit_total / Decimal(total_all_charged) * 100
        ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    else:
        margin_total_pct = Decimal("0.0")

    # 3. Výnosy na hodinu (celkem)
    if total_all_hours > 0:
        revenue_per_hour_total = (
            Decimal(total_all_charged) / Decimal(total_all_hours)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        revenue_per_hour_total = Decimal("0.00")

    # 4. Průměrný příjem / hráč (celkem)
    total_players_count = Hrac.objects.count()
    if total_players_count > 0:
        avg_revenue_per_player_total = (
            Decimal(total_all_charged) / Decimal(total_players_count)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        avg_revenue_per_player_total = Decimal("0.00")

    # === MĚSÍČNÍ DATA PRO ÚČETNÍ GRAFY ===
    accounting_monthly_data = _accounting_series(today, czech_months, 6)
    accounting_yearly_data = _accounting_series(today, czech_months, 12)
    accounting_alltime_data = _accounting_alltime_series(today, czech_months)
    naklady_history = _naklady_history()
    naklady_chart_data = _naklady_chart_monthly_series(12)
    naklady_alltime_chart_data = _naklady_chart_monthly_series(999)
    naklady_daily_chart_data = _naklady_chart_daily_series(30)
    naklady_form_datum_raw = request.GET.get("datum") or request.GET.get("mesic") or today.strftime("%Y-%m-%d")
    naklady_form_datum = _parse_naklad_datum(naklady_form_datum_raw) or today
    if naklady_form_datum > today:
        naklady_form_datum = today

    first_training = Trening.objects.order_by("datum").values_list("datum", flat=True).first()
    if first_training:
        fd = dj_tz.localtime(first_training).date() if dj_tz.is_aware(first_training) else first_training.date()
        naklady_year_from = fd.year
    else:
        naklady_year_from = today.year - 2
    naklady_year_choices = list(range(naklady_year_from, today.year + 2))

    # === SLOVNÍK PRO ŠABLONU ===
    accounting = {
        "cashflow_month": f"{cashflow_month:.0f} Kč",
        "gross_profit_month": f"{gross_profit_month:.0f} Kč",
        "margin_month": f"{margin_month_pct:.1f} %",
        "revenue_per_hour_month": f"{revenue_per_hour_month:.0f} Kč",
        "total_trener_paid": f"{total_trener_paid_all:.0f} Kč",
        "total_trener_remaining": f"{total_trener_remaining:.0f} Kč",
        "net_profit_total": f"{net_profit_total:.0f} Kč",
        "net_profit_month": f"{net_profit_month:.0f} Kč",
        "other_costs_month": f"{other_costs_month:.0f} Kč",
        "other_costs_total": f"{total_other_costs:.0f} Kč",
        "avg_revenue_per_player_month": f"{avg_revenue_per_player_month:.0f} Kč",
        "gross_profit_total": f"{gross_profit_total:.0f} Kč",
        "margin_total": f"{margin_total_pct:.1f} %",
        "revenue_per_hour_total": f"{revenue_per_hour_total:.0f} Kč",
        "avg_revenue_per_player_total": f"{avg_revenue_per_player_total:.0f} Kč",
        "cashflow_month_value": float(cashflow_month),
        "gross_profit_month_value": float(gross_profit_month),
        "net_profit_month_value": float(net_profit_month),
        "other_costs_month_value": float(other_costs_month),
        "other_costs_total_value": float(total_other_costs),
    }

    section_title, section_subtitle = ANALYTIKA_SECTION_META[section]

    # === FINÁLNÍ KONTEXT ===
    ctx = dict(
        admin.site.each_context(request),
        title="Analytika",
        kpis={
            "hours": f"{hours_current:.2f} h",
            "nauctovano": f"{Decimal(nac_current):.0f} Kč",
            "platby": f"{Decimal(pays_current):.0f} Kč",
            "k_vyplaceni": f"{total_trener_to_pay_now:.0f} Kč",  # OPRAVENO: celkový k vyplacení
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
            "total_trainings_count": total_trainings_count,
            "total_charges_count": total_charges_count,
            "total_payments_count": total_payments_count,
        },
        treneri=trener_rows,
        debtors=debtors,
        top_debtors=top_debtors,
        top_surplus=top_surplus,
        monthly_chart_data=monthly_chart_data,
        yearly_chart_data=yearly_chart_data,
        alltime_chart_data=alltime_chart_data,
        debtors_chart_data=debtors_chart_data,
        trener_chart_data=trener_chart_data,
        trener_hours_chart_data=trener_hours_chart_data,
        payment_types_data=payment_types_data,
        activity_data=activity_data,
        accounting=accounting,
        accounting_monthly_data=accounting_monthly_data,
        accounting_yearly_data=accounting_yearly_data,
        accounting_alltime_data=accounting_alltime_data,
        accounting_charts_data={
            "m6": accounting_monthly_data,
            "y12": accounting_yearly_data,
            "all": accounting_alltime_data,
        },
        naklady_form_datum=naklady_form_datum.strftime("%Y-%m-%d"),
        naklady_form_year=naklady_form_datum.year,
        naklady_form_month=naklady_form_datum.month,
        naklady_form_day=naklady_form_datum.day,
        naklady_year_choices=naklady_year_choices,
        naklady_form_rows=_naklady_form_rows(naklady_form_datum),
        naklady_history=naklady_history,
        naklady_chart_data=naklady_chart_data,
        naklady_alltime_chart_data=naklady_alltime_chart_data,
        naklady_daily_chart_data=naklady_daily_chart_data,
        naklady_charts_data={
            "m12": naklady_chart_data,
            "all": naklady_alltime_chart_data,
            "daily": naklady_daily_chart_data,
        },
        naklad_kategorie=OstatniNaklad.Kategorie.choices,
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
