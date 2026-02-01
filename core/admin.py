# core/admin.py
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, time, timedelta
import logging
import json

from django.conf import settings
from django.db import transaction
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Sum, Case, When, F, Value, DecimalField, Q
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone as dj_tz
from django.utils.html import format_html, format_html_join
from django import forms
from django.contrib.admin.widgets import AdminSplitDateTime
from django.forms.models import BaseInlineFormSet

from .models import (
    Hrac,
    Trening,
    Dochazka,
    Transakce,
    Cenik,
    Vyuctovani,
    TrenerProfil,
    TrenerSazba,
    TrenerPlatba,
    sazba_trenera_k_datu,
    Rodina,
)

User = get_user_model()
logger = logging.getLogger(__name__)


# -----------------------------
#  Hráči
# -----------------------------
@admin.register(Hrac)
class HracAdmin(admin.ModelAdmin):
    list_display = ("jmeno", "email", "kredit_display", "rodina_link")
    search_fields = ("jmeno",)
    fields = ("jmeno", "email", "rodina")
    
    # PŘIDÁNA NOVÁ AKCE DO SEZNAMU
    actions = ["akce_vygenerovat_vyuctovani", "akce_pridat_platbu"]

    change_form_template = "admin/core/hrac/change_form.html"
    change_list_template = "admin/core/hrac/change_list.html"
    
    list_per_page = 10_000
    list_max_show_all = 10_000
    
    # === ZMĚNA #1: PŘEJMENOVÁNÍ ANOTACE PRO ŘAZENÍ ===
    def get_queryset(self, request):
        """
        Přidá anotaci pro kredit, aby podle ní šlo řadit.
        Pojmenujeme ji "_kredit_sort", aby nedošlo ke konfliktu.
        """
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(
            _kredit_sort=Sum(  # Přejmenováno z "kredit"
                Case(
                    When(transakce__typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA], then=F("transakce__castka")),
                    When(transakce__typ=Transakce.Typ.NAUCTOVANO, then=-F("transakce__castka")),
                    default=Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
        )
        return queryset
    # === KONEC ZMĚNY #1 ===

    # --- URL pro stránku "Změna informací" + POST vyúčtování ---
    def get_urls(self):
        urls = super().get_urls()
        my = [
            path(
                "<int:object_id>/info/",
                self.admin_site.admin_view(self.info_view),
                name="core_hrac_info",
            ),
            path(
                "<int:object_id>/vyuctovat/",
                self.admin_site.admin_view(self.vyuctovat_view),
                name="core_hrac_vyuctovat",
            ),
        ]
        return my + urls

    class HracInfoForm(forms.ModelForm):
        class Meta:
            model = Hrac
            fields = ["jmeno", "email", "rodina"]
            widgets = {
                "jmeno": forms.TextInput(attrs={"class": "vTextField"}),
                "email": forms.EmailInput(attrs={"class": "vTextField"}),
            }

    def info_view(self, request, object_id, *args, **kwargs):
        hrac = self.get_object(request, object_id)
        if not hrac:
            return redirect("admin:core_hrac_changelist")
        if request.method == "POST":
            form = self.HracInfoForm(request.POST, instance=hrac)
            if form.is_valid():
                form.save()
                self.message_user(request, "Informace uloženy.", level=messages.SUCCESS)
                return redirect("admin:core_hrac_change", object_id)
        else:
            form = self.HracInfoForm(instance=hrac)
        ctx = dict(
            self.admin_site.each_context(request),
            title=f"Změna informací – {hrac.jmeno}",
            opts=self.model._meta,
            original=hrac,
            form=form,
        )
        return TemplateResponse(request, "admin/core/hrac/info_form.html", ctx)

    # === ZMĚNA: UPRAVENÁ METODA PRO INDIVIDUÁLNÍ VYÚČTOVÁNÍ ===
    def vyuctovat_view(self, request, object_id, *args, **kwargs):
        """POST endpoint pro tlačítko 'Vygenerovat vyúčtování teď'."""
        hrac = self.get_object(request, object_id)
        if not hrac:
            self.message_user(request, "Hráč neexistuje.", level=messages.ERROR)
            return redirect("admin:core_hrac_changelist")

        if request.method != "POST":
            return redirect("admin:core_hrac_change", object_id)

        # volitelná částka k úhradě
        raw_amt = (request.POST.get("_castka_k_uhrazeni") or "").strip()
        override_amount = None
        if raw_amt:
            try:
                override_amount = Decimal(raw_amt.replace(",", "."))
                if override_amount < 0:
                    override_amount = None
            except (InvalidOperation, ValueError):
                override_amount = None

        # volitelné období Od/Do (YYYY-MM-DD)
        def _parse_date(s: str, end: bool = False):
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

        # === ZMĚNA: PŘEČTEME VARIANTU E-MAILU ===
        email_variant = request.POST.get("_email_variant", "1")
        # === KONEC ZMĚNY ===

        logger.info(
            ">>> HRAC_VYUCTOVAT: start hrac_id=%s jmeno=%s email=%s override_amount=%s vfrom=%s vto=%s variant=%s",
            hrac.pk, hrac.jmeno, hrac.email, override_amount, vfrom, vto, email_variant
        )

        vyuct = hrac.vygeneruj_vyuctovani(
            duvod="manual",
            send_email=True,
            email_variant=email_variant, # <-- PŘEDÁME VARIANTU
            override_amount_due=override_amount,
            override_period_from=vfrom,
            override_period_to=vto,
        )

        logger.info(
            ">>> HRAC_VYUCTOVAT: hotovo hrac_id=%s amount_due=%s vyuct_id=%s",
            hrac.pk, getattr(vyuct, "amount_due", None), getattr(vyuct, "pk", None)
        )

        self.message_user(
            request,
            f"Vyúčtování vytvořeno. K úhradě: {vyuct.amount_due:.0f} Kč. "
            f"E-mail: {'odeslán' if hrac.email else 'není vyplněn'}",
            level=messages.SUCCESS,
        )
        return redirect("admin:core_hrac_change", object_id)
    # === KONEC UPRAVENÉ METODY ===

    # === ZMĚNA #2: PROPOJENÍ SLOUPCE S NOVOU HODNOTOU PRO ŘAZENÍ ===
    def kredit_display(self, obj):
        # Pro zobrazení stále používáme původní vlastnost modelu `obj.kredit`
        return f"{obj.kredit:.0f} Kč"
    kredit_display.short_description = "Kredit"
    # Pro řazení ale použijeme náš nový výpočet
    kredit_display.admin_order_field = "_kredit_sort"  
    # === KONEC ZMĚNY #2 ===

    def rodina_link(self, obj):
        if not obj.rodina_id:
            return "—"
        url = reverse("admin:core_rodina_change", args=[obj.rodina_id])
        nazev = obj.rodina.nazev or f"Rodina #{obj.rodina_id}"
        return format_html('<a href="{}">{}</a>', url, nazev)
    rodina_link.short_description = "Rodina"

    # === ZMĚNA: UPRAVENÁ METODA PRO HROMADNOU AKCI (VYÚČTOVÁNÍ) ===
    def akce_vygenerovat_vyuctovani(self, request, queryset):
        
        # 1. Zkopírujeme pomocnou funkci pro parsování data
        def _parse_date(s: str, end: bool = False):
            s = (s or "").strip()
            if not s:
                return None
            try:
                d = datetime.strptime(s, "%Y-%m-%d").date()
            except Exception:
                return None
            t = time.max if end else time.min
            return dj_tz.make_aware(datetime.combine(d, t), dj_tz.get_current_timezone())

        # 2. Přečteme hodnoty z request.POST (které nám přidá JavaScript)
        vfrom = _parse_date(request.POST.get("_bulk_vyuct_from"), end=False)
        vto = _parse_date(request.POST.get("_bulk_vyuct_to"), end=True)
        
        raw_amt = (request.POST.get("_bulk_castka_k_uhrazeni") or "").strip()
        override_amount = None
        if raw_amt:
            try:
                override_amount = Decimal(raw_amt.replace(",", "."))
                if override_amount < 0:
                    override_amount = None
            except (InvalidOperation, ValueError):
                override_amount = None
        
        email_variant = request.POST.get("_bulk_email_variant", "1")

        count = 0
        for hrac in queryset:
            vyuct = hrac.vygeneruj_vyuctovani(
                duvod="manual",
                send_email=True,
                email_variant=email_variant, 
                override_amount_due=override_amount,
                override_period_from=vfrom,
                override_period_to=vto,
            )
            logger.info(
                ">>> HRAC_AKCE_VYUCTOVAT: hrac_id=%s email=%s amount_due=%s vyuct_id=%s",
                hrac.pk, hrac.email, getattr(vyuct, "amount_due", None), getattr(vyuct, "pk", None)
            )
            count += 1
        self.message_user(request, f"Vyúčtování vytvořeno pro {count} hráčů.", level=messages.SUCCESS)
    akce_vygenerovat_vyuctovani.short_description = "Vygenerovat vyúčtování (poslat e-mail)"
    
    
    # === NOVÁ AKCE: HROMADNÁ PLATBA ===
    def akce_pridat_platbu(self, request, queryset):
        # Načtení dat z JS
        raw_amount = request.POST.get("_bulk_payment_amount")
        raw_date = request.POST.get("_bulk_payment_date")
        typ = request.POST.get("_bulk_payment_type")
        note = request.POST.get("_bulk_payment_note", "")

        if not raw_amount:
            return

        try:
            castka = Decimal(raw_amount.replace(",", "."))
            
            # --- Zde je tvá vylepšená logika pro datum ---
            if raw_date:
                # Převedeme string na datum (vznikne čas 00:00:00)
                datum_obj = datetime.strptime(raw_date, "%Y-%m-%d")
                
                # Získáme aktuální čas
                now = dj_tz.now()
                
                # Spojíme vybrané datum s aktuálním časem (zachováme hodiny/minuty)
                datum = datum_obj.replace(hour=now.hour, minute=now.minute, second=now.second)
                
                # Pokud používáte časová pásma, uděláme datum "aware"
                if settings.USE_TZ:
                    datum = dj_tz.make_aware(datum)
            else:
                # Pokud datum nebylo vybráno, použijeme "teď"
                datum = dj_tz.now()
            # ---------------------------------------------

            count = 0
            with transaction.atomic():
                for hrac in queryset:
                    Transakce.objects.create(
                        hrac=hrac,
                        typ=typ,
                        castka=castka,
                        popis=note,
                        vytvoreno=datum
                    )
                    count += 1
            
            self.message_user(request, f"Hromadná platba: Úspěšně přidáno {castka} Kč pro {count} hráčů.", messages.SUCCESS)

        except (ValueError, InvalidOperation) as e:
            self.message_user(request, f"Chyba při zadávání platby: {e}", messages.ERROR)

    akce_pridat_platbu.short_description = "Zadat platbu vybraným hráčům"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        hrac = Hrac.objects.get(pk=object_id)

        def _parse_date(s: str):
            try:
                return datetime.strptime(s, "%Y-%m-%d").date()
            except Exception:
                return None

        dfrom = _parse_date(request.GET.get("from", ""))
        dto = _parse_date(request.GET.get("to", ""))

        charges_qs = (
            hrac.transakce
            .filter(typ=Transakce.Typ.NAUCTOVANO)
            .select_related("trening")
        )
        if dfrom:
            charges_qs = charges_qs.filter(trening__datum__date__gte=dfrom)
        if dto:
            charges_qs = charges_qs.filter(trening__datum__date__lte=dto)

        pays_qs = (
            hrac.transakce
            .filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA])
            .select_related("trening")
        )
        if dfrom:
            pays_qs = pays_qs.filter(vytvoreno__date__gte=dfrom)
        if dto:
            pays_qs = pays_qs.filter(vytvoreno__date__lte=dto)

        start_credit = Decimal("0")
        if dfrom:
            before_charges = (
                hrac.transakce
                .filter(typ=Transakce.Typ.NAUCTOVANO, trening__datum__date__lt=dfrom)
                .aggregate(s=Sum("castka"))["s"] or 0
            )
            before_pays = (
                hrac.transakce
                .filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA], vytvoreno__date__lt=dfrom)
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
            if not dt:
                return "", ""
            if dj_tz.is_aware(dt):
                dt = dj_tz.localtime(dt)
            return dt.strftime("%d.%m.%Y"), dt.strftime("%H:%M")

        rows = []
        running_credit = start_credit
        total_min = 0
        sum_cena = Decimal("0")
        sum_paid = Decimal("0")

        for dt, tx, is_charge in events:
            datum_str, cas_str = _fmt_dt(dt)

            hodiny = skupina = sezona = cena = zaplaceno = ""
            if is_charge and tx.trening:
                total_min += (tx.trening.delka_minut or 0)
                sum_cena += Decimal(tx.castka or 0)

                # ZDE JE FINÁLNÍ OPRAVA pro řádky tabulky
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
                "hodiny": hodiny,
                "skupina": skupina,
                "sezona": sezona,
                "cena": cena,
                "zaplaceno": zaplaceno,
                "kredit": display_kredit,
                "akce": delete_link,
                "typ": tx.typ,
            })

        trainings_count = charges_qs.count()
        
        # ZDE JE FINÁLNÍ OPRAVA pro součtový řádek
        trainings_hours_decimal = (Decimal(total_min) / Decimal(60)).normalize()
        trainings_hours = str(trainings_hours_decimal).replace('.', ',')
        
        end_credit = running_credit

        extra_context = extra_context or {}
        extra_context["ledger_rows"] = rows
        extra_context["ledger_totals"] = {
            "hodiny": trainings_hours,
            "cena": f"{sum_cena:.0f}",
            "zaplaceno": f"{sum_paid:.0f}",
            "credit": f"{end_credit:.0f}",
        }
        extra_context["filter_from"] = dfrom
        extra_context["filter_to"] = dto
        extra_context["show_generate_button"] = True
        extra_context["vyuctovani_list_url"] = f"{reverse('admin:core_vyuctovani_changelist')}?hrac__id__exact={object_id}"

        extra_context["player_summary"] = {
            "trainings_count": trainings_count,
            "trainings_sum": f"{sum_cena:.0f} Kč",
            "payments_sum": f"{sum_paid:.0f} Kč",
            "credit": f"{end_credit:.0f} Kč",
            "credit_raw": end_credit,
        }

        return super().change_view(request, object_id, form_url, extra_context=extra_context)


