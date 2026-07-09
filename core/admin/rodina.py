"""Rodina admin."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, time

from django.contrib import admin, messages
from django.db.models import Sum, Case, When, F, Value, DecimalField
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone as dj_tz
from django.utils.html import format_html, format_html_join

from ..models import Rodina, Transakce


@admin.register(Rodina)
class RodinaAdmin(admin.ModelAdmin):
    list_display = ("nazev", "kredit_total_display")
    list_display_links = ("nazev",)
    ordering = ("nazev",)
    search_fields = ("nazev", "clenove__jmeno")

    fields = ("nazev", "kontakt_email", "clenove_preview")
    readonly_fields = ("clenove_preview",)

    change_form_template = "admin/core/rodina/change_form.html"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            _kredit=Sum(
                Case(
                    When(
                        clenove__transakce__typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
                        then=F("clenove__transakce__castka"),
                    ),
                    When(
                        clenove__transakce__typ=Transakce.Typ.NAUCTOVANO,
                        then=-F("clenove__transakce__castka"),
                    ),
                    default=Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
        ).prefetch_related("clenove")

    def kredit_total_display(self, obj):
        val = obj._kredit or 0
        return f"{int(val):,} Kč".replace(",", " ")
    kredit_total_display.short_description = "KREDIT"
    kredit_total_display.admin_order_field = "_kredit"

    def clenove_preview(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "Nejprve uložte rodinu. Poté se zde zobrazí její členové."

        members = obj.clenove.all().order_by("jmeno")
        if not members:
            return "Rodina nemá žádné členy."

        items = format_html_join(
            "",
            "<li><a href='{}'>{}</a> <span style='opacity:.7'>({} Kč)</span></li>",
            (
                (
                    reverse("admin:core_hrac_change", args=[h.id]),
                    h.jmeno,
                    f"{int(h.kredit):,}".replace(",", " "),
                )
                for h in members
            ),
        )
        return format_html(
            "<ul style='margin:4px 0 0 18px;padding:0'>{}</ul>",
            items,
        )
    clenove_preview.short_description = "Členové rodiny"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        family = self.get_object(request, object_id)

        if request.method == "POST" and "_vyuctovat_rodinu" in request.POST:
            def _parse_date(s, end=False):
                s = (s or "").strip()
                if not s:
                    return None
                try:
                    d = datetime.strptime(s, "%Y-%m-%d").date()
                except Exception:
                    return None
                t = time.max if end else time.min
                return dj_tz.make_aware(datetime.combine(d, t), dj_tz.get_current_timezone())

            vfrom = _parse_date(request.POST.get("_vyuct_from"), end=False)
            vto = _parse_date(request.POST.get("_vyuct_to"), end=True)

            raw_amt = (request.POST.get("_castka_k_uhrazeni") or "").strip()
            override_total = None
            if raw_amt:
                try:
                    override_total = Decimal(raw_amt.replace(",", "."))
                    if override_total < 0:
                        override_total = None
                except Exception:
                    override_total = None

            members = list(family.clenove.all())
            if not members:
                self.message_user(request, "Rodina nemá žádné členy.", level=messages.WARNING)
                return redirect(request.path)

            total_due = Decimal("0.00")
            count = 0

            if override_total is not None:
                comp_map = {}
                positive_sum = Decimal("0.00")
                for h in members:
                    tx_qs = h.transakce.filter(vytvoreno__lte=(vto or dj_tz.now()))
                    if vfrom:
                        tx_qs = tx_qs.filter(vytvoreno__gt=vfrom)
                    ch = Decimal(tx_qs.filter(typ=Transakce.Typ.NAUCTOVANO).aggregate(s=Sum("castka"))["s"] or 0)
                    pay = Decimal(tx_qs.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).aggregate(s=Sum("castka"))["s"] or 0)
                    comp = (ch - pay)
                    comp_map[h] = comp
                    if comp > 0:
                        positive_sum += comp

                cents_total = int((override_total * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                allocations = {}
                if positive_sum > 0:
                    assigned = 0
                    for h in members[:-1]:
                        share = comp_map[h] if comp_map[h] > 0 else Decimal("0")
                        cents = int(((share / positive_sum) * cents_total).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                        allocations[h] = Decimal(cents) / 100
                        assigned += cents
                    allocations[members[-1]] = Decimal(cents_total - assigned) / 100
                else:
                    per = cents_total // len(members)
                    for h in members[:-1]:
                        allocations[h] = Decimal(per) / 100
                    allocations[members[-1]] = Decimal(cents_total - per * (len(members) - 1)) / 100

                for h in members:
                    vyuct = h.vygeneruj_vyuctovani(
                        duvod="rodina",
                        send_email=True,
                        override_amount_due=allocations[h],
                        override_period_from=vfrom,
                        override_period_to=vto,
                    )
                    total_due += Decimal(vyuct.amount_due or 0)
                    count += 1
            else:
                for h in members:
                    vyuct = h.vygeneruj_vyuctovani(
                        duvod="rodina",
                        send_email=True,
                        override_period_from=vfrom,
                        override_period_to=vto,
                    )
                    total_due += Decimal(vyuct.amount_due or 0)
                    count += 1

            self.message_user(
                request,
                f"Vyúčtování rodiny: odesláno {count} členům, celkem k úhradě {total_due:.0f} Kč.",
                level=messages.SUCCESS,
            )
            return redirect(request.path)

        def _parse_date(s):
            try:
                return datetime.strptime(s or "", "%Y-%m-%d").date()
            except Exception:
                return None

        dfrom = _parse_date(request.GET.get("from"))
        dto = _parse_date(request.GET.get("to"))

        members = list(family.clenove.all())
        member_ids = [m.id for m in members] or [-1]

        charges_qs = (
            Transakce.objects
            .filter(hrac_id__in=member_ids, typ=Transakce.Typ.NAUCTOVANO)
            .select_related("trening", "hrac")
        )
        pays_qs = (
            Transakce.objects
            .filter(hrac_id__in=member_ids, typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA])
            .select_related("hrac")
        )

        if dfrom:
            charges_qs = charges_qs.filter(trening__datum__date__gte=dfrom)
            pays_qs = pays_qs.filter(vytvoreno__date__gte=dfrom)
        if dto:
            charges_qs = charges_qs.filter(trening__datum__date__lte=dto)
            pays_qs = pays_qs.filter(vytvoreno__date__lte=dto)

        start_credit = Decimal("0.00")
        if dfrom:
            before_charges = (
                Transakce.objects
                .filter(hrac_id__in=member_ids, typ=Transakce.Typ.NAUCTOVANO, trening__datum__date__lt=dfrom)
                .aggregate(s=Sum("castka"))["s"] or 0
            )
            before_pays = (
                Transakce.objects
                .filter(hrac_id__in=member_ids, typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA], vytvoreno__date__lt=dfrom)
                .aggregate(s=Sum("castka"))["s"] or 0
            )
            start_credit = (Decimal(before_pays) - Decimal(before_charges)).quantize(Decimal("0.01"))

        events = []
        for tx in charges_qs:
            dt = tx.trening.datum if tx.trening else tx.vytvoreno
            if dj_tz.is_aware(dt):
                dt = dj_tz.localtime(dt)
            events.append((dt, tx, True))
        for tx in pays_qs:
            dt = tx.vytvoreno
            if dj_tz.is_aware(dt):
                dt = dj_tz.localtime(dt)
            events.append((dt, tx, False))
        events.sort(key=lambda t: t[0])

        def _fmt_dt(dt):
            return dt.strftime("%d.%m.%Y"), dt.strftime("%H:%M")

        rows = []
        running_credit = start_credit
        total_min = 0
        sum_cena = Decimal("0")
        sum_paid = Decimal("0")

        for dt, tx, is_charge in events:
            datum_str, cas_str = _fmt_dt(dt)

            hrac_jmeno = tx.hrac.jmeno if getattr(tx, "hrac", None) else "—"
            hodiny = skupina = sezona = cena = zaplaceno = ""

            if is_charge and tx.trening:
                total_min += (tx.trening.delka_minut or 0)
                sum_cena += Decimal(tx.castka or 0)
                hodiny_decimal = (Decimal(tx.trening.delka_minut) / Decimal(60)).normalize()
                hodiny = str(hodiny_decimal).replace('.', ',')
                skupina = tx.trening.get_format_display()
                sezona = "léto" if tx.trening.kurt == "VENEK" else "zima"
                cena = f"{Decimal(tx.castka):.0f}"
                running_credit -= Decimal(tx.castka or 0)
            else:
                sum_paid += Decimal(tx.castka or 0)
                zaplaceno = f"{Decimal(tx.castka):.0f}"
                running_credit += Decimal(tx.castka or 0)

            display_kredit = f"{running_credit:.0f}"

            delete_link = ""
            if is_charge and tx.trening:
                delete_url = reverse("admin:core_trening_delete", args=[tx.trening.id])
                delete_link = format_html('<a href="{}" class="deletelink">Smazat</a>', delete_url)
            elif not is_charge:
                delete_url = reverse("admin:core_transakce_delete", args=[tx.id])
                delete_link = format_html('<a href="{}" class="deletelink">Smazat</a>', delete_url)

            rows.append({
                "datum": datum_str,
                "cas": cas_str,
                "hrac": hrac_jmeno,
                "hodiny": hodiny,
                "skupina": skupina,
                "sezona": sezona,
                "cena": cena,
                "zaplaceno": zaplaceno,
                "kredit": display_kredit,
                "akce": delete_link,
                "typ": tx.typ,
            })

        trainings_hours_decimal = (Decimal(total_min) / Decimal(60)).normalize()
        trainings_hours = str(trainings_hours_decimal).replace('.', ',')
        end_credit = running_credit
        trainings_count = charges_qs.count()

        extra_context = extra_context or {}
        extra_context.update({
            "ledger_rows": rows,
            "ledger_totals": {
                "hodiny": trainings_hours,
                "cena": f"{sum_cena:.0f}",
                "zaplaceno": f"{sum_paid:.0f}",
                "credit": f"{end_credit:.0f}",
            },
            "filter_from": dfrom,
            "filter_to": dto,
            "family_members": family.clenove.all(),
            "family_summary": {
                "trainings_count": trainings_count,
                "trainings_sum": f"{sum_cena:.0f} Kč",
                "payments_sum": f"{sum_paid:.0f} Kč",
                "credit": f"{end_credit:.0f} Kč",
                "credit_raw": end_credit,
            },
        })
        return super().change_view(request, object_id, form_url, extra_context=extra_context)
