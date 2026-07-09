"""Custom admin site views (dashboard, analytika)."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, time, timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db.models import Sum, Case, When, F, Value, DecimalField, Q
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone as dj_tz

from .admin_utils import month_range
from .models import (
    Dochazka,
    Hrac,
    TrenerPlatba,
    Transakce,
    Trening,
    sazba_trenera_k_datu,
)

User = get_user_model()


# ✅ OPRAVENÁ ANALYTICKÁ FUNKCE S KONZISTENTNÍMI VÝPOČTY
def admin_analytika_view(request):
    """Analytická stránka s opravenou logikou výpočtů - vše na accrual základně."""
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

        # Spočítáme CELKOVÉ earned za všechny tréninky
        due_total = Decimal("0.00")
        for tr in Trening.objects.filter(trener_id=uid):
            rate = sazba_trenera_k_datu(u, tr.datum)
            h = Decimal(tr.delka_minut) / Decimal(60)
            due_total += (h * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
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
            "url": reverse("admin:core_treneri_detail", args=[u.id]),
        })
    
    trener_rows.sort(key=lambda r: Decimal(r["balance"].split()[0]), reverse=True)

    # === DLUŽNÍCI ===
    debtors_qs = hraci_s_kreditem.filter(_kredit_calculated__lt=0).order_by("_kredit_calculated")
    debtors = [{
        "name": h.jmeno,
        "kredit": f"{(h._kredit_calculated or 0):.0f} Kč",
        "url": reverse("admin:core_hrac_change", args=[h.id]),
        "kredit_value": float(h._kredit_calculated or 0),
    } for h in debtors_qs]

    top_debtors = debtors[:5]
    surplus_qs = hraci_s_kreditem.filter(_kredit_calculated__gt=0).order_by("-_kredit_calculated")[:5]
    top_surplus = [{
        "name": h.jmeno,
        "kredit": f"+{(h._kredit_calculated or 0):.0f} Kč",
        "url": reverse("admin:core_hrac_change", args=[h.id]),
    } for h in surplus_qs]

    # === GRAFY DATA ===
    top_debtors_for_chart = debtors[:10]
    debtors_chart_data = {
        "labels": [d["name"] for d in top_debtors_for_chart],
        "values": [abs(d["kredit_value"]) for d in top_debtors_for_chart],
    }
    
    trener_rows_positive = [t for t in trener_rows if Decimal(t["balance"].split()[0]) > 0][:10]
    trener_chart_data = {
        "labels": [t["name"] for t in trener_rows_positive],
        "values": [float(t["balance"].split()[0]) for t in trener_rows_positive],
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
    
    # === GRAF 6 MĚSÍCŮ ===
    monthly_chart_data = []
    current_day_for_loop = today 
    for i in range(6):
        month_start = current_day_for_loop.replace(day=1)
        if month_start.month == 12:
            next_month_start = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            next_month_start = month_start.replace(month=month_start.month + 1, day=1)
        month_end = next_month_start - timedelta(days=1)

        label = f"{czech_months[month_start.month]} '{month_start.strftime('%y')}"
        month_trainings = Trening.objects.filter(datum__date__gte=month_start, datum__date__lte=month_end)
        month_total_min = month_trainings.aggregate(s=Sum("delka_minut"))["s"] or 0
        month_hours = (Decimal(month_total_min) / Decimal(60)).quantize(Decimal("0.01"))
        
        # === OPRAVA: Naúčtováno podle DATUM tréninku (accrual basis) ===
        # Pro konzistenci s ostatními výpočty používáme datum tréninku, ne vytvoreno transakce
        month_charged = Decimal("0.00")
        for tr in month_trainings:
            tr_charges = Transakce.objects.filter(
                trening=tr,
                typ=Transakce.Typ.NAUCTOVANO,
            ).aggregate(s=Sum("castka"))["s"] or 0
            month_charged += Decimal(tr_charges)
        
        # Platby zůstávají podle vytvoreno (cash basis)
        month_paid = Transakce.objects.filter(vytvoreno__date__gte=month_start, vytvoreno__date__lte=month_end, typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).aggregate(s=Sum("castka"))["s"] or Decimal("0")

        monthly_chart_data.append({
            "label": label,
            "hours": float(month_hours),
            "charged": float(month_charged),
            "paid": float(month_paid),
        })
        current_day_for_loop = month_start - timedelta(days=1) 
    
    monthly_chart_data.reverse()

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

    # 4. Čistý zisk celkem = platby od hráčů − výplaty trenérům (CASH BASIS)
    # Toto je konzistentní s grafem čistého zisku (paid - trener_paid)
    net_profit_total = (
        Decimal(total_all_paid) - total_trener_paid_all
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 5. Cash Flow měsíc = přijaté platby − výplaty trenérům v měsíci
    trener_paid_month = Decimal(
        TrenerPlatba.objects.filter(
            vytvoreno__date__gte=m_from_current,
            vytvoreno__date__lte=m_to_current,
        ).aggregate(s=Sum("castka"))["s"] or 0
    )
    cashflow_month = (pays_current - trener_paid_month).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

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

    # === MĚSÍČNÍ DATA PRO ÚČETNÍ GRAFY (6 měsíců) ===
    accounting_monthly_data = []
    current_day_acc = today
    
    for i in range(6):
        month_start_acc = current_day_acc.replace(day=1)
        if month_start_acc.month == 12:
            next_m = month_start_acc.replace(year=month_start_acc.year + 1, month=1, day=1)
        else:
            next_m = month_start_acc.replace(month=month_start_acc.month + 1, day=1)
        month_end_acc = next_m - timedelta(days=1)

        label_acc = f"{czech_months[month_start_acc.month]} '{month_start_acc.strftime('%y')}"

        # Platby od hráčů (cash basis - podle vytvoreno)
        m_paid = Decimal(
            Transakce.objects.filter(
                vytvoreno__date__gte=month_start_acc,
                vytvoreno__date__lte=month_end_acc,
                typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
            ).aggregate(s=Sum("castka"))["s"] or 0
        )
        
        # === OPRAVA: Naúčtováno podle DATUM tréninku (accrual basis) ===
        # Pro konzistenci s earned trenérů používáme datum tréninku, ne vytvoreno transakce
        m_charged = Decimal("0.00")
        m_tqs = Trening.objects.filter(
            datum__date__gte=month_start_acc,
            datum__date__lte=month_end_acc,
        )
        for tr in m_tqs:
            # Najdeme všechny transakce naúčtování pro tento trénink
            tr_charges = Transakce.objects.filter(
                trening=tr,
                typ=Transakce.Typ.NAUCTOVANO,
            ).aggregate(s=Sum("castka"))["s"] or 0
            m_charged += Decimal(tr_charges)
        
        # Výplaty trenérům v tomto měsíci (cash basis - podle vytvoreno)
        m_trener_paid = Decimal(
            TrenerPlatba.objects.filter(
                vytvoreno__date__gte=month_start_acc,
                vytvoreno__date__lte=month_end_acc,
            ).aggregate(s=Sum("castka"))["s"] or 0
        )
        
        # === Earned trenérů v tomto měsíci (accrual basis - podle datum tréninku) ===
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

        # Cash flow = paid - trener_paid (cash basis)
        m_cashflow = float((m_paid - m_trener_paid).quantize(Decimal("0.01")))
        
        # Hrubý zisk = charged - trener_earned (accrual basis - obojí podle datum tréninku)
        m_gross = float((m_charged - m_trener_earned).quantize(Decimal("0.01")))
        
        # Čistý zisk = paid - trener_paid (cash basis - stejné jako cash flow)
        m_net = float((m_paid - m_trener_paid).quantize(Decimal("0.01")))

        accounting_monthly_data.append({
            "label": label_acc,
            "cashflow": m_cashflow,
            "gross_profit": m_gross,
            "net_profit": m_net,  # Přidáno pro JS - stejné jako cashflow
            "paid": float(m_paid),
            "charged": float(m_charged),
            "trener_paid": float(m_trener_paid),
            "trener_earned": float(m_trener_earned),
        })

        current_day_acc = month_start_acc - timedelta(days=1)

    accounting_monthly_data.reverse()

    # === SLOVNÍK PRO ŠABLONU ===
    accounting = {
        "cashflow_month": f"{cashflow_month:.0f} Kč",
        "gross_profit_month": f"{gross_profit_month:.0f} Kč",
        "margin_month": f"{margin_month_pct:.1f} %",
        "revenue_per_hour_month": f"{revenue_per_hour_month:.0f} Kč",
        "total_trener_paid": f"{total_trener_paid_all:.0f} Kč",
        "total_trener_remaining": f"{total_trener_remaining:.0f} Kč",
        "net_profit_total": f"{net_profit_total:.0f} Kč",
        "avg_revenue_per_player_month": f"{avg_revenue_per_player_month:.0f} Kč",
        "gross_profit_total": f"{gross_profit_total:.0f} Kč",
        "margin_total": f"{margin_total_pct:.1f} %",
        "revenue_per_hour_total": f"{revenue_per_hour_total:.0f} Kč",
        "avg_revenue_per_player_total": f"{avg_revenue_per_player_total:.0f} Kč",
        "cashflow_month_value": float(cashflow_month),
        "gross_profit_month_value": float(gross_profit_month),
    }

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
        debtors_chart_data=debtors_chart_data,
        trener_chart_data=trener_chart_data,
        payment_types_data=payment_types_data,
        activity_data=activity_data,
        accounting=accounting,
        accounting_monthly_data=accounting_monthly_data,
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
        "name": h.jmeno,
        "kredit": f"{(h._kredit_calculated or 0):.0f} Kč",
        "url": reverse("admin:core_hrac_change", args=[h.id]),
    } for h in debtors_qs]

    posledni_platby = [
        {
            "when": (dj_tz.localtime(p.vytvoreno) if dj_tz.is_aware(p.vytvoreno) else p.vytvoreno).strftime("%d.%m.%Y %H:%M"),
            "hrac": p.hrac.jmeno,
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