# -----------------------------
#  Rodina (beze změny)
# -----------------------------
@admin.register(Rodina)
class RodinaAdmin(admin.ModelAdmin):
    list_display = ("nazev", "kredit_total_display")
    list_display_links = ("nazev",)
    ordering = ("nazev",)
    search_fields = ("nazev", "clenove__jmeno")

    fields = ("nazev", "kontakt_email", "clenove_preview")
    readonly_fields = ("clenove_preview",)

    change_list_template = "admin/core/rodina/change_list.html"
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

                # --- ZDE JE OPRAVA ---
            delete_link = ""
            if is_charge and tx.trening:
                # Pokud je to naúčtování za trénink, odkaz směřuje na smazání tréninku
                delete_url = reverse("admin:core_trening_delete", args=[tx.trening.id])
                delete_link = format_html('<a href="{}" class="deletelink">Smazat</a>', delete_url)
            elif not is_charge:
                # Pokud je to platba/vratka, odkaz směřuje na smazání transakce
                delete_url = reverse("admin:core_transakce_delete", args=[tx.id])
                delete_link = format_html('<a href="{}" class="deletelink">Smazat</a>', delete_url)
            # --- KONEC OPRAVY ---

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


# -----------------------------
#  Ceník (beze změny)
# -----------------------------
@admin.register(Cenik)
class CenikAdmin(admin.ModelAdmin):
    list_display = ("format", "kurt", "cena_za_hodinu", "platnost_od", "platnost_do")
    list_filter = ("format", "kurt")
    # Změna zde:
    search_fields = ("format", "kurt")


# ---------------------------------------------------------
#  DOCHÁZKA – kompletní inline s ochranou proti duplicitám
# ---------------------------------------------------------

class DochazkaInlineForm(forms.ModelForm):
    class Meta:
        model = Dochazka
        fields = ["hrac"]

    def save(self, commit=True):
        """Každý vyplněný řádek automaticky označí, že hráč přišel."""
        obj = super().save(commit=False)
        obj.prisel = True
        if commit:
            obj.save()
        return obj


