"""Hrac admin."""
from decimal import Decimal, InvalidOperation
from core.money import format_castka
from datetime import datetime, time
import logging

from django.conf import settings
from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Sum, Case, When, F, Value, DecimalField
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone as dj_tz
from django.utils.html import format_html
from django.utils.translation import gettext as _g
from django.utils.translation import gettext_lazy as _

from ..forms import HracInfoForm
from ..models import Hrac, Transakce

logger = logging.getLogger(__name__)


@admin.register(Hrac)
class HracAdmin(admin.ModelAdmin):
    list_display = ("jmeno_display", "email", "kredit_display", "rodina_link")
    list_display_links = ("jmeno_display",)
    search_fields = ("jmeno", "prijmeni", "email")
    fields = ("jmeno", "prijmeni", "email", "rodina")
    
    actions = ["akce_vygenerovat_vyuctovani", "akce_pridat_platbu"]

    change_form_template = "admin/core/hrac/change_form.html"
    change_list_template = "admin/core/hrac/change_list.html"
    
    list_per_page = 10_000
    list_max_show_all = 10_000

    def get_sortable_by(self, request):
        return ("jmeno_display", "kredit_display")

    @admin.display(description=_("Jméno"), ordering="prijmeni")
    def jmeno_display(self, obj):
        return " ".join(p for p in (obj.prijmeni.strip(), obj.jmeno.strip()) if p) or "—"

    def get_queryset(self, request):
        """Přidá anotaci pro kredit, aby podle ní šlo řadit."""
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(
            _kredit_sort=Sum(
                Case(
                    When(transakce__typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA], then=F("transakce__castka")),
                    When(transakce__typ=Transakce.Typ.NAUCTOVANO, then=-F("transakce__castka")),
                    default=Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
        )
        return queryset

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


    def info_view(self, request, object_id, *args, **kwargs):
        hrac = self.get_object(request, object_id)
        if not hrac:
            return redirect("admin:core_hrac_changelist")
        if request.method == "POST":
            form = HracInfoForm(request.POST, instance=hrac)
            if form.is_valid():
                form.save()
                self.message_user(request, _g("Informace uloženy."), level=messages.SUCCESS)
                return redirect("admin:core_hrac_change", object_id)
        else:
            form = HracInfoForm(instance=hrac)
        ctx = dict(
            self.admin_site.each_context(request),
            title=_g("Změna informací – %(name)s") % {"name": hrac.cele_jmeno},
            opts=self.model._meta,
            original=hrac,
            form=form,
        )
        return TemplateResponse(request, "admin/core/hrac/info_form.html", ctx)

    def vyuctovat_view(self, request, object_id, *args, **kwargs):
        """POST endpoint pro tlačítko 'Vygenerovat vyúčtování teď'."""
        hrac = self.get_object(request, object_id)
        if not hrac:
            self.message_user(request, _g("Hráč neexistuje."), level=messages.ERROR)
            return redirect("admin:core_hrac_changelist")

        if request.method != "POST":
            return redirect("admin:core_hrac_change", object_id)

        raw_amt = (request.POST.get("_castka_k_uhrazeni") or "").strip()
        override_amount = None
        if raw_amt:
            try:
                override_amount = Decimal(raw_amt.replace(",", "."))
                if override_amount < 0:
                    override_amount = None
            except (InvalidOperation, ValueError):
                override_amount = None

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
        email_variant = request.POST.get("_email_variant", "1")

        logger.info(
            ">>> HRAC_VYUCTOVAT: start hrac_id=%s jmeno=%s email=%s override_amount=%s vfrom=%s vto=%s variant=%s",
            hrac.pk, hrac.cele_jmeno, hrac.email, override_amount, vfrom, vto, email_variant
        )

        vyuct = hrac.vygeneruj_vyuctovani(
            duvod="manual",
            send_email=True,
            email_variant=email_variant,
            override_amount_due=override_amount,
            override_period_from=vfrom,
            override_period_to=vto,
        )

        logger.info(
            ">>> HRAC_VYUCTOVAT: hotovo hrac_id=%s amount_due=%s vyuct_id=%s",
            hrac.pk, getattr(vyuct, "amount_due", None), getattr(vyuct, "pk", None)
        )

        email_status = _g("odeslán") if hrac.email else _g("není vyplněn")
        self.message_user(
            request,
            _g("Vyúčtování vytvořeno. K úhradě: %(amount)s. E-mail: %(email)s")
            % {"amount": format_castka(vyuct.amount_due), "email": email_status},
            level=messages.SUCCESS,
        )
        return redirect("admin:core_hrac_change", object_id)

    @admin.display(description=_("Kredit"), ordering="_kredit_sort")
    def kredit_display(self, obj):
        val = obj.kredit
        text = format_castka(val)
        try:
            from ..models import SystemNastaveni

            if SystemNastaveni.load().zvyraznit_zaporny_kredit and val < 0:
                return format_html('<span class="kredit-zaporny">{}</span>', text)
        except Exception:
            pass
        return text

    @admin.display(description=_("Rodina"))
    def rodina_link(self, obj):
        if not obj.rodina_id:
            return "—"
        url = reverse("admin:core_rodina_change", args=[obj.rodina_id])
        nazev = obj.rodina.nazev or f"Rodina #{obj.rodina_id}"
        return format_html('<a href="{}">{}</a>', url, nazev)

    def akce_vygenerovat_vyuctovani(self, request, queryset):
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
        self.message_user(
            request,
            _g("Vyúčtování vytvořeno pro %(count)s hráčů.") % {"count": count},
            level=messages.SUCCESS,
        )
    akce_vygenerovat_vyuctovani.short_description = _("Vygenerovat vyúčtování (poslat e-mail)")
    
    def akce_pridat_platbu(self, request, queryset):
        raw_amount = request.POST.get("_bulk_payment_amount")
        raw_date = request.POST.get("_bulk_payment_date")
        typ = request.POST.get("_bulk_payment_type")
        note = request.POST.get("_bulk_payment_note", "")

        if not raw_amount:
            return

        try:
            castka = Decimal(raw_amount.replace(",", "."))
            
            if raw_date:
                datum_obj = datetime.strptime(raw_date, "%Y-%m-%d")
                now = dj_tz.now()
                datum = datum_obj.replace(hour=now.hour, minute=now.minute, second=now.second)
                
                if settings.USE_TZ:
                    datum = dj_tz.make_aware(datum)
            else:
                datum = dj_tz.now()

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
            
            self.message_user(
                request,
                _g("Hromadná platba: Úspěšně přidáno %(amount)s pro %(count)s hráčů.")
                % {"amount": format_castka(castka), "count": count},
                messages.SUCCESS,
            )

        except (ValueError, InvalidOperation) as e:
            self.message_user(
                request,
                _g("Chyba při zadávání platby: %(error)s") % {"error": e},
                messages.ERROR,
            )

    akce_pridat_platbu.short_description = _("Zadat platbu vybraným hráčům")

    def _email_variant_context(self) -> dict:
        from ..models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        return {
            "email_variant_label_1": nast.email_variant_label("1"),
            "email_variant_label_2": nast.email_variant_label("2"),
        }

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self._email_variant_context())
        return super().changelist_view(request, extra_context=extra_context)

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

                hodiny_decimal = (Decimal(tx.trening.delka_minut) / Decimal(60)).normalize()
                hodiny = str(hodiny_decimal).replace('.', ',')

                skupina = tx.trening.get_format_display()
                sezona = "léto" if (tx.trening.kurt or "").casefold() in {"venku", "venek"} else "zima"
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
                delete_link = format_html(
                    '<a href="{}" class="deletelink">{}</a>', delete_url, _g("Smazat")
                )
            elif not is_charge:
                delete_url = reverse("admin:core_transakce_delete", args=[tx.id])
                delete_link = format_html(
                    '<a href="{}" class="deletelink">{}</a>', delete_url, _g("Smazat")
                )

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
        trainings_hours_decimal = (Decimal(total_min) / Decimal(60)).normalize()
        trainings_hours = str(trainings_hours_decimal).replace('.', ',')
        end_credit = running_credit

        extra_context = extra_context or {}
        extra_context.update(self._email_variant_context())
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
            "trainings_sum": format_castka(sum_cena),
            "payments_sum": format_castka(sum_paid),
            "credit": format_castka(end_credit),
            "credit_raw": end_credit,
        }

        return super().change_view(request, object_id, form_url, extra_context=extra_context)
