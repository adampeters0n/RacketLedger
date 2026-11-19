"""Hrac admin."""
from decimal import Decimal, InvalidOperation
from datetime import datetime, time
import logging
import string

from django.conf import settings
from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Q, Sum, Case, When, F, Value, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone as dj_tz
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from ..admin_utils import czech_order_expr
from ..forms import HracInfoForm
from ..models import Hrac, Transakce
from ..roles import can_access_hraci, can_access_rodiny, can_view_hrac_kredit, can_view_finance
from .role_gate import RoleGateMixin

logger = logging.getLogger(__name__)

# První písmeno příjmení (nebo jména) – včetně českých diakritik pod A–Z
_LETTER_STARTS = {
    "A": ("A", "Á", "Ä", "a", "á", "ä"),
    "B": ("B", "b"),
    "C": ("C", "Č", "c", "č"),
    "D": ("D", "Ď", "d", "ď"),
    "E": ("E", "É", "Ě", "Ë", "e", "é", "ě", "ë"),
    "F": ("F", "f"),
    "G": ("G", "g"),
    "H": ("H", "h"),
    "I": ("I", "Í", "i", "í"),
    "J": ("J", "j"),
    "K": ("K", "k"),
    "L": ("L", "l"),
    "M": ("M", "m"),
    "N": ("N", "Ň", "n", "ň"),
    "O": ("O", "Ó", "Ö", "o", "ó", "ö"),
    "P": ("P", "p"),
    "Q": ("Q", "q"),
    "R": ("R", "Ř", "r", "ř"),
    "S": ("S", "Š", "s", "š"),
    "T": ("T", "Ť", "t", "ť"),
    "U": ("U", "Ú", "Ů", "Ü", "u", "ú", "ů", "ü"),
    "V": ("V", "v"),
    "W": ("W", "w"),
    "X": ("X", "x"),
    "Y": ("Y", "Ý", "y", "ý"),
    "Z": ("Z", "Ž", "z", "ž"),
}


class HracPismenoListFilter(admin.SimpleListFilter):
    """Filtr jmen podle počátečního písmene (příjmení, jinak jméno) – chip jako jinde."""

    title = _("Písmeno")
    parameter_name = "letter"

    def lookups(self, request, model_admin):
        return [(ch, ch) for ch in string.ascii_uppercase]

    def queryset(self, request, queryset):
        letter = (self.value() or "").strip().upper()
        if letter not in _LETTER_STARTS:
            return queryset
        starts = _LETTER_STARTS[letter]
        by_prijmeni = Q()
        by_jmeno = Q()
        for ch in starts:
            by_prijmeni |= Q(prijmeni__startswith=ch)
            by_jmeno |= Q(jmeno__startswith=ch)
        # Stejná logika jako jmeno_display: řadí se podle příjmení; bez příjmení → jméno
        return queryset.filter(
            by_prijmeni | (Q(prijmeni="") & by_jmeno)
        )


class HracStavListFilter(admin.SimpleListFilter):
    """Výchozí = Aktivní; dále Neaktivní a Vše."""

    title = _("Stav")
    parameter_name = "stav"

    def lookups(self, request, model_admin):
        return [
            ("neaktivni", _("Neaktivní")),
            ("vse", _("Vše")),
        ]

    def choices(self, changelist):
        # Primárně „Aktivní“ (místo Django „Vše“), ať chip ukáže správný label.
        yield {
            "selected": self.value() is None,
            "query_string": changelist.get_query_string(remove=[self.parameter_name]),
            "display": _("Aktivní"),
        }
        for lookup, title in self.lookup_choices:
            yield {
                "selected": self.value() == str(lookup),
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": title,
            }

    def queryset(self, request, queryset):
        value = self.value()
        if value in {"neaktivni", "skryti"}:
            return queryset.filter(aktivni=False)
        if value in {"vse", "vsichni"}:
            return queryset
        # None / výchozí = Aktivní
        return queryset.filter(aktivni=True)