class DochazkaFormSet(BaseInlineFormSet):
    """
    Tento FormSet je klíčem k opravě. Přeskočí validaci proti databázi (validate_unique),
    ale v rámci clean() pohlídá, abys nevybral jednoho hráče 2x v jednom okně.
    """
    def clean(self):
        """
        Kontrola duplicit přímo ve formuláři na obrazovce.
        """
        super().clean()
        if any(self.errors):
            return

        hraci_v_seznamu = []
        for form in self.forms:
            # Ignorujeme prázdné formuláře nebo ty, které uživatel označil ke smazání
            if self._should_delete_form(form) or not form.cleaned_data.get('hrac'):
                continue
            
            hrac = form.cleaned_data.get('hrac')
            if hrac in hraci_v_seznamu:
                # Vyhodí chybu pouze pokud je stejné jméno v seznamu vícekrát
                raise ValidationError(f"Hráč {hrac} je v tomto tréninku vybrán vícekrát!")
            hraci_v_seznamu.append(hrac)

    def validate_unique(self):
        """
        Tady říkáme: 'Nekontroluj to, co je v DB'. To vyřešíme v save_formset v TreningAdminu.
        """
        pass


class DochazkaInline(admin.TabularInline):
    model = Dochazka
    form = DochazkaInlineForm
    formset = DochazkaFormSet  # Přidání FormSetu s naší logikou
    extra = 1
    autocomplete_fields = ("hrac",)

    fields = (
        "hrac",
        "cena_preview",
        "castka_nauc_display",
        "nauceno_kdy_display",
    )
    readonly_fields = (
        "cena_preview",
        "castka_nauc_display",
        "nauceno_kdy_display",
    )

    exclude = ("prisel",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "hrac":
            w = field.widget
            for attr in ("can_add_related", "can_change_related", "can_view_related", "can_delete_related"):
                if hasattr(w, attr):
                    setattr(w, attr, False)
        return field

    def get_formset(self, request, obj=None, **kwargs):
        self.parent_obj = obj
        return super().get_formset(request, obj, **kwargs)

    def cena_preview(self, obj):
        tr = obj.trening if getattr(obj, "trening_id", None) else getattr(self, "parent_obj", None)
        if not tr:
            return "—"
        try:
            return f"{tr.cena_na_hrace():.0f} Kč"
        except Exception:
            return "—"
    cena_preview.short_description = "Cena (Kč)"

    def castka_nauc_display(self, obj):
        value = getattr(obj, "castka_nauc", None)
        if value is None:
            return "—"
        try:
            return f"{Decimal(value):.0f} Kč"
        except Exception:
            return str(value)
    castka_nauc_display.short_description = "Naúčtováno (Kč)"

    def nauceno_kdy_display(self, obj):
        dt = getattr(obj, "nauceno_kdy", None)
        if not dt:
            return "—"
        try:
            if dj_tz.is_aware(dt):
                dt = dj_tz.localtime(dt)
            return dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            return str(dt)
    nauceno_kdy_display.short_description = "Naúčtováno kdy"


# -----------------------------
#  TRÉNINK (beze změny)
# -----------------------------
class TimeDatalistTextInput(forms.TextInput):
    input_type = "text"

    def __init__(self, *args, **kwargs):
        attrs = kwargs.setdefault("attrs", {})
        attrs.setdefault("placeholder", "např. 13:00")
        attrs.setdefault("autocomplete", "off")
        attrs.setdefault("inputmode", "text")
        attrs.setdefault("pattern", r"^([01]\d|2[0-3]):[0-5]\d$")
        attrs.setdefault("title", "Zadej čas ve tvaru HH:MM (např. 13:00)")
        super().__init__(*args, **kwargs)

    def render(self, name, value, attrs=None, renderer=None):
        attrs = {} if attrs is None else attrs.copy()
        base_id = attrs.get("id", name)
        list_id = f"{base_id}-time-suggest"
        attrs["list"] = list_id

        html = super().render(name, value, attrs, renderer)

        options = []
        for h in range(6, 24):
            options.append(f"<option value='{h:02d}:00'></option>")
            options.append(f"<option value='{h:02d}:30'></option>")
        datalist = f"<datalist id='{list_id}'>" + "".join(options) + "</datalist>"
        return html + datalist


class AdminSplitDateTimeWithDatalist(AdminSplitDateTime):
    """AdminSplitDateTime s textovým time inputem + datalist návrhy."""
    def __init__(self, attrs=None):
        super().__init__(attrs=attrs)
        self.widgets[1] = TimeDatalistTextInput()


@admin.register(Trening)
class TreningAdmin(admin.ModelAdmin):
    change_form_template = "admin/core/trening/change_form.html"
    list_display = ("datum", "hraci_jmena", "trener_jmeno", "format_display", "castka_na_hrace_kc")
    list_filter = ("trener", "format", "kurt", "datum")
    search_fields = (
        "trener__username", "trener__first_name", "trener__last_name",
        "poznamka", "dochazky__hrac__jmeno"
    )
    list_per_page = 50
    inlines = [DochazkaInline]
    actions = ["znovu_zpracovat_uctovani"]

    # --- AGRESIVNÍ SWAP FUNKCE ---
    def save_formset(self, request, form, formset, change):
        """
        Při úpravě existujícího tréninku nejdříve smaže veškerou starou docházku,
        čímž uvolní místo pro nové (i stejné) hráče, a pak uloží ty aktuální z webu.
        """
        if formset.model == Dochazka:
            if change:
                # 1. Smažeme úplně všechnu starou docházku pro tento trénink
                # To automaticky smaže i staré transakce díky tvému signálu post_delete
                form.instance.dochazky.all().delete()
            
            # 2. Uložíme ty hráče, které vidíš teď ve formuláři
            instances = formset.save(commit=False)
            for instance in instances:
                # Musíme znovu přiřadit trénink, protože jsme ho v kroku 1 "vyčistili"
                instance.trening = form.instance
                instance.save()
            formset.save_m2m()
        else:
            super().save_formset(request, form, formset, change)

    # --- ZBYTEK TVÉHO KÓDU ---
    def get_form(self, request, obj=None, **kwargs):
        Form = super().get_form(request, obj, **kwargs)
        if "delka_minut" in Form.base_fields:
            field = Form.base_fields["delka_minut"]
            field.label = "Délka (hodiny)"
            CHOICES = [
                (30, "30 min"),
                (45, "45 min"),
                (60, "1 h"),
                (90, "1,5 h"),
                (120, "2 h"),
                (150, "2,5 h"),
                (180, "3 h"),
            ]
            field.widget = forms.Select(choices=CHOICES)
            field.help_text = ""
            if obj is None:
                field.initial = 60
        return Form

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "datum":
            kwargs["widget"] = AdminSplitDateTimeWithDatalist()
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path("schedule/", self.admin_site.admin_view(self.schedule_view), name="core_trening_schedule"),
            path("treneri/summary/", self.admin_site.admin_view(self.treneri_summary_view), name="core_treneri_summary"),
            path("treneri/<int:user_id>/", self.admin_site.admin_view(self.trener_detail_view), name="core_treneri_detail"),
        ]
        return extra + urls

    def hraci_jmena(self, obj: Trening):
        names = [d.hrac.jmeno for d in obj.dochazky.select_related("hrac").filter(prisel=True)]
        return ", ".join(names) if names else "—"
    hraci_jmena.short_description = "Hráč(i)"

    def trener_jmeno(self, obj: Trening):
        full = (getattr(obj.trener, "get_full_name", None) or (lambda: ""))()
        return full or obj.trener.username
    trener_jmeno.short_description = "Trenér"

    def format_display(self, obj: Trening):
        return obj.get_format_display()
    format_display.short_description = "Formát"

    def castka_na_hrace_kc(self, obj: Trening):
        return f"{obj.cena_na_hrace()} Kč"
    castka_na_hrace_kc.short_description = "Částka / hráč"

    # >>> ROZVRH – týdenní/denní přehled
    def schedule_view(self, request):
        """Týdenní/denní rozvrh tréninků s filtry + rozložení překryvů do pruhů."""
        q = request.GET
        CZECH_DOW = ["po", "út", "st", "čt", "pá", "so", "ne"]

        def _slug(s: str) -> str:
            s = (s or "").strip().lower()
            repl = (("á", "a"), ("č", "c"), ("ď", "d"), ("é", "e"), ("ě", "e"), ("í", "i"),
                    ("ň", "n"), ("ó", "o"), ("ř", "r"), ("š", "s"), ("ť", "t"), ("ú", "u"),
                    ("ů", "u"), ("ý", "y"), ("ž", "z"))
            for a, b in repl:
                s = s.replace(a, b)
            import re
            s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
            if not s or not s[0].isalpha():
                s = f"f-{s or 'neznamy'}"
            return s

        try:
            base_date = datetime.strptime(q.get("date", ""), "%Y-%m-%d").date()
        except Exception:
            base_date = dj_tz.localdate()

        mode = q.get("view", "week")
        start_day = base_date if mode == "day" else (base_date - timedelta(days=base_date.weekday()))
        end_day = start_day if mode == "day" else (start_day + timedelta(days=6))

        start_dt = dj_tz.make_aware(datetime.combine(start_day, time.min))
        end_dt = dj_tz.make_aware(datetime.combine(end_day, time.max))

        trainer_id = q.get("trener") or ""
        qs = (
            Trening.objects
            .filter(datum__range=(start_dt, end_dt))
            .select_related("trener")
            .prefetch_related("dochazky__hrac")
            .order_by("datum")
        )
        if trainer_id:
            qs = qs.filter(trener_id=trainer_id)

        day_start_min = 6 * 60
        hours = list(range(6, 23))

        day_count = (end_day - start_day).days + 1
        days = []
        for i in range(day_count):
            d = start_day + timedelta(days=i)
            label = f"{CZECH_DOW[d.weekday()]} {d.strftime('%d.%m.')}"
            days.append({"date": d, "label": label, "events": []})
        idx_by_date = {(start_day + timedelta(days=i)): i for i in range(day_count)}

        for t in qs:
            local = dj_tz.localtime(t.datum) if dj_tz.is_aware(t.datum) else t.datum
            d = local.date()
            i = idx_by_date.get(d)
            if i is None:
                continue

            start_min = local.hour * 60 + local.minute
            offset = max(0, start_min - day_start_min)
            dur = int(t.delka_minut)

            fmt_label = t.get_format_display()
            fmt_slug = _slug(fmt_label)

            ev = {
                "id": t.id,
                "offset_min": offset,
                "dur_min": dur,
                "end_min": offset + dur,
                "title": ", ".join(
                    dch.hrac.jmeno for dch in t.dochazky.select_related("hrac").filter(prisel=True)
                ) or "—",
                "sub": f"{fmt_label} • {t.get_kurt_display()}",
                "fmt": fmt_slug,
                "fmt_label": fmt_label,
            }
            days[i]["events"].append(ev)

        def assign_lanes(evs):
            if not evs:
                return
            evs.sort(key=lambda e: (e["offset_min"], e["dur_min"]))

            cluster = []
            cluster_max_end = -1

            def finalize_cluster(cluster_events):
                lanes_end = []
                for e in cluster_events:
                    placed = False
                    for idx, end in enumerate(lanes_end):
                        if e["offset_min"] >= end:
                            e["lane"] = idx
                            lanes_end[idx] = e["end_min"]
                            placed = True
                            break
                    if not placed:
                        lanes_end.append(e["end_min"])
                        e["lane"] = len(lanes_end) - 1
                total = len(lanes_end)
                for e in cluster_events:
                    e["lanes"] = total

            for e in evs:
                if not cluster:
                    cluster = [e]
                    cluster_max_end = e["end_min"]
                    continue
                if e["offset_min"] < cluster_max_end:
                    cluster.append(e)
                    if e["end_min"] > cluster_max_end:
                        cluster_max_end = e["end_min"]
                else:
                    finalize_cluster(cluster)
                    cluster = [e]
                    cluster_max_end = e["end_min"]

            if cluster:
                finalize_cluster(cluster)

        for day in days:
            assign_lanes(day["events"])

        step = 7 if mode == "week" else 1
        ctx = dict(self.admin_site.each_context(request))
        ctx.update({
            "title": "Rozvrh tréninků",
            "active_menu": "rozvrh",
            "view_mode": mode,
            "trainers": User.objects.order_by("username"),
            "selected_trainer": int(trainer_id) if trainer_id else "",
            "date_value": base_date.strftime("%Y-%m-%d"),
            "prev_date": (base_date - timedelta(days=step)).strftime("%Y-%m-%d"),
            "next_date": (base_date + timedelta(days=step)).strftime("%Y-%m-%d"),
            "hours": hours,
            "day_start_min": day_start_min,
            "days": days,
        })
        return TemplateResponse(request, "admin/core/trening/kalendar.html", ctx)

    # === SOUHRN TRENÉRŮ ===
    def treneri_summary_view(self, request):
        def _parse(s):
            try:
                return datetime.strptime(s, "%Y-%m-%d").date()
            except Exception:
                return None

        dfrom = _parse(request.GET.get("from", ""))
        dto = _parse(request.GET.get("to", ""))

        base_qs = Trening.objects.all()
        if dfrom:
            base_qs = base_qs.filter(datum__date__gte=dfrom)
        if dto:
            base_qs = base_qs.filter(datum__date__lte=dto)

        trener_ids = list(base_qs.values_list("trener_id", flat=True).distinct())

        rows = []
        total_due = Decimal("0.00")

        for uid in trener_ids:
            u = User.objects.get(pk=uid)
            tqs = base_qs.filter(trener_id=uid).order_by("datum").prefetch_related("dochazky__hrac")

            total_min = 0
            due = Decimal("0.00")
            for t in tqs:
                rate = sazba_trenera_k_datu(u, t.datum)
                hours_val = (Decimal(t.delka_minut) / Decimal(60)).quantize(Decimal("0.01"))
                due += (hours_val * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                total_min += t.delka_minut

            hodiny = (Decimal(total_min) / Decimal(60)).quantize(Decimal("0.01"))
            total_due += due

            paid_qs = TrenerPlatba.objects.filter(user=u)
            if dfrom:
                paid_qs = paid_qs.filter(vytvoreno__date__gte=dfrom)
            if dto:
                paid_qs = paid_qs.filter(vytvoreno__date__lte=dto)
            paid = Decimal(paid_qs.aggregate(s=Sum("castka"))["s"] or 0)
            balance = (due - paid).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            rows.append({
                "trener": (u.get_full_name() or u.username),
                "trener_change_url": reverse("admin:auth_user_change", args=[u.id]),
                "detail_url": reverse("admin:core_treneri_detail", args=[u.id]) + (
                    f"?from={dfrom}&to={dto}" if dfrom or dto else ""
                ),
                "pocet": tqs.count(),
                "hodiny": f"{hodiny:.2f}",
                "dluzno": f"{due:.0f} Kč",
                "zaplaceno": f"{paid:.0f} Kč",
                "k_vyplaceni": f"{balance:.0f} Kč",
                "vyplata_url": reverse("admin:core_trenerplatba_add") + f"?user={u.id}&amount={balance}",
            })

        total_paid_qs = TrenerPlatba.objects.all()
        if dfrom:
            total_paid_qs = total_paid_qs.filter(vytvoreno__date__gte=dfrom)
        if dto:
            total_paid_qs = total_paid_qs.filter(vytvoreno__date__lte=dto)
        total_paid = Decimal(total_paid_qs.aggregate(s=Sum("castka"))["s"] or 0)
        total_balance = (total_due - total_paid)

        ctx = dict(
            self.admin_site.each_context(request),
            title="Trenéři – souhrn",
            rows=rows,
            total_due=f"{total_due:.0f} Kč",
            total_paid=f"{total_paid:.0f} Kč",
            total_balance=f"{total_balance:.0f} Kč",
            dfrom=dfrom, dto=dto,
            active_menu="treneri",
        )
        return TemplateResponse(request, "admin/core/trening/treneri_summary.html", ctx)

    # === DETAIL TRENÉRA (S FORMULÁŘEM PRO SAZBU) ===
    def trener_detail_view(self, request, user_id: int):
        u = User.objects.get(pk=user_id)

        if request.method == "POST" and "_nastavit_sazbu" in request.POST:
            date_raw = (request.POST.get("rate_from") or "").strip()
            amt_raw = (request.POST.get("rate_amount") or "").strip()

            try:
                eff_from = datetime.strptime(date_raw, "%Y-%m-%d").date()
            except Exception:
                messages.error(request, "Neplatné datum „Od“.")
                return redirect(request.get_full_path())

            try:
                amount = Decimal(amt_raw.replace(",", "."))
                if amount <= 0:
                    raise ValueError()
            except Exception:
                messages.error(request, "Neplatná částka sazby.")
                return redirect(request.get_full_path())

            try:
                TrenerSazba.set_rate_from(user=u, effective_from=eff_from, rate=amount)
            except ValidationError as e:
                messages.error(request, f"Sazbu se nepodařilo nastavit: {e}")
            else:
                messages.success(
                    request,
                    f"Sazba {amount:.0f} Kč/h nastavena od {eff_from.strftime('%d.%m.%Y')}."
                )
            return redirect(request.get_full_path())

        def _parse(s):
            try:
                return datetime.strptime(s, "%Y-%m-%d").date()
            except Exception:
                return None

        dfrom = _parse(request.GET.get("from", ""))
        dto = _parse(request.GET.get("to", ""))

        tqs = Trening.objects.filter(trener=u)
        if dfrom:
            tqs = tqs.filter(datum__date__gte=dfrom)
        if dto:
            tqs = tqs.filter(datum__date__lte=dto)
        tqs = tqs.prefetch_related("dochazky__hrac").order_by("-datum")

        rows, total_min, total_due = [], 0, Decimal("0.00")
        for t in tqs:
            dt = dj_tz.localtime(t.datum) if dj_tz.is_aware(t.datum) else t.datum
            hours = (Decimal(t.delka_minut) / Decimal(60)).quantize(Decimal("0.01"))
            rate = sazba_trenera_k_datu(u, dt)
            castka = (hours * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_min += t.delka_minut
            total_due += castka

            hraci = ", ".join(
                d.hrac.jmeno for d in t.dochazky.select_related("hrac").filter(prisel=True)
            ) or "—"

            rows.append({
                "datum": dt.strftime("%d.%m.%Y"),
                "cas": dt.strftime("%H:%M"),
                "format": t.get_format_display(),
                "kurt": t.get_kurt_display(),
                "hraci": hraci,
                "hodiny": f"{hours:.2f}",
                "sazba": f"{rate:.0f} Kč/h",
                "castka": f"{castka:.0f} Kč",
                "trening_change_url": reverse("admin:core_trening_change", args=[t.id]),
            })

        total_hours = (Decimal(total_min) / Decimal(60)).quantize(Decimal("0.01"))

        platby_qs = TrenerPlatba.objects.filter(user=u).order_by("-vytvoreno")
        if dfrom:
            platby_qs = platby_qs.filter(vytvoreno__date__gte=dfrom)
        if dto:
            platby_qs = platby_qs.filter(vytvoreno__date__lte=dto)

        platby_rows = []
        for p in platby_qs:
            ts = dj_tz.localtime(p.vytvoreno) if dj_tz.is_aware(p.vytvoreno) else p.vytvoreno
            platby_rows.append({
                "datum": ts.strftime("%d.%m.%Y"),
                "cas": ts.strftime("%H:%M"),
                "castka": f"{Decimal(p.castka):.0f} Kč",
                "poznamka": p.poznamka or "—",
                "change_url": reverse("admin:core_trenerplatba_change", args=[p.id]),
            })

        paid = Decimal(platby_qs.aggregate(s=Sum("castka"))["s"] or 0)
        balance = (total_due - paid).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        rate_today = sazba_trenera_k_datu(u, dj_tz.now())
        rate_today_amount = f"{rate_today:.0f}"
        rate_today_date = dj_tz.localdate().strftime("%Y-%m-%d")
        rate_form_initial_date = rate_today_date

        sazby = (
            TrenerSazba.objects.filter(user=u).order_by("-platnost_od")
            .values("id", "platnost_od", "platnost_do", "sazba_za_hodinu")
        )

        ctx = dict(
            self.admin_site.each_context(request),
            title=f"Trenér – {u.get_full_name() or u.username}",
            trener=u,
            total_hours=f"{total_hours:.2f} h",
            total_due=f"{total_due:.0f} Kč",
            total_paid=f"{paid:.0f} Kč",
            balance=f"{balance:.0f} Kč",
            pay_url=reverse("admin:core_trenerplatba_add") + f"?user={u.id}&amount={balance}",
            platby_rows=platby_rows,
            platby_total=f"{paid:.0f} Kč",
            rows=rows,
            rate_today_amount=rate_today_amount,
            rate_today_date=rate_today_date,
            rate_form_initial_date=rate_form_initial_date,
            sazby=sazby,
            summary_url=reverse("admin:core_treneri_summary"),
            dfrom=dfrom, dto=dto,
            active_menu="treneri",
        )
        return TemplateResponse(request, "admin/core/trening/trener_detail.html", ctx)


# -----------------------------
#  PLATBY HRÁČŮ (OPRAVENO)
# -----------------------------
class OnlyPaymentsFilter(admin.SimpleListFilter):
    title = "Typ"
    parameter_name = "typ"

    def lookups(self, request, model_admin):
        return [
            (Transakce.Typ.PLATBA, Transakce.Typ.PLATBA.label),
            (Transakce.Typ.VRATKA, Transakce.Typ.VRATKA.label),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val in (Transakce.Typ.PLATBA, Transakce.Typ.VRATKA):
            return queryset.filter(typ=val)
        return queryset


@admin.register(Transakce)
class TransakceAdmin(admin.ModelAdmin):
    # --- 1. HLAVNÍ POHLED: HISTORIE TRANSAKCÍ ---
    list_display = ("datum_display", "hrac_link", "castka_display", "typ_display", "poznamka", "akce_smazat")
    list_filter = (OnlyPaymentsFilter, "vytvoreno", "hrac")
    search_fields = ("hrac__jmeno", "popis")
    actions = ["delete_selected"]
    list_per_page = 50
    
    change_list_template = "admin/core/transakce/change_list.html"
    
    fields = ('hrac', 'typ', 'castka', 'popis', 'vytvoreno')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).select_related("hrac")

    # --- SLOUPCE PRO HISTORII ---
    @admin.display(description="Datum", ordering="vytvoreno")
    def datum_display(self, obj):
        if not obj.vytvoreno: return "-"
        dt = dj_tz.localtime(obj.vytvoreno) if dj_tz.is_aware(obj.vytvoreno) else obj.vytvoreno
        return format_html(
            '<span style="white-space:nowrap;">{}</span> <span style="color:#888; font-size:0.9em">{}</span>',
            dt.strftime("%d. %B %Y"), dt.strftime("%H:%M")
        )

    @admin.display(description="Hráč", ordering="hrac__jmeno")
    def hrac_link(self, obj):
        if not obj.hrac: return "-"
        url = reverse("admin:core_hrac_change", args=[obj.hrac.id])
        return format_html('<a href="{}" style="font-weight:600;">{}</a>', url, obj.hrac.jmeno)

    @admin.display(description="Částka", ordering="castka")
    def castka_display(self, obj):
        color = "green" if obj.castka >= 0 else "red"
        sign = "+" if obj.castka > 0 else ""
        
        # --- ZDE BYLA CHYBA, TOTO JE OPRAVA ---
        # Číslo naformátujeme předem v Pythonu, ne uvnitř HTML stringu
        formatted_val = f"{obj.castka:,.0f}"
        
        return format_html(
            '<span style="color:{}; font-weight:bold;">{} {} Kč</span>',
            color, sign, formatted_val
        )

    @admin.display(description="Typ", ordering="typ")
    def typ_display(self, obj):
        return obj.get_typ_display()

    @admin.display(description="Poznámka")
    def poznamka(self, obj):
        return obj.popis or ""

    @admin.display(description="Akce")
    def akce_smazat(self, obj):
        url = reverse("admin:core_transakce_delete", args=[obj.id])
        return format_html('<a class="deletelink" href="{}"></a>', url)


# --- 2. DRUHÝ POHLED: PŘEHLED ZŮSTATKŮ ---
    def prehled_zustatku_view(self, request):
        rows = []
        for h in Hrac.objects.all():
            last_pay = (
                Transakce.objects.filter(hrac=h, typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA])
                .order_by("-vytvoreno")
                .values_list("vytvoreno", flat=True)
                .first()
            )

            charges_qs = Transakce.objects.filter(hrac=h, typ=Transakce.Typ.NAUCTOVANO)
            if last_pay:
                charges_qs = charges_qs.filter(vytvoreno__gt=last_pay)
            charges = charges_qs.aggregate(s=Sum("castka"))["s"] or Decimal("0")

            mins_qs = Dochazka.objects.filter(hrac=h, prisel=True, transakce_nauc__isnull=False)
            if last_pay:
                mins_qs = mins_qs.filter(transakce_nauc__vytvoreno__gt=last_pay)
            total_min = mins_qs.aggregate(s=Sum("trening__delka_minut"))["s"] or 0
            hodiny = (Decimal(total_min) / Decimal(60)).quantize(Decimal("0.01"))

            # URL detailu hráče (pro jméno)
            detail_url = reverse("admin:core_hrac_change", args=[h.id])

            # URL pro přidání platby
            payment_url = reverse("admin:core_transakce_add") + f"?hrac={h.id}"
            
            # === ZMĚNA: Používáme jen class="button" bez inline stylů ===
            # Tím se aktivuje váš globální CSS styl (oranžová, border, font)
            akce_btn = format_html(
                '<a class="button" href="{}">Zadat platbu</a>', 
                payment_url
            )

            rows.append({
                "hrac_html": format_html('<a href="{}">{}</a>', detail_url, h.jmeno),
                "kredit": f"{h.kredit:.0f} Kč",
                "nauctovano": f"{charges:.0f} Kč",
                "hodiny": f"{hodiny:.2f} h",
                "akce_html": akce_btn, 
            })

        context = {
            **self.admin_site.each_context(request),
            "title": "Přehled zůstatků",
            "summary_rows": rows,
            "summary_title": "Stav kreditů hráčů",
            "col_head_nauctovano": "Naúčtováno od posl. platby",
            "col_head_hodiny": "Hodiny od posl. platby",
            "history_url": reverse("admin:core_transakce_changelist"),
        }
        return TemplateResponse(request, "admin/core/transakce/prehled_plateb.html", context)

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            path("prehled-zustatku/", self.admin_site.admin_view(self.prehled_zustatku_view), name="core_transakce_prehled"),
        ]
        return my_urls + urls

    def get_form(self, request, obj=None, **kwargs):
        Form = super().get_form(request, obj, **kwargs)
        if obj is None and "typ" in Form.base_fields:
            Form.base_fields["typ"].choices = [
                (Transakce.Typ.PLATBA, Transakce.Typ.PLATBA.label),
                (Transakce.Typ.VRATKA, Transakce.Typ.VRATKA.label),
            ]
        return Form

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        hrac_id = request.GET.get("hrac")
        if hrac_id:
            initial["hrac"] = hrac_id
        return initial


