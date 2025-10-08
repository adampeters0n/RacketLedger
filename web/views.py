from decimal import Decimal
from django.db.models import Sum
from django.shortcuts import render
from core.models import Hrac, Transakce, Dochazka

def _payment_rows():
    rows = []
    for h in Hrac.objects.all().order_by("jmeno"):
        # Poslední platba / vratka
        last_pay = (Transakce.objects
                    .filter(hrac=h, typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA])
                    .order_by('-vytvoreno')
                    .values_list('vytvoreno', flat=True)
                    .first())

        # Naúčtováno od poslední platby
        charges_qs = Transakce.objects.filter(hrac=h, typ=Transakce.Typ.NAUCTOVANO)
        if last_pay:
            charges_qs = charges_qs.filter(vytvoreno__gt=last_pay)
        charges = charges_qs.aggregate(s=Sum('castka'))['s'] or Decimal('0')

        # Hodiny od poslední platby (jen prisel=True)
        mins_qs = Dochazka.objects.filter(hrac=h, prisel=True)
        if last_pay:
            mins_qs = mins_qs.filter(trening__datum__gt=last_pay)
        total_min = mins_qs.aggregate(s=Sum('trening__delka_minut'))['s'] or 0
        hours = (Decimal(total_min) / Decimal(60)).quantize(Decimal('0.01'))

        rows.append({
            "id": h.id,
            "jmeno": h.jmeno,
            "kredit": h.kredit,
            "charges": charges,
            "hours": hours,
        })
    return rows

def dashboard(request):
    ctx = {"kpis": {"debt_sum": 0, "todays_trainings": 0, "last_payments": 0}}
    return render(request, "web/dashboard.html", ctx)

def payments_table(request):
    return render(request, "web/payments.html", {"rows": _payment_rows()})