@admin.register(Hrac)
class HracAdmin(RoleGateMixin, admin.ModelAdmin):
    role_check = staticmethod(can_access_hraci)
    form = HracInfoForm
    list_display = (
        "jmeno_display",
        "email",
        "kredit_display",
        "rodina_link",
    )
    list_display_links = ("jmeno_display",)
    list_filter = (HracStavListFilter, HracPismenoListFilter)
    search_fields = ("jmeno", "prijmeni", "email")
    fields = (
        "jmeno",
        "prijmeni",
        "email",
        "telefon",
        "rok_narozeni",
        "uroven",
        "pohlavi",
        "aktivni",
        "rodina",
    )
    
    actions = [
        "akce_skryt_hrace",
        "akce_obnovit_hrace",
        "akce_vygenerovat_vyuctovani",
        "akce_pridat_platbu",
    ]

    change_form_template = "admin/core/hrac/change_form.html"
    change_list_template = "admin/core/hrac/change_list.html"
    delete_confirmation_template = "admin/core/hrac/delete_confirmation.html"

    # Všichni hráči na jedné stránce (rychlost drží anotace kreditu + select_related)
    list_per_page = 10_000
    list_max_show_all = 10_000
    list_per_page_locked = True
    # Pole OK pro admin.E033; české řazení (SQLite/Postgres) doplní get_ordering()
    ordering = ("prijmeni", "jmeno", "id")

    def get_list_display(self, request):
        cols = ["jmeno_display", "email"]
        if can_access_rodiny(request.user):
            cols.append("rodina_link")
        if can_view_hrac_kredit(request.user):
            cols.insert(2, "kredit_display")
        return cols

    def get_sortable_by(self, request):
        if can_view_hrac_kredit(request.user):
            return ("jmeno_display", "kredit_display")
        return ("jmeno_display",)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if "delete_selected" in actions:
            # Původní hromadné smazání by kaskádou smazalo platby/docházku.
            del actions["delete_selected"]
        if not can_view_finance(request.user):
            for key in ("akce_vygenerovat_vyuctovani", "akce_pridat_platbu"):
                actions.pop(key, None)
        return actions

    def get_ordering(self, request):
        """Příjmení/jméno podle české abecedy (Č, Ř, Š, Ž, Ch…)."""
        ordering = list(super().get_ordering(request) or [])
        if not ordering:
            ordering = ["prijmeni", "jmeno", "id"]
        mapped = []
        for item in ordering:
            if not isinstance(item, str):
                mapped.append(item)
                continue
            descending = item.startswith("-")
            name = item[1:] if descending else item
            if name in {"prijmeni", "jmeno"}:
                mapped.append(czech_order_expr(name, descending=descending))
            else:
                mapped.append(item)
        return mapped

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        # Autocomplete při výběru hráče do tréninku: jen aktivní
        if "/autocomplete/" in request.path:
            queryset = queryset.filter(aktivni=True)
        return queryset, use_distinct

    @admin.display(description=_("Jméno"), ordering="prijmeni")
    def jmeno_display(self, obj):
        return " ".join(p for p in (obj.prijmeni.strip(), obj.jmeno.strip()) if p) or "—"

    def get_queryset(self, request):
        """Kredit v SQL (bez N+1) + rodina přes select_related."""
        dec = DecimalField(max_digits=12, decimal_places=2)
        queryset = super().get_queryset(request).select_related("rodina")
        queryset = queryset.annotate(
            _kredit_sort=Coalesce(
                Sum(
                    Case(
                        When(
                            transakce__typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA],
                            then=F("transakce__castka"),
                        ),
                        When(
                            transakce__typ=Transakce.Typ.NAUCTOVANO,
                            then=-F("transakce__castka"),
                        ),
                        default=Value(0),
                        output_field=dec,
                    )
                ),
                Value(0, output_field=dec),
            )
        )
        return queryset

    def get_deleted_objects(self, objs, request):
        """Bez kaskády – mazání = skrytí (aktivni=False), data zůstanou."""
        objs = list(objs)
        deleted_objects = [str(o) for o in objs]
        model_count = {str(self.opts.verbose_name_plural): len(objs)}
        return deleted_objects, model_count, set(), []

    def delete_model(self, request, obj):
        obj.aktivni = False
        obj.save(update_fields=["aktivni"])

    def delete_queryset(self, request, queryset):
        queryset.update(aktivni=False)

    def response_delete(self, request, obj_display, obj_id):
        self.message_user(
            request,
            _("Hráč „%(name)s“ byl skryt ze seznamu. Tréninky a platby zůstaly zachované.")
            % {"name": obj_display},
            messages.SUCCESS,
        )
        return redirect("admin:core_hrac_changelist")

    @admin.action(description=_("Skrýt vybrané hráče (nevymazat data)"))
    def akce_skryt_hrace(self, request, queryset):
        updated = queryset.filter(aktivni=True).update(aktivni=False)
        self.message_user(
            request,
            _("Skryto hráčů: %(n)s. Data tréninků a plateb zůstala zachovaná.")
            % {"n": updated},
            messages.SUCCESS,
        )

    @admin.action(description=_("Obnovit skryté hráče do seznamu"))
    def akce_obnovit_hrace(self, request, queryset):
        updated = queryset.filter(aktivni=False).update(aktivni=True)
        self.message_user(
            request,
            _("Obnoveno hráčů: %(n)s.") % {"n": updated},
            messages.SUCCESS,
        )

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
            path(
                "<int:object_id>/prehled-treninku/",
                self.admin_site.admin_view(self.prehled_treninku_view),
                name="core_hrac_prehled_treninku",
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
                self.message_user(request, "Informace uloženy.", level=messages.SUCCESS)
                return redirect("admin:core_hrac_change", object_id)
        else:
            form = HracInfoForm(instance=hrac)
        ctx = dict(
            self.admin_site.each_context(request),
            title=f"Změna informací – {hrac.cele_jmeno}",
            opts=self.model._meta,
            original=hrac,
            form=form,
        )
        return TemplateResponse(request, "admin/core/hrac/info_form.html", ctx)

    def vyuctovat_view(self, request, object_id, *args, **kwargs):
        """POST endpoint pro tlačítko 'Vygenerovat vyúčtování teď'."""
        hrac = self.get_object(request, object_id)
        if not hrac:
            self.message_user(request, "Hráč neexistuje.", level=messages.ERROR)
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

        # Prázdné období i částka → aktuální dluh + rozpis od poslední platby / prvního tréninku
        if override_amount is None and vfrom is None and vto is None:
            override_amount = max(Decimal("0.00"), -hrac.kredit)
            vfrom = hrac.zacatek_obdobi_od_posledni_platby()

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

        self.message_user(
            request,
            f"Vyúčtování vytvořeno. K úhradě: {vyuct.amount_due:.0f} Kč. "
            f"E-mail: {'odeslán' if hrac.email else 'není vyplněn'}",
            level=messages.SUCCESS,
        )
        return redirect("admin:core_hrac_change", object_id)

    def prehled_treninku_view(self, request, object_id, *args, **kwargs):
        """POST: pošle jen přehled kreditu + rozpis tréninků (bez výzvy k platbě)."""
        hrac = self.get_object(request, object_id)
        if not hrac:
            self.message_user(request, "Hráč neexistuje.", level=messages.ERROR)
            return redirect("admin:core_hrac_changelist")

        if request.method != "POST":
            return redirect("admin:core_hrac_change", object_id)

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

        if not hrac.email_vyuctovani:
            self.message_user(
                request,
                _("Hráč nemá e-mail pro vyúčtování — přehled nelze odeslat."),
                level=messages.ERROR,
            )
            return redirect("admin:core_hrac_change", object_id)

        hrac.vygeneruj_vyuctovani(
            duvod="prehled",
            send_email=True,
            email_variant=email_variant,
            override_period_from=vfrom,
            override_period_to=vto,
            overview_only=True,
        )

        self.message_user(
            request,
            _("Přehled tréninků odeslán na {email} (bez výzvy k platbě).").format(
                email=hrac.email_vyuctovani
            ),
            level=messages.SUCCESS,
        )
        return redirect("admin:core_hrac_change", object_id)

    @admin.display(description=_("Kredit"), ordering="_kredit_sort")
    def kredit_display(self, obj):
        from ..models import SystemNastaveni

        # Preferuj anotaci z get_queryset – žádné 2× aggregate na řádek
        val = getattr(obj, "_kredit_sort", None)
        if val is None:
            val = obj.kredit
        else:
            val = Decimal(val)
        text = f"{val:.0f} Kč"
        if val < 0 and SystemNastaveni.load().zvyraznit_zaporny_kredit:
            return format_html('<span class="kredit-zaporny">{}</span>', text)
        return text

    @admin.display(description=_("Rodina"))
    def rodina_link(self, obj):
        if not obj.rodina_id:
            return "—"
        url = reverse("admin:core_rodina_change", args=[obj.rodina_id])
        # rodina je select_related – bez dalšího SQL
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

        from ..models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        surplus = nast.hromadne_surplus or Decimal("5000.00")
        raw_surplus = (request.POST.get("_bulk_surplus") or "").strip()
        if raw_surplus:
            try:
                surplus = Decimal(raw_surplus.replace(",", "."))
                if surplus < 0:
                    surplus = nast.hromadne_surplus or Decimal("5000.00")
            except (InvalidOperation, ValueError):
                surplus = nast.hromadne_surplus or Decimal("5000.00")

        # Volitelný pevný override (starší klient / ruční částka) — jinak dluh + surplus
        raw_amt = (request.POST.get("_bulk_castka_k_uhrazeni") or "").strip()
        fixed_amount = None
        if raw_amt:
            try:
                fixed_amount = Decimal(raw_amt.replace(",", "."))
                if fixed_amount < 0:
                    fixed_amount = None
            except (InvalidOperation, ValueError):
                fixed_amount = None

        email_variant = request.POST.get("_bulk_email_variant", "1")

        count = 0
        for hrac in queryset:
            amount = (
                fixed_amount
                if fixed_amount is not None
                else hrac.castka_k_uhrade_dluh_plus_surplus(surplus)
            )
            vyuct = hrac.vygeneruj_vyuctovani(
                duvod="manual",
                send_email=True,
                email_variant=email_variant,
                override_amount_due=amount,
                override_period_from=vfrom,
                override_period_to=vto,
            )
            logger.info(
                ">>> HRAC_AKCE_VYUCTOVAT: hrac_id=%s email=%s amount_due=%s vyuct_id=%s",
                hrac.pk, hrac.email, getattr(vyuct, "amount_due", None), getattr(vyuct, "pk", None)
            )
            count += 1
        self.message_user(request, f"Vyúčtování vytvořeno pro {count} hráčů.", level=messages.SUCCESS)
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
            
            self.message_user(request, f"Hromadná platba: Úspěšně přidáno {castka} Kč pro {count} hráčů.", messages.SUCCESS)

        except (ValueError, InvalidOperation) as e:
            self.message_user(request, f"Chyba při zadávání platby: {e}", messages.ERROR)

    akce_pridat_platbu.short_description = _("Zadat platbu vybraným hráčům")

    def _email_variant_context(self) -> dict:
        from ..models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        surplus = nast.hromadne_surplus or Decimal("5000.00")
        return {
            "email_variant_label_1": nast.email_variant_label("1"),
            "email_variant_label_2": nast.email_variant_label("2"),
            "email_variant_label_3": nast.email_variant_label("3"),
            "hromadne_surplus_default": f"{surplus:.0f}",
        }

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self._email_variant_context())
        extra_context["show_hrac_kredit"] = can_view_hrac_kredit(request.user)
        extra_context["show_rodiny"] = can_access_rodiny(request.user)
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
                sum_cena += Decimal(tx.castka or 0)
                skupina = tx.trening.get_format_display()
                # Služby: bez času, hodin a sezóny (cena je paušál)
                if tx.trening.je_sluzba():
                    cas_str = ""
                    hodiny = ""
                    sezona = ""
                else:
                    total_min += (tx.trening.delka_minut or 0)
                    hodiny_decimal = (Decimal(tx.trening.delka_minut) / Decimal(60)).normalize()
                    hodiny = str(hodiny_decimal).replace('.', ',')
                    sezona = "léto" if tx.trening.kurt == "VENEK" else "zima"
                cena = f"{Decimal(tx.castka):.0f}"
                running_credit -= Decimal(tx.castka or 0)
            else:
                sum_paid += Decimal(tx.castka or 0)
                zaplaceno = f"{Decimal(tx.castka):.0f}"
                running_credit += Decimal(tx.castka or 0)

            display_kredit = f"{running_credit:.0f}"
            
            action_link = ""
            if is_charge and tx.trening:
                edit_url = reverse("admin:core_trening_change", args=[tx.trening.id])
                action_link = format_html(
                    '<a href="{}" class="changelink">{}</a>',
                    edit_url,
                    _("Upravit"),
                )
            elif not is_charge:
                edit_url = reverse("admin:core_transakce_change", args=[tx.id])
                action_link = format_html(
                    '<a href="{}" class="changelink">{}</a>',
                    edit_url,
                    _("Upravit"),
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
                "akce": action_link,
                "typ": tx.typ,
            })

        trainings_count = charges_qs.count()
        trainings_hours_decimal = (Decimal(total_min) / Decimal(60)).normalize()
        trainings_hours = str(trainings_hours_decimal).replace('.', ',')
        end_credit = running_credit

        show_finance = can_view_finance(request.user)
        if not show_finance:
            for row in rows:
                if row.get("typ") in (
                    Transakce.Typ.PLATBA,
                    Transakce.Typ.VRATKA,
                ):
                    row["akce"] = ""
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
        extra_context["show_generate_button"] = show_finance
        extra_context["show_hrac_finance"] = show_finance
        extra_context["show_hrac_kredit"] = can_view_hrac_kredit(request.user)
        extra_context["vyuctovani_list_url"] = f"{reverse('admin:core_vyuctovani_changelist')}?hrac__id__exact={object_id}"

        extra_context["player_summary"] = {
            "trainings_count": trainings_count,
            "trainings_sum": f"{sum_cena:.0f} Kč",
            "payments_sum": f"{sum_paid:.0f} Kč",
            "credit": f"{end_credit:.0f} Kč",
            "credit_raw": end_credit,
        }

        return super().change_view(request, object_id, form_url, extra_context=extra_context)