# -----------------------------
#  Ostatní modely (beze změny)
# -----------------------------
@admin.register(TrenerProfil)
class TrenerProfilAdmin(admin.ModelAdmin):
    list_display = ("uzivatel", "sazba_za_hodinu")
    search_fields = ("user__username", "user__first_name", "user__last_name")

    def uzivatel(self, obj):
        return obj.user.get_full_name() or obj.user.username
    uzivatel.short_description = "Trenér"


@admin.register(TrenerSazba)
class TrenerSazbaAdmin(admin.ModelAdmin):
    list_display = ("uzivatel", "platnost_od", "platnost_do", "sazba_za_hodinu")
    list_filter = ("user",)
    date_hierarchy = "platnost_od"
    search_fields = ("user__username", "user__first_name", "user__last_name")

    def uzivatel(self, obj):
        return obj.user.get_full_name() or obj.user.username
    uzivatel.short_description = "Trenér"


@admin.register(TrenerPlatba)
class TrenerPlatbaAdmin(admin.ModelAdmin):
    list_display = ("vytvoreno", "uzivatel", "castka", "poznamka")
    list_filter = ("user", "vytvoreno") # Přidáno filtrování podle data
    search_fields = ("user__username", "user__first_name", "user__last_name", "poznamka")
    
    # Tento řádek byl přidán pro zobrazení a pořadí polí ve formuláři
    fields = ('user', 'castka', 'poznamka', 'vytvoreno')

    def uzivatel(self, obj):
        return obj.user.get_full_name() or obj.user.username
    uzivatel.short_description = "Trenér"

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        uid = request.GET.get("user")
        if uid:
            initial["user"] = uid
        amt = request.GET.get("amount")
        if amt:
            try:
                initial["castka"] = Decimal(str(amt).replace(",", "."))
            except Exception:
                pass
        return initial


