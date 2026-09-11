"""Custom admin site views (dashboard, analytika)."""
import json
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from core.money import format_castka
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models import Sum, Case, When, F, Value, DecimalField, Q
from django.db.models.functions import TruncMonth
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone as dj_tz
from django.utils.translation import gettext as _, gettext_lazy as _lazy

from .admin_utils import month_range
from .analytika_data import build_analytika_context
from .analytika_export import (
    EXPORT_PERIODS,
    build_financial_report,
    export_filename,
    render_report_excel,
    render_report_pdf,
)
from .models import (
    Dochazka,
    Hrac,
    OstatniNaklad,
    SystemNastaveni,
    TrenerPlatba,
    Transakce,
    Trening,
    UserPreference,
    Vyuctovani,
    VyuctovaniNastaveni,
    sazba_trenera_k_datu,
)
from .forms import SystemNastaveniForm
from .js_i18n import get_analytika_js_i18n, get_js_locale, get_nastaveni_js_i18n
from .middleware import set_language_cookie
from .system_theme import (
    DEFAULT_THEME,
    THEME_VARIANTS,
    css_vars_style_block,
    presets_for_js,
    resolve_effective_theme,
    resolve_theme_colors,
    theme_options_for_template,
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
    "prehled": (_lazy("Přehled"), _lazy("Klíčové ukazatele tenisového systému za aktuální měsíc")),
    "aktivita": (_lazy("Aktivita"), _lazy("Odehrané hodiny, tréninky a denní trend")),
    "finance": (_lazy("Finance"), _lazy("Naúčtování, platby a finanční srovnání")),
    "ucetnictvi": (_lazy("Účetnictví"), _lazy("Cash flow, zisky, marže a výnosy na hodinu")),
    "hraci": (_lazy("Hráči"), _lazy("Kredity, dluhy a přeplatky hráčů")),
    "treneri": (_lazy("Trenéři"), _lazy("Náklady na trenéry – hodiny, nároky a výplaty")),
    "naklady": (_lazy("Ostatní náklady"), _lazy("Provozní náklady mimo výplaty trenérů – započítávají se do čistého zisku")),
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
        messages.error(request, _("Neplatné datum nákladů."))
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
        messages.success(
            request,
            _("Náklady za %(date)s uloženy (%(count)s kategorií).")
            % {"date": den.strftime("%d.%m.%Y"), "count": saved},
        )
    else:
        messages.info(
            request,
            _("Náklady za %(date)s vymazány – nebyla zadána žádná částka.")
            % {"date": den.strftime("%d.%m.%Y")},
        )
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
            "castka_fmt": format_castka(Decimal(item['castka'])),
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
        "total_fmt": format_castka(total),
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
    extra_ctx = {}
    if section == "prehled":
        extra_ctx["analytika_export_periods"] = EXPORT_PERIODS
        extra_ctx["analytika_export_urls"] = {
            p: {
                "pdf": reverse("admin:analytika_export", kwargs={"period": p, "fmt": "pdf"}),
                "xlsx": reverse("admin:analytika_export", kwargs={"period": p, "fmt": "xlsx"}),
            }
            for p in EXPORT_PERIODS
        }
    ctx = dict(
        admin.site.each_context(request),
        title=_("Analytika"),
        **build_analytika_context(section, request),
        **extra_ctx,
        analytika_section=section,
        analytika_section_title=section_title,
        analytika_section_subtitle=section_subtitle,
        analytika_section_urls={
            slug: reverse("admin:analytika_section", kwargs={"section": slug})
            for slug in ANALYTIKA_SECTIONS
        },
        ts_js_i18n=get_analytika_js_i18n(),
        ts_js_locale=get_js_locale(),
    )
    return TemplateResponse(request, "admin/analytika.html", ctx)


def admin_analytika_export_view(request, period: str, fmt: str):
    """Stažení finančního přehledu (PDF / Excel)."""
    if period not in EXPORT_PERIODS:
        raise Http404
    if fmt not in {"pdf", "xlsx"}:
        raise Http404

    report = build_financial_report(period)
    filename = export_filename(report, fmt)

    if fmt == "xlsx":
        content = render_report_excel(report)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        content = render_report_pdf(report)
        content_type = "application/pdf"

    from django.http import HttpResponse
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


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
            "balance": format_castka(balance),
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

    debtors_qs = SystemNastaveni.load().filter_debtors(hraci_s_kreditem).order_by("_kredit_calculated")[:8]
    debtors = [{
        "name": h.cele_jmeno,
        "kredit": format_castka((h._kredit_calculated or 0)),
        "url": reverse("admin:core_hrac_change", args=[h.id]),
    } for h in debtors_qs]

    posledni_platby = [
        {
            "when": (dj_tz.localtime(p.vytvoreno) if dj_tz.is_aware(p.vytvoreno) else p.vytvoreno).strftime("%d.%m.%Y %H:%M"),
            "hrac": p.hrac.cele_jmeno,
            "castka": format_castka(Decimal(p.castka)),
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
        title=_("Přehled"),
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


REZIM_LABELS = dict(VyuctovaniNastaveni.AutoRezim.choices)


def _build_diagnostika_context():
    """Statistiky systému pro záložku Nástroje."""
    from django.conf import settings as dj_settings

    nast = SystemNastaveni.load()
    posledni_vyuct = (
        Vyuctovani.objects.order_by("-created_at")
        .values_list("created_at", "hrac__prijmeni", "hrac__jmeno")
        .first()
    )
    posledni_vyuct_label = None
    if posledni_vyuct:
        dt = posledni_vyuct[0]
        if dj_tz.is_aware(dt):
            dt = dj_tz.localtime(dt)
        jmeno = " ".join(p for p in (posledni_vyuct[1], posledni_vyuct[2]) if p).strip()
        posledni_vyuct_label = f"{dt.strftime('%d.%m.%Y %H:%M')} – {jmeno or '—'}"

    email_host = getattr(dj_settings, "EMAIL_HOST", "") or ""
    email_configured = bool(email_host and getattr(dj_settings, "EMAIL_HOST_USER", ""))

    return {
        "hraci_pocet": Hrac.objects.count(),
        "treningy_pocet": Trening.objects.count(),
        "platby_pocet": Transakce.objects.filter(
            typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]
        ).count(),
        "email_configured": email_configured,
        "email_from": nast.effective_from_email(),
        "email_host": email_host or "—",
        "posledni_vyuctovani": posledni_vyuct_label or _("Zatím žádné"),
        "db_engine": dj_settings.DATABASES["default"]["ENGINE"].rsplit(".", 1)[-1],
    }


def admin_nastaveni_view(request):
    """Centrální stránka nastavení systému."""
    if not request.user.is_staff:
        raise Http404

    nastaveni = SystemNastaveni.load()
    vyuct_nast = VyuctovaniNastaveni.load()

    if request.method == "POST":
        action = (request.POST.get("_action") or "save").strip()

        if action == "test_email":
            test_to = (request.POST.get("test_email_to") or request.user.email or "").strip()
            if not test_to:
                messages.error(request, _("Zadejte e-mail pro testovací zprávu."))
            else:
                try:
                    from core.utils.email_archive import send_and_append_to_sent

                    subject = nastaveni.format_email_subject("Test e-mailu z nastavení")
                    body = (
                        "Toto je testovací zpráva z tenisového systému.\n\n"
                        f"{nastaveni.effective_podpis()}"
                    )
                    send_and_append_to_sent(subject=subject, body=body, to=test_to)
                    messages.success(
                        request,
                        _("Testovací e-mail odeslán na %(email)s.") % {"email": test_to},
                    )
                except Exception as exc:
                    messages.error(
                        request,
                        _("Odeslání testovacího e-mailu selhalo: %(error)s") % {"error": exc},
                    )
            return redirect("admin:nastaveni")

        form = SystemNastaveniForm(
            request.POST,
            request.FILES,
            instance=nastaveni,
            vyuct_rezim_initial=vyuct_nast.auto_rezim,
        )
        if form.is_valid():
            _apply_system_nastaveni_form(
                form, vyuct_nast, user=request.user, update_user_theme=True
            )
            nastaveni.refresh_from_db()
            messages.success(request, _("Nastavení systému uloženo."))
            response = redirect("admin:nastaveni")
            set_language_cookie(response, nastaveni.vychozi_jazyk)
            return response
        messages.error(request, _("Nastavení se nepodařilo uložit. Zkontrolujte zvýrazněná pole."))
    else:
        form = SystemNastaveniForm(
            instance=nastaveni,
            vyuct_rezim_initial=vyuct_nast.auto_rezim,
        )

    user_variant, user_dark, _colors = resolve_effective_theme(
        user=request.user, nastaveni=nastaveni
    )
    form.initial = {
        **form.initial,
        "barevna_varianta": user_variant,
        "tmavy_rezim": user_dark,
    }

    theme_options = theme_options_for_template()

    uzivatele_pocet = User.objects.filter(is_staff=True).count()
    skupiny_pocet = Group.objects.count()

    sidebar_panels = [
        {"id": "obecne", "label": _("Obecné"), "type": "form"},
        {"id": "vzhled", "label": _("Vzhled"), "type": "form"},
        {"id": "provoz", "label": _("Provoz"), "type": "form"},
        {"id": "emaily", "label": _("E-maily"), "type": "form"},
        {"id": "upozorneni", "label": _("Upozornění"), "type": "form"},
        {
            "id": "uzivatele",
            "label": _("Uživatelé"),
            "type": "links",
            "items": [
                {
                    "label": _("Uživatelé"),
                    "detail": _("%(count)s účtů · %(staff)s s přístupem")
                    % {"count": User.objects.count(), "staff": uzivatele_pocet},
                    "url": reverse("admin:auth_user_changelist"),
                },
                {
                    "label": _("Skupiny"),
                    "detail": _("%(count)s skupin oprávnění") % {"count": skupiny_pocet},
                    "url": reverse("admin:auth_group_changelist"),
                },
                {
                    "label": _("Změna hesla"),
                    "detail": request.user.get_username(),
                    "url": reverse("admin:password_change"),
                },
            ],
        },
        {
            "id": "nastroje",
            "label": _("Nástroje"),
            "type": "mixed",
        },
    ]

    provoz_links = [
        {
            "label": _("Nastavení vyúčtování"),
            "detail": REZIM_LABELS.get(vyuct_nast.auto_rezim, vyuct_nast.auto_rezim),
            "url": reverse("admin:core_vyuctovani_nastaveni"),
        },
        {
            "label": _("Ceník"),
            "detail": _("Typy, kurty a ceny – volné pojmenování"),
            "url": reverse("admin:core_cenik_changelist"),
        },
        {
            "label": _("Rodiny"),
            "detail": _("Rodinné skupiny hráčů"),
            "url": reverse("admin:core_hrac_rodina_changelist"),
        },
    ]

    vyuct_summary = {
        "rezim": REZIM_LABELS.get(vyuct_nast.auto_rezim, vyuct_nast.auto_rezim),
        "popis": vyuct_nast.popis_rezimu(),
        "email": _("Zapnuto") if vyuct_nast.auto_posilat_email else _("Vypnuto"),
        "email_variant": vyuct_nast.get_email_variant_display(),
    }

    nastroje_links = [
        {
            "label": _("Analytika"),
            "detail": _("Přehledy a exporty"),
            "url": reverse("admin:analytika"),
        },
        {
            "label": _("Rozvrh tréninků"),
            "detail": _("Týdenní kalendář"),
            "url": reverse("admin:core_trening_schedule"),
        },
    ]

    from core.data_import import is_sqlite_database
    from core.roles import can_export_data, can_import_data, can_manage_users, is_platform_admin

    show_data_export = can_export_data(request.user)
    show_data_import = can_import_data(request.user) and is_sqlite_database()
    if show_data_export:
        nastroje_links.append(
            {
                "label": _("Export dat (JSON)"),
                "detail": _("Záloha hráčů, tréninků a plateb"),
                "url": reverse("admin:nastaveni_export"),
            }
        )

    password_url = reverse("admin:password_change")
    users_url = reverse("admin:auth_user_changelist")
    groups_url = reverse("admin:auth_group_changelist")

    if not can_manage_users(request.user):
        for panel in sidebar_panels:
            if panel["id"] == "uzivatele":
                panel["items"] = [
                    item for item in panel["items"]
                    if item["url"] == password_url
                ]
    elif not is_platform_admin(request.user):
        # Club admin: uživatelé ano, skupiny oprávnění ne (platform).
        for panel in sidebar_panels:
            if panel["id"] == "uzivatele":
                panel["items"] = [
                    item for item in panel["items"]
                    if item["url"] != groups_url
                ]

    ctx = {
        **admin.site.each_context(request),
        "title": _("Nastavení"),
        "form": form,
        "theme_options": theme_options,
        "theme_presets": presets_for_js(),
        "nastaveni_config": {
            "vzhledUrl": reverse("admin:nastaveni_vzhled"),
            "saveUrl": reverse("admin:nastaveni_autosave"),
            "barevnaVarianta": user_variant or DEFAULT_THEME,
        },
        "aktualni_varianta": user_variant,
        "sidebar_panels": sidebar_panels,
        "provoz_links": provoz_links,
        "vyuct_summary": vyuct_summary,
        "nastroje_links": nastroje_links,
        "show_data_export": show_data_export,
        "show_data_import": show_data_import,
        "diagnostika": _build_diagnostika_context(),
        "test_email_default": request.user.email or "",
        "email_predmet_nahled": nastaveni.email_subject_preview(),
        "email_odesilatel_nahled": nastaveni.effective_from_email(),
        "ts_js_i18n": get_nastaveni_js_i18n(),
        "ts_js_locale": get_js_locale(),
    }
    return TemplateResponse(request, "admin/nastaveni.html", ctx)


def admin_nastaveni_import_view(request):
    """Import JSON zálohy – jen platform admin + SQLite."""
    from core.roles import can_import_data

    if not can_import_data(request.user):
        raise Http404
    if request.method != "POST":
        return redirect("admin:nastaveni")

    upload = request.FILES.get("import_file")
    if not upload:
        messages.error(request, _("Vyberte JSON soubor k importu."))
        return redirect("admin:nastaveni")

    import tempfile
    from pathlib import Path

    from core.data_import import ImportNotAllowed, import_dump_file

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            tmp_path = Path(tmp.name)
        backup = import_dump_file(tmp_path, backup=True)
        msg = _("Data naimportována.")
        if backup:
            msg += " " + _("Záloha DB: %(name)s") % {"name": backup.name}
        messages.success(request, msg)
    except ImportNotAllowed as exc:
        messages.error(request, str(exc))
    except Exception as exc:
        messages.error(request, _("Import selhal: %(error)s") % {"error": exc})
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    return redirect("admin:nastaveni")


def _apply_system_nastaveni_form(
    form,
    vyuct_nast,
    *,
    user=None,
    update_user_theme: bool = False,
) -> None:
    """Uloží systémová nastavení; vzhled se ukládá per-user, ne do singletonu."""
    current = SystemNastaveni.load()
    sys_variant = current.barevna_varianta
    sys_tmavy = current.tmavy_rezim
    user_variant = form.cleaned_data.get("barevna_varianta")
    user_tmavy = form.cleaned_data.get("tmavy_rezim")

    obj = form.save(commit=False)
    obj.barevna_varianta = sys_variant
    obj.tmavy_rezim = sys_tmavy
    obj.save()
    form.save_m2m()

    if update_user_theme and user is not None and getattr(user, "is_authenticated", False):
        pref = UserPreference.for_user(user)
        if user_variant and user_variant in THEME_VARIANTS:
            pref.barevna_varianta = user_variant
        if "tmavy_rezim" in form.cleaned_data:
            pref.tmavy_rezim = bool(user_tmavy)
        pref.save()

    rezim = form.cleaned_data.get("vyuctovani_rezim")
    if rezim and rezim != vyuct_nast.auto_rezim:
        vyuct_nast.auto_rezim = rezim
        vyuct_nast.save()
    from .admin_urls import refresh_admin_branding
    refresh_admin_branding()


def _merge_nastaveni_autosave_post(post, nastaveni: SystemNastaveni, vyuct_nast: VyuctovaniNastaveni):
    """Doplní chybějící pole pro AJAX autosave z aktuální instance."""
    merged = post.copy()
    boolean_fields = {
        "zvyraznit_zaporny_kredit",
    }
    scalar_fields = [
        "nazev_klubu",
        "slogan",
        "kontakt_email",
        "kontakt_telefon",
        "kontakt_adresa",
        "vychozi_jazyk",
        "mena",
        "email_podpis",
        "barevna_varianta",
        "vychozi_delka_minut",
        "vychozi_sezona",
        "rozvrh_od_hodina",
        "rozvrh_do_hodina",
        "vychozi_zobrazeni_rozvrhu",
        "prah_dluhu_dashboard",
        "radku_na_stranku",
    ]
    for field in scalar_fields:
        if field not in merged:
            merged[field] = getattr(nastaveni, field)
    for field in boolean_fields:
        if field not in merged:
            if getattr(nastaveni, field):
                merged[field] = "on"
    # Tmavý režim: ModelForm očekává checkbox přítomnost (systémová hodnota jen pro validaci formuláře)
    if "tmavy_rezim" not in post and nastaveni.tmavy_rezim:
        merged["tmavy_rezim"] = "on"
    elif "tmavy_rezim" not in post:
        merged.pop("tmavy_rezim", None)
    if "vyuctovani_rezim" not in merged:
        merged["vyuctovani_rezim"] = vyuct_nast.auto_rezim
    if "email_jmeno" not in merged:
        jmeno, _adresa = nastaveni.from_email_parts()
        merged["email_jmeno"] = jmeno
    if "email_adresa" not in merged:
        _jmeno, adresa = nastaveni.from_email_parts()
        merged["email_adresa"] = adresa
    if "email_oznaceni" not in merged:
        merged["email_oznaceni"] = nastaveni.subject_tag_display()
    return merged


def _nastaveni_autosave_payload(nastaveni: SystemNastaveni, *, language_changed: bool = False) -> dict:
    payload = {
        "ok": True,
        "nazev_klubu": nastaveni.nazev_klubu or "",
        "vychozi_jazyk": nastaveni.vychozi_jazyk or settings.LANGUAGE_CODE,
        "language_changed": language_changed,
        "logo_url": nastaveni.logo.url if nastaveni.logo else "",
        "favicon_url": nastaveni.favicon.url if nastaveni.favicon else "",
    }
    return payload


def admin_nastaveni_autosave_view(request):
    """Okamžité uložení nastavení (AJAX)."""
    if not request.user.is_staff:
        return JsonResponse({"ok": False, "error": "Forbidden"}, status=403)
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)

    nastaveni = SystemNastaveni.load()
    vyuct_nast = VyuctovaniNastaveni.load()
    old_lang = nastaveni.vychozi_jazyk

    post_data = _merge_nastaveni_autosave_post(request.POST, nastaveni, vyuct_nast)
    form = SystemNastaveniForm(
        post_data,
        request.FILES,
        instance=nastaveni,
        vyuct_rezim_initial=vyuct_nast.auto_rezim,
    )
    if not form.is_valid():
        errors = {field: [str(msg) for msg in msgs] for field, msgs in form.errors.items()}
        return JsonResponse({"ok": False, "errors": errors}, status=400)

    _apply_system_nastaveni_form(form, vyuct_nast)
    nastaveni.refresh_from_db()
    language_changed = nastaveni.vychozi_jazyk != old_lang
    response = JsonResponse(
        _nastaveni_autosave_payload(nastaveni, language_changed=language_changed)
    )
    set_language_cookie(response, nastaveni.vychozi_jazyk)
    return response


def admin_nastaveni_vzhled_view(request):
    """Okamžité uložení osobní palety a tmavého režimu (AJAX)."""
    if not request.user.is_staff:
        return JsonResponse({"ok": False, "error": "Forbidden"}, status=403)
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)

    nast = SystemNastaveni.load()
    pref = UserPreference.for_user(request.user)

    variant = (request.POST.get("barevna_varianta") or "").strip()
    if variant and variant in THEME_VARIANTS:
        pref.barevna_varianta = variant
    elif variant:
        return JsonResponse({"ok": False, "error": "Neplatná paleta."}, status=400)

    if "tmavy_rezim" in request.POST:
        val = request.POST.get("tmavy_rezim", "")
        pref.tmavy_rezim = val in ("1", "true", "on", "True")

    pref.save()

    variant, tmavy, colors = resolve_effective_theme(user=request.user, nastaveni=nast)
    return JsonResponse(
        {
            "ok": True,
            "barevna_varianta": variant,
            "tmavy_rezim": tmavy,
            "theme": variant,
            "palette": variant,
            "mode": "dark" if tmavy else "light",
            "colors": colors,
            "theme_style": css_vars_style_block(colors, dark=tmavy),
        }
    )


def admin_nastaveni_export_view(request):
    """Stažení JSON zálohy dat – jen platform admin."""
    from core.roles import can_export_data

    if not can_export_data(request.user):
        raise Http404

    from core.data_export import build_production_dump_json

    try:
        raw = build_production_dump_json()
    except Exception as exc:
        messages.error(request, _("Export dat se nezdařil: %(error)s") % {"error": exc})
        return redirect("admin:nastaveni")

    filename = f"tennis_export_{dj_tz.localdate():%Y%m%d}.json"
    response = HttpResponse(raw, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