@admin.register(Vyuctovani)
class VyuctovaniAdmin(admin.ModelAdmin):
    
    # === TOTO JE TEN NOVÝ KÓD ===
    def has_add_permission(self, request):
        # Tento řádek zakáže tlačítko "Přidat vyúčtování"
        return False
    date_hierarchy = "created_at"
    ordering = ("-period_to",)
    list_filter = ("hrac", "reason", "created_at")
    search_fields = ("hrac__jmeno",)
    list_per_page = 50

    list_display = (
        "col_obdobi",
        "hrac",
        "col_nauctovano",
        "col_platby",
        "col_k_uhrade",
        "col_kredit",
        "col_kredit_po_uhrade",
    )

    def _kc(self, value: Decimal) -> str:
        value = Decimal(value or 0).quantize(Decimal("0.01"))
        return f"{value:.0f} Kč"

    def col_obdobi(self, obj):
        def _fmt(dt):
            if not dt:
                return "—"
            if dj_tz.is_aware(dt):
                dt = dj_tz.localtime(dt)
            return dt.strftime("%d.%m.%Y %H:%M")
        return f"{_fmt(obj.period_from)} → {_fmt(obj.period_to)}"
    col_obdobi.short_description = "Období"

    def _fallback_charges(self, obj):
        return obj.nacitano_v_obdobi

    def _fallback_payments(self, obj):
        return obj.platby_v_obdobi

    def _fallback_credit_end(self, obj):
        return obj.kredit_na_konci

    def col_nauctovano(self, obj):
        val = obj.charges_total or 0
        if val == 0 and obj.amount_due == 0 and obj.payments_total == 0:
            val = self._fallback_charges(obj)
        return self._kc(val)
    col_nauctovano.short_description = "Naúčtováno"

    def col_platby(self, obj):
        val = obj.payments_total or 0
        if val == 0 and obj.amount_due == 0 and obj.charges_total == 0:
            val = self._fallback_payments(obj)
        return self._kc(val)
    col_platby.short_description = "Platby/vratky"

    def col_k_uhrade(self, obj):
        if obj.amount_due is None or (obj.amount_due == 0 and obj.charges_total == 0 and obj.payments_total == 0):
            val = (self._fallback_charges(obj) - self._fallback_payments(obj))
        else:
            val = obj.amount_due
        return self._kc(val)
    col_k_uhrade.short_description = "K úhradě"

    def col_kredit(self, obj):
        val = obj.credit_end or 0
        if val == 0 and obj.amount_due == 0 and obj.charges_total == 0 and obj.payments_total == 0:
            val = self._fallback_credit_end(obj)
        return self._kc(val)
    col_kredit.short_description = "Kredit"

    def col_kredit_po_uhrade(self, obj):
        val = (Decimal(obj.credit_end or 0) + Decimal(obj.amount_due or 0))
        return self._kc(val)
    col_kredit_po_uhrade.short_description = "Kredit po úhradě"


# -----------------------------
#  ADMIN DASHBOARD (/admin/)
# -----------------------------
def _month_range(today):
    start = today.replace(day=1)
    end = today
    return start, end


def core_app_dashboard_view(request):
    """Vylepšená app-index stránka pro /admin/core/ – rychlé akce, KPI, dnešní tréninky, poslední platby a top dlužníci."""
    today = dj_tz.localdate()
    now = dj_tz.now()

    m_from, m_to = _month_range(today)

    tqs_month = Trening.objects.filter(datum__date__gte=m_from, datum__date__lte=m_to)
    total_min_month = tqs_month.aggregate(s=Sum("delka_minut"))["s"] or 0
    hours_month = (Decimal(total_min_month) / Decimal(60)).quantize(Decimal("0.01"))

    nac_month = Transakce.objects.filter(
        vytvoreno__date__gte=m_from, vytvoreno__date__lte=m_to,
        typ=Transakce.Typ.NAUCTOVANO,
    ).aggregate(s=Sum("castka"))["s"] or Decimal("0")

    pays_month = Transakce.objects.filter(
        vytvoreno__date__gte=m_from, vytvoreno__date__lte=m_to,
        typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
    ).aggregate(s=Sum("castka"))["s"] or Decimal("0")

    players_count = Hrac.objects.count()
    trainings_today = Trening.objects.filter(datum__date=today).count()

    upcoming = (
        Trening.objects
        .filter(datum__gte=now, datum__lte=(now + timedelta(days=1)))
        .select_related("trener")
        .prefetch_related("dochazky__hrac")
        .order_by("datum")
    )
    upcoming_rows = []
    for t in upcoming[:10]:
        dt = dj_tz.localtime(t.datum) if dj_tz.is_aware(t.datum) else t.datum
        hraci = ", ".join(d.hrac.jmeno for d in t.dochazky.select_related("hrac").filter(prisel=True)) or "—"
        upcoming_rows.append({
            "when": dt.strftime("%d.%m.%Y %H:%M"),
            "format": t.get_format_display(),
            "kurt": t.get_kurt_display(),
            "trener": (t.trener.get_full_name() or t.trener.username),
            "hraci": hraci,
            "url": reverse("admin:core_trening_change", args=[t.id]),
        })

    posledni_platby = [
        {
            "when": (dj_tz.localtime(p.vytvoreno) if dj_tz.is_aware(p.vytvoreno) else p.vytvoreno).strftime("%d.%m.%Y %H:%M"),
            "hrac": p.hrac.jmeno,
            "castka": f"{Decimal(p.castka):.0f} Kč",
            "url": reverse("admin:core_transakce_change", args=[p.id]),
        }
        for p in (Transakce.objects
                  .filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA])
                  .select_related("hrac")
                  .order_by("-vytvoreno")[:8])
    ]

    # === ZMĚNA #3: PŘEJMENOVÁNÍ ANOTACE V CORE DASHBOARD ===
    debt_qs = (
        Hrac.objects
        .annotate(
            _kredit_sort=Sum( # Přejmenováno z 'credit'
                Case(
                    When(transakce__typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA], then=F("transakce__castka")),
                    When(transakce__typ=Transakce.Typ.NAUCTOVANO, then=-F("transakce__castka")),
                    default=Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
        )
        .filter(_kredit_sort__lt=0) # Přejmenováno
        .order_by("_kredit_sort")[:8] # Přejmenováno
    )
    debtors = [{
        "name": h.jmeno,
        "kredit": f"{(h._kredit_sort or 0):.0f} Kč", # Přejmenováno
        "url": reverse("admin:core_hrac_change", args=[h.id]),
    } for h in debt_qs]
    # === KONEC ZMĚNY #3 ===

    ctx = dict(
        admin.site.each_context(request),
        title="Core – přehled",
        kpis={
            "players": f"{players_count}",
            "trainings_today": f"{trainings_today}",
            "hours_month": f"{hours_month:.2f} h",
            "nauctovano_month": f"{Decimal(nac_month):.0f} Kč",
            "platby_month": f"{Decimal(pays_month):.0f} Kč",
        },
        quick={
            "add_training": reverse("admin:core_trening_add"),
            "add_payment": reverse("admin:core_transakce_add"),
            "add_player": reverse("admin:core_hrac_add"),
            "pricelist": reverse("admin:core_cenik_changelist"),
        },
        upcoming=upcoming_rows,
        posledni_platby=posledni_platby,
        debtors=debtors,
    )
    return TemplateResponse(request, "admin/core/app_dashboard.html", ctx)


# ✅ PATCH: KOMPLETNĚ PŘEPRACOVANÁ FUNKCE PRO ANALYTIKU
def admin_analytika_view(request):
    """Samostatná stránka pro KPI statistiky, 6M grafy a detailní tabulky."""
    today = dj_tz.localdate()
    
    # --- 1. Výpočty pro KPI boxy (aktuální měsíc) ---
    m_from_current, m_to_current = _month_range(today)
    
    tqs_current = Trening.objects.filter(datum__date__gte=m_from_current, datum__date__lte=m_to_current)
    total_min_current = tqs_current.aggregate(s=Sum("delka_minut"))["s"] or 0
    hours_current = (Decimal(total_min_current) / Decimal(60)).quantize(Decimal("0.01"))

    nac_current = Transakce.objects.filter(
        vytvoreno__date__gte=m_from_current, vytvoreno__date__lte=m_to_current,
        typ=Transakce.Typ.NAUCTOVANO,
    ).aggregate(s=Sum("castka"))["s"] or Decimal("0")

    pays_current = Transakce.objects.filter(
        vytvoreno__date__gte=m_from_current, vytvoreno__date__lte=m_to_current,
        typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
    ).aggregate(s=Sum("castka"))["s"] or Decimal("0")

    trener_due_total_current = Decimal("0.00")
    trener_ids_current = list(tqs_current.values_list("trener_id", flat=True).distinct())
    for uid in trener_ids_current:
        # Přeskočíme, pokud je ID None (např. u smazaného trenéra)
        if uid is None:
            continue
        try:
            u = User.objects.get(pk=uid)
        except User.DoesNotExist:
            continue
            
        my_tr = tqs_current.filter(trener_id=uid)
        due = Decimal("0.00")
        for tr in my_tr:
            rate = sazba_trenera_k_datu(u, tr.datum)
            h = (Decimal(tr.delka_minut) / Decimal(60))
            due += (h * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        paid = Decimal(
            TrenerPlatba.objects.filter(
                user=u,
                vytvoreno__date__gte=m_from_current, vytvoreno__date__lte=m_to_current
            ).aggregate(s=Sum("castka"))["s"] or 0
        )
        balance = (due - paid).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        trener_due_total_current += balance

    # --- 2. Výpočty pro celkové statistiky (dluhy/přebytky) ---
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

    # --- 3. Výpočty pro detailní tabulky (Dlužníci a Trenéři) ---
    trener_rows = []
    for uid in trener_ids_current:
        if uid is None:
            continue
        try:
            u = User.objects.get(pk=uid)
        except User.DoesNotExist:
            continue

        # Znovu vypočítáme balance...
        my_tr = tqs_current.filter(trener_id=uid)
        due = Decimal("0.00")
        for tr in my_tr:
            rate = sazba_trenera_k_datu(u, tr.datum)
            h = (Decimal(tr.delka_minut) / Decimal(60))
            due += (h * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        paid = Decimal(
            TrenerPlatba.objects.filter(
                user=u,
                vytvoreno__date__gte=m_from_current, vytvoreno__date__lte=m_to_current
            ).aggregate(s=Sum("castka"))["s"] or 0
        )
        balance = (due - paid).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        trener_rows.append({
            "name": u.get_full_name() or u.username,
            "balance": f"{balance:.0f} Kč",
            "url": reverse("admin:core_treneri_detail", args=[u.id]),
        })
    trener_rows.sort(key=lambda r: int(r["balance"].split()[0]), reverse=True)

    debtors_qs = hraci_s_kreditem.filter(_kredit_calculated__lt=0).order_by("_kredit_calculated")
    debtors = [{
        "name": h.jmeno,
        "kredit": f"{(h._kredit_calculated or 0):.0f} Kč",
        "url": reverse("admin:core_hrac_change", args=[h.id]),
    } for h in debtors_qs]

    
    # --- 4. OPRAVENÁ LOGIKA PRO 6M GRAF ---
    monthly_chart_data = []
    czech_months = {
        1: 'Led', 2: 'Úno', 3: 'Bře', 4: 'Dub', 5: 'Kvě', 6: 'Čer',
        7: 'Čvc', 8: 'Srp', 9: 'Zář', 10: 'Říj', 11: 'Lis', 12: 'Pro'
    }
    
    # Začneme aktuálním dnem
    current_day_for_loop = today 

    for i in range(6): # 6 měsíců zpětně
        # 1. Najdi první den v měsíci
        month_start = current_day_for_loop.replace(day=1)
        
        # 2. Najdi poslední den v měsíci
        if month_start.month == 12:
            next_month_start = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            next_month_start = month_start.replace(month=month_start.month + 1, day=1)
        month_end = next_month_start - timedelta(days=1)

        label = f"{czech_months[month_start.month]} '{month_start.strftime('%y')}"

        # Hodiny (z tréninků) - POZOR: datum tréninku je `datum`
        month_trainings = Trening.objects.filter(datum__date__gte=month_start, datum__date__lte=month_end)
        month_total_min = month_trainings.aggregate(s=Sum("delka_minut"))["s"] or 0
        month_hours = (Decimal(month_total_min) / Decimal(60)).quantize(Decimal("0.01"))

        # Naúčtováno (z transakcí) - POZOR: datum transakce je `vytvoreno`
        month_charged = Transakce.objects.filter(
            vytvoreno__date__gte=month_start, vytvoreno__date__lte=month_end,
            typ=Transakce.Typ.NAUCTOVANO,
        ).aggregate(s=Sum("castka"))["s"] or Decimal("0")

        # Platby (z transakcí) - POZOR: datum transakce je `vytvoreno`
        month_paid = Transakce.objects.filter(
            vytvoreno__date__gte=month_start, vytvoreno__date__lte=month_end,
            typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
        ).aggregate(s=Sum("castka"))["s"] or Decimal("0")

        monthly_chart_data.append({
            "label": label,
            "hours": float(month_hours),
            "charged": float(month_charged),
            "paid": float(month_paid),
        })

        # 3. Posuň se na předchozí měsíc pro další iteraci
        current_day_for_loop = month_start - timedelta(days=1) 
    
    monthly_chart_data.reverse() # Seřadíme od nejstaršího po nejnovější
    # --- KONEC OPRAVENÉ LOGIKY PRO GRAF ---

    # --- 5. Finální kontext pro šablonu ---
    ctx = dict(
        admin.site.each_context(request),
        title="Analytika",
        kpis={
            "hours": f"{hours_current:.2f} h",
            "nauctovano": f"{Decimal(nac_current):.0f} Kč",
            "platby": f"{Decimal(pays_current):.0f} Kč",
            "k_vyplaceni": f"{trener_due_total_current:.0f} Kč",
            "total_debt": f"{total_debt:.0f} Kč",
            "total_surplus": f"{total_surplus:.0f} Kč",
            "total_balance": f"{total_balance:.0f} Kč",
        },
        treneri=trener_rows,
        debtors=debtors,
        
        # Předání dat pro 6M graf do šablony
        monthly_chart_data=json.dumps(monthly_chart_data)
    )
    return TemplateResponse(request, "admin/analytika.html", ctx)


# ✅ PATCH: UPRAVENÁ FUNKCE PRO PŮVODNÍ DASHBOARD /admin/
def admin_dashboard_view(request):
    """Hlavní dashboard - nyní zobrazuje POUZE seznamy (poslední platby, dlužníci atd.)."""
    
    # --- Většina logiky pro KPI byla odstraněna ---
    
    # 1. Logika pro "K vyplacení trenérům" (TOP 5)
    # Musíme ji zde nechat, protože ji seznam používá
    today = dj_tz.localdate()
    m_from, m_to = _month_range(today)
    tqs = Trening.objects.filter(datum__date__gte=m_from, datum__date__lte=m_to)

    trener_rows = []
    trener_ids = list(tqs.values_list("trener_id", flat=True).distinct())
    for uid in trener_ids:
        u = User.objects.get(pk=uid)
        my_tr = tqs.filter(trener_id=uid)
        due = Decimal("0.00")
        for tr in my_tr:
            rate = sazba_trenera_k_datu(u, tr.datum)
            h = (Decimal(tr.delka_minut) / Decimal(60))
            due += (h * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        paid = Decimal(
            TrenerPlatba.objects.filter(
                user=u,
                vytvoreno__date__gte=m_from, vytvoreno__date__lte=m_to
            ).aggregate(s=Sum("castka"))["s"] or 0
        )
        balance = (due - paid).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        trener_rows.append({
            "name": u.get_full_name() or u.username,
            "balance": f"{balance:.0f} Kč",
            "url": reverse("admin:core_treneri_detail", args=[u.id]),
        })
    trener_rows.sort(key=lambda r: int(r["balance"].split()[0]), reverse=True)
    trener_rows = trener_rows[:5] # <-- Zde zůstává TOP 5


    # 2. Logika pro "Top dlužníci"
    # Musíme ji zde nechat, protože ji seznam používá
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

    # ✅ PATCH: Omezení na TOP 8 dlužníků (původně chybělo omezení)
    debtors_qs = hraci_s_kreditem.filter(_kredit_calculated__lt=0).order_by("_kredit_calculated")[:8]
    debtors = [{
        "name": h.jmeno,
        "kredit": f"{(h._kredit_calculated or 0):.0f} Kč",
        "url": reverse("admin:core_hrac_change", args=[h.id]),
    } for h in debtors_qs]

    # 3. Logika pro "Poslední platby"
    posledni_platby = [
        {
            "when": (dj_tz.localtime(p.vytvoreno) if dj_tz.is_aware(p.vytvoreno) else p.vytvoreno).strftime("%d.%m.%Y %H:%M"),
            "hrac": p.hrac.jmeno,
            "castka": f"{Decimal(p.castka):.0f} Kč",
            "url": reverse("admin:core_transakce_change", args=[p.id]),
        }
        for p in Transakce.objects.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).select_related("hrac").order_by("-vytvoreno")[:5]
    ]

    # 4. Logika pro "Poslední tréninky"
    posledni_treninky = []
    for t in Trening.objects.select_related("trener").order_by("-datum")[:5]:
        dt = dj_tz.localtime(t.datum) if dj_tz.is_aware(t.datum) else t.datum
        posledni_treninky.append({
            "when": dt.strftime("%d.%m.%Y %H:%M"),
            "trener": (t.trener.get_full_name() or t.trener.username),
            "format": t.get_format_display(),
            "url": reverse("admin:core_trening_change", args=[t.id]),
        })

    # 5. Kontext pro šablonu (už bez 'kpis')
    ctx = dict(
        admin.site.each_context(request),
        title="Přehled",
        # KPI DICTIONARY JE PRYČ
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
    # Vykreslíme upravenou šablonu (která už neobsahuje KPI boxy)
    return TemplateResponse(request, "admin/dashboard.html", ctx)


# -----------------------------
#  Vlastní TOP-LEVEL admin URL pro „Trenéři“ (beze změny)
# -----------------------------
def _treneri_urls_for_site(site):
    """Vrátí URL patterns /admin/core/treneri/... pro daný AdminSite."""
    from .models import Trening  # jistota, že je import uvnitř

    def wrap(view):
        return site.admin_view(view)

    def summary_view(request, *args, **kwargs):
        ma = site._registry[Trening]
        return ma.treneri_summary_view(request)

    def detail_view(request, user_id, *args, **kwargs):
        ma = site._registry[Trening]
        return ma.trener_detail_view(request, user_id=user_id)

    return [
        path("core/treneri/", wrap(summary_view), name="core_treneri_summary"),
        path("core/treneri/<int:user_id>/", wrap(detail_view), name="core_treneri_detail"),
    ]


# -----------------------------
#  Sjednocený patch admin.get_urls (dashboard + trenéři)
# -----------------------------
_original_get_urls = admin.site.get_urls


def _new_get_urls():
    urls = _original_get_urls()
    extra = [
        path("", admin.site.admin_view(admin_dashboard_view), name="index"),
        path("core/", admin.site.admin_view(core_app_dashboard_view), name="core_app_dashboard"),
        
        # ✅ PATCH: PŘIDÁNÍ NOVÉ URL PRO ANALYTIKU
        path("analytika/", admin.site.admin_view(admin_analytika_view), name="analytika"),
    ]
    try:
        extra += _treneri_urls_for_site(admin.site)
    except Exception:
        pass
    return extra + urls


admin.site.get_urls = _new_get_urls

# Branding adminu
admin.site.site_header = "Tenis systém Čimice"
admin.site.site_title = "Tenis systém"
admin.site.index_title = "Přehled"