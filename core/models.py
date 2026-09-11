import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta, datetime, time, date
import calendar

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from core.utils.email_archive import send_and_append_to_sent
from django.db import models, transaction
from django.db.models import Q, Sum, Max
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.utils import timezone as dj_tz # Ponechávám dj_tz pro zkrácený zápis
from django.utils import timezone           # Ponechávám timezone pro default=timezone.now
from django.utils.html import escape, format_html
from django.utils.translation import gettext_lazy as _
import logging
from .i18n_config import DEFAULT_LANGUAGE, SYSTEM_LANGUAGES
from .system_theme import DEFAULT_THEME, THEME_CHOICES
from .money import DEFAULT_MENA, MENA_CHOICES, format_castka

logger = logging.getLogger(__name__)

_auto_vyuctovani_queued: set[int] = set()
AUTO_VYUCTOVANI_OBDOBI_MESICU = 3


def _datum_pred_mesici(d: date, mesicu: int) -> date:
    month = d.month - mesicu
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _zacatek_obdobi_pro_auto_vyuctovani(mesicu: int = AUTO_VYUCTOVANI_OBDOBI_MESICU) -> datetime:
    """Začátek období pro automatické vyúčtování (N kalendářních měsíců zpět)."""
    d = _datum_pred_mesici(dj_tz.localdate(), mesicu)
    start = datetime.combine(d, time.min)
    if settings.USE_TZ:
        start = dj_tz.make_aware(start, dj_tz.get_current_timezone())
    return start

def _schedule_auto_vyuctovani(hrac_id: int) -> None:
    """Spustí auto vyúčtování až po commitu – max. jednou na hráče v rámci transakce."""
    if hrac_id in _auto_vyuctovani_queued:
        return
    _auto_vyuctovani_queued.add(hrac_id)

    def _run() -> None:
        _auto_vyuctovani_queued.discard(hrac_id)
        hrac = Hrac.objects.filter(pk=hrac_id).first()
        if hrac:
            hrac.spustit_auto_vyuctovani()

    transaction.on_commit(_run)


# =========================
#  Rodina
# =========================
class Rodina(models.Model):
# ... kód Rodina je v pořádku ...
    nazev = models.CharField(
        _("Název rodiny (např. Novákovi)"),
        max_length=120,
        blank=True,
        default="",
    )
    kontakt_email = models.EmailField(blank=True, null=True)
    kontakt_telefon = models.CharField(max_length=40, blank=True, default="")
    poznamka = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = _("Rodina")
        verbose_name_plural = _("Rodiny")
        ordering = ("nazev", "id")   

    def __str__(self):
        return self.nazev or "Rodina"


# =========================
#  Hráč
# =========================
class Hrac(models.Model):
    class RezimVyuctovani(models.TextChoices):
        MESICNE = "MESICNE", _("Měsíčně")
        N_TRENINGU = "N_TRENINGU", _("Po N trénincích")
        CASTKA = "CASTKA", _("Limit kreditu")

    jmeno = models.CharField(_("Jméno"), max_length=120)
    prijmeni = models.CharField(_("Příjmení"), max_length=120, db_index=True, blank=True, default="")
    email = models.EmailField(blank=True, null=True)

    # vazba na rodinu (nové)
    rodina = models.ForeignKey(
        Rodina, on_delete=models.SET_NULL, null=True, blank=True, related_name="clenove"
    )

    # --- nastavení souhrnného vyúčtování ---
    vyuctovani_rezim = models.CharField(
        max_length=16, choices=RezimVyuctovani.choices, default=RezimVyuctovani.MESICNE
    )
    vyuctovani_n = models.PositiveIntegerField(default=10)  # pro režim N_TRENINGU
    vyuctovani_threshold = models.DecimalField(            # pro režim CASTKA
        max_digits=10, decimal_places=2, default=Decimal("5000.00")
    )
    posledni_vyuctovani_at = models.DateTimeField(blank=True, null=True)
    pocet_treninku_od_vyuctovani = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("Hráč")
        verbose_name_plural = _("Hráči")
        ordering = ("prijmeni", "jmeno")

    def __str__(self) -> str:
        return self.cele_jmeno

    @property
    def cele_jmeno(self) -> str:
        return " ".join(p for p in (self.jmeno.strip(), self.prijmeni.strip()) if p)

    # ---- salda/kredit ----
    @property
    def zustatek(self) -> Decimal:
        nacitano = (
            self.transakce.filter(typ=Transakce.Typ.NAUCTOVANO)
            .aggregate(Sum("castka"))["castka__sum"]
            or Decimal("0")
        )
        platby = (
            self.transakce.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA])
            .aggregate(Sum("castka"))["castka__sum"]
            or Decimal("0")
        )
        return (Decimal(nacitano) - Decimal(platby)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def kredit(self) -> Decimal:
        return (-self.zustatek).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def email_vyuctovani(self) -> str | None:
        """E-mail pro vyúčtování – hráč, jinak kontakt rodiny."""
        if self.email:
            return self.email
        if self.rodina_id and self.rodina.kontakt_email:
            return self.rodina.kontakt_email
        return None

    @property
    def odehrane_hodiny(self) -> Decimal:
        celkem_minut = self.dochazky.aggregate(Sum("trening__delka_minut"))[
            "trening__delka_minut__sum"
        ] or 0
        hodiny = Decimal(celkem_minut) / Decimal(60)
        return hodiny.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _qs_transakci_od_posledni_uzaverky(self):
        if self.posledni_vyuctovani_at:
            return self.transakce.filter(vytvoreno__gt=self.posledni_vyuctovani_at)
        return self.transakce.all()

    def nedoplatek_od_posledni_uzaverky(self) -> Decimal:
        qs = self._qs_transakci_od_posledni_uzaverky()
        nacitano = qs.filter(typ=Transakce.Typ.NAUCTOVANO).aggregate(Sum("castka"))["castka__sum"] or Decimal("0")
        platby = qs.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).aggregate(Sum("castka"))["castka__sum"] or Decimal("0")
        return (Decimal(nacitano) - Decimal(platby)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

# --- UZÁVĚRKA / VYÚČTOVÁNÍ ---
    def vygeneruj_vyuctovani(
        self,
        duvod: str = "manual",
        send_email: bool = False,
        email_variant: str = "1",
        override_amount_due: Decimal | None = None,
        override_period_from=None,   # date/datetime/None
        override_period_to=None,     # date/datetime/None
    ):
        """
        Uzávěrka za období.
        """
        def _normalize_dt(x, is_end=False):
            if not x: return None
            if isinstance(x, datetime): dt = x
            else: dt = datetime.combine(x, time.max if is_end else time.min)
            if dj_tz.is_naive(dt) and settings.USE_TZ:
                dt = dj_tz.make_aware(dt, dj_tz.get_current_timezone())
            return dt

        now = dj_tz.now()
        period_from = _normalize_dt(override_period_from) if override_period_from else self.posledni_vyuctovani_at
        period_to = _normalize_dt(override_period_to, is_end=True) if override_period_to else now

        if not override_period_to:
            scope_qs = self.transakce.all()
            if period_from:
                scope_qs = scope_qs.filter(vytvoreno__gt=period_from)
            latest_vytvoreno = scope_qs.order_by("-vytvoreno").values_list("vytvoreno", flat=True).first()
            if latest_vytvoreno and latest_vytvoreno > period_to:
                period_to = latest_vytvoreno

        # Transakce v období
        tx_qs = self.transakce.filter(vytvoreno__lte=period_to)
        if period_from: tx_qs = tx_qs.filter(vytvoreno__gt=period_from)

        charges = tx_qs.filter(typ=Transakce.Typ.NAUCTOVANO).aggregate(Sum("castka"))["castka__sum"] or Decimal("0")
        pays = tx_qs.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).aggregate(Sum("castka"))["castka__sum"] or Decimal("0")
        computed_amount = (Decimal(charges) - Decimal(pays)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        # --- Logika pro částku (0 Kč vs zadaná částka) ---
        if override_amount_due is not None:
            amount_due = Decimal(override_amount_due).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif duvod == "manual":
            amount_due = Decimal("0.00") # Manuálně bez částky = 0 Kč
        else:
            amount_due = computed_amount

        # Statistiky
        sessions = self.dochazky.filter(prisel=True, trening__datum__lte=period_to, **({"trening__datum__gt": period_from} if period_from else {})).count()
        credit_end = self.kredit
        delta_credit = (Decimal(pays) - Decimal(charges)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        credit_start = (credit_end - delta_credit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        snapshot_pk = self.transakce.aggregate(m=Max("pk"))["m"] or 0

        vyuct = Vyuctovani.objects.create(
            hrac=self, period_from=period_from, period_to=period_to, sessions_count=sessions,
            charges_total=Decimal(charges).quantize(Decimal("0.01")), payments_total=Decimal(pays).quantize(Decimal("0.01")),
            amount_due=amount_due, credit_start=credit_start, credit_end=credit_end, reason=duvod,
            snapshot_transakce_pk=snapshot_pk,
        )

        update_uzaverka = duvod != "manual"
        if update_uzaverka:
            self.posledni_vyuctovani_at = now
            self.pocet_treninku_od_vyuctovani = 0
            self.save(update_fields=["posledni_vyuctovani_at", "pocet_treninku_od_vyuctovani"])

        # ===== E-mail =====
        billing_email = self.email_vyuctovani
        if send_email and billing_email:
            # Data pro tabulku
            charges_qs = tx_qs.filter(typ=Transakce.Typ.NAUCTOVANO).select_related("trening").order_by("trening__datum")
            pays_qs = tx_qs.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).order_by("vytvoreno")

            start_credit = Decimal("0.00")
            if period_from:
                bc = self.transakce.filter(typ=Transakce.Typ.NAUCTOVANO, vytvoreno__lt=period_from).aggregate(s=Sum("castka"))["s"] or 0
                bp = self.transakce.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA], vytvoreno__lt=period_from).aggregate(s=Sum("castka"))["s"] or 0
                start_credit = (Decimal(bp) - Decimal(bc)).quantize(Decimal("0.01"))

            events = []
            for tx in charges_qs:
                dt = tx.trening.datum if tx.trening else tx.vytvoreno
                if dj_tz.is_aware(dt): dt = dj_tz.localtime(dt)
                events.append(("CHARGE", dt, tx))
            for tx in pays_qs:
                dt = tx.vytvoreno
                if dj_tz.is_aware(dt): dt = dj_tz.localtime(dt)
                events.append(("PAY", dt, tx))
            events.sort(key=lambda t: t[1])

            # --- Datum "DO" pro text e-mailu ---
            if override_period_to:
                display_period_to = period_to
            else:
                # Pokud není zadáno ručně, vezmeme datum poslední akce (aby to vypadalo lépe)
                display_period_to = events[-1][1] if events else period_to

            running_credit = start_credit
            sum_cena = Decimal("0")
            sum_paid = Decimal("0")
            rows_html_parts = []
            lines = []

            for typ, dt, tx in events:
                # Přeskočit položky mimo datum (pro jistotu)
                if period_from and dt < period_from:
                    amt = Decimal(tx.castka or 0)
                    if typ == "CHARGE": running_credit -= amt
                    else: running_credit += amt
                    continue
                if period_to and dt > period_to:
                    amt = Decimal(tx.castka or 0)
                    if typ == "CHARGE": running_credit -= amt
                    else: running_credit += amt
                    continue

                datum_str = dt.strftime("%d.%m.%Y")
                cas_str = dt.strftime("%H:%M")
                skupina = "—"
                cena = zaplaceno = ""

                if typ == "CHARGE":
                    if tx.trening: skupina = tx.trening.get_format_display() 
                    amt = Decimal(tx.castka or 0)
                    sum_cena += amt
                    running_credit -= amt
                    cena = format_castka(amt)
                else:
                    amt = Decimal(tx.castka or 0)
                    sum_paid += amt
                    running_credit += amt
                    zaplaceno = format_castka(amt)

                kredit_str = format_castka(running_credit)
                lines.append(f"{datum_str}\t{cas_str}\t{skupina}\t{cena}\t{zaplaceno}\t{kredit_str}")

                # Zarovnání na střed (align='center')
                rows_html_parts.append(
                    "<tr>"
                    f"<td>{datum_str}</td>"
                    f"<td>{cas_str}</td>"
                    f"<td>{skupina}</td>"
                    f"<td align='center'>{cena or '—'}</td>"
                    f"<td align='center'>{zaplaceno or '—'}</td>"
                    f"<td align='center'><strong>{kredit_str}</strong></td>"
                    "</tr>"
                )

            if not rows_html_parts:
                rows_html_parts.append("<tr><td colspan='6' align='center'>—</td></tr>")

            totals_html = (
                "<tr style='background:#f9fafb'>"
                "<td colspan='3' align='right'><strong>Součty</strong></td>"
                f"<td align='center'><strong>{format_castka(sum_cena)}</strong></td>"
                f"<td align='center'><strong>{format_castka(sum_paid)}</strong></td>"
                f"<td align='center'><strong>{format_castka(running_credit)}</strong></td>"
                "</tr>"
            )
            rows_html = "".join(rows_html_parts) + totals_html
            table_txt = "\n".join(lines)

            kredit_po_uhrade = (credit_end + amount_due).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            
            # --- Text Částky ---
            if amount_due == 0:
                amount_display_str = f"{format_castka(0)} (pouze přehled tréninků)"
            else:
                amount_display_str = format_castka(amount_due)

            # --- Číslo účtu ---
            vyuct_nast = VyuctovaniNastaveni.load()
            sys_nast = SystemNastaveni.load()
            if email_variant == "2":
                cislo_uctu_text = vyuct_nast.ucet_varianta_2
                cislo_uctu_html = f"<strong>{escape(vyuct_nast.ucet_varianta_2)}</strong>"
            else:
                cislo_uctu_text = vyuct_nast.ucet_varianta_1
                cislo_uctu_html = f"<strong>{escape(vyuct_nast.ucet_varianta_1)}</strong>"
            vs_popis = (vyuct_nast.variabilni_symbol_popis or "").strip() or "Jméno hráče"

            subject = sys_nast.format_email_subject(
                f"Přehled tréninků a vyúčtování – {self.cele_jmeno}"
            )
            podpis = sys_nast.effective_podpis()
            podpis_html = sys_nast.podpis_html()

            text_body = (
                f"Zasílám přehled tréninků a vyúčtování za období od {period_from.strftime('%d.%m.%Y') if period_from else 'začátku'} do {display_period_to.strftime('%d.%m.%Y')}.\n\n"
                "Níže je přiložen podrobný rozpis všech položek.\n\n"
                "---\n"
                "**Přehled kreditu:**\n\n"
                f"Aktuální kredit (před platbou): {format_castka(credit_end)}\n"
                f"Celková cena tréninků v tomto období: {format_castka(sum_cena)}\n\n"
                "Pro vyrovnání kreditu a jeho navýšení na další období je třeba uhradit:\n\n"
                f"Částka k zaplacení: **{amount_display_str}**\n\n"
                "Platební údaje:\n"
                f"Číslo účtu: **{cislo_uctu_text}**\n"
                f"Variabilní symbol: **{vs_popis}**\n\n"
                f"Po připsání platby bude stav kreditu: {format_castka(kredit_po_uhrade)}\n"
                "---\n\n"
                "Detailní rozpis tréninků:\n\n"
                f"{table_txt}\n\n"
                "Děkuji.\n\n"
                f"{podpis}"
            )

            html_body = f"""
            <div style="font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;line-height:1.6;">
              <p>Zasílám přehled tréninků a vyúčtování za období od 
                 <strong>{period_from.strftime('%d.%m.%Y') if period_from else 'začátku'}</strong>
                 do <strong>{display_period_to.strftime('%d.%m.%Y')}</strong>.
              </p>
              <p>Níže je přiložen podrobný rozpis všech položek.</p>
              
              <hr style="border:none; border-top:1px solid #e5e7eb; margin: 20px 0;">
              
              <h3 style="margin-top: 20px; margin-bottom: 10px;">Přehled kreditu:</h3>
              <div style="font-size: 1.05em; line-height: 1.7;">
                Aktuální kredit (před platbou): <strong>{format_castka(credit_end)}</strong><br>
                Celková cena tréninků v tomto období: <strong>{format_castka(sum_cena)}</strong>
              </div>

              <div style="margin: 20px 0;">
                Pro vyrovnání kreditu a jeho navýšení na další období je třeba uhradit:
              </div>
              
              <div style="background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 20px;">
                <div style="font-size: 1.1em; margin-bottom: 12px;">
                  Částka k zaplacení: <strong style="font-size: 1.3em; color: #111827;">{amount_display_str}</strong>
                </div>
                <div style="line-height: 1.7;">
                  Platební údaje:<br>
                  Číslo účtu: {cislo_uctu_html}<br> Variabilní symbol: <strong>{escape(vs_popis)}</strong> 
                </div>
              </div>
              
              <div style="margin-bottom: 20px;">
                Po připsání platby bude stav kreditu: <strong>{format_castka(kredit_po_uhrade)}</strong>
              </div>

              <hr style="border:none; border-top:1px solid #e5e7eb; margin: 20px 0;">

              <h3 style="margin:16px 0 6px;">Detailní rozpis tréninků:</h3>
              <table cellpadding="6" cellspacing="0" style="border-collapse:collapse;border:1px solid #e5e7eb;width:100%;font-size:0.9em;">
                <thead style="background:#f9fafb;">
                  <tr>
                    <th align="left" style="padding: 8px; border-bottom: 1px solid #e5e7eb;">Datum</th>
                    <th align="left" style="padding: 8px; border-bottom: 1px solid #e5e7eb;">Čas</th>
                    <th align="left" style="padding: 8px; border-bottom: 1px solid #e5e7eb;">Skupina</th>
                    <th align="center" style="padding: 8px; border-bottom: 1px solid #e5e7eb;">Cena</th>
                    <th align="center" style="padding: 8px; border-bottom: 1px solid #e5e7eb;">Zaplaceno</th>
                    <th align="center" style="padding: 8px; border-bottom: 1px solid #e5e7eb;">Kredit</th>
                  </tr>
                </thead>
                <tbody>{rows_html}</tbody>
              </table>

              <p style="margin-top:20px;">Děkuji.</p>
              <p style="margin-top:16px;">{podpis_html}</p>
            </div>
            """

            ok_send, ok_archive = send_and_append_to_sent(
                subject=subject,
                body=text_body,
                html_body=html_body,
                to=billing_email,
            )

            logger.info(
                ">>> VYUCTOVANI: email_send=%s, saved_to_sent=%s, hrac=%s, email=%s, subject=%s",
                ok_send, ok_archive, self.cele_jmeno, billing_email, subject
            )

        return vyuct

    def _max_kredit_od_vyuctovani(self, vyuct: "Vyuctovani") -> Decimal:
        """Nejvyšší dosažený kredit od uzávěrky (pro detekci obnovy po platbě)."""
        running = Decimal(vyuct.credit_end or 0)
        peak = running
        anchor_pk = vyuct.snapshot_transakce_pk or 0
        if not anchor_pk:
            anchor_pk = (
                self.transakce.filter(vytvoreno__lte=vyuct.created_at).aggregate(m=Max("pk"))["m"] or 0
            )
        for tx in self.transakce.filter(pk__gt=anchor_pk).order_by("pk"):
            amt = Decimal(tx.castka or 0)
            if tx.typ == Transakce.Typ.NAUCTOVANO:
                running -= amt
            elif tx.typ in (Transakce.Typ.PLATBA, Transakce.Typ.VRATKA):
                running += amt
            if running > peak:
                peak = running
        return peak

    def _kredit_se_obnovil_nad_limit_po_castka_vyuctovani(self, limit: Decimal) -> bool:
        """True, pokud lze znovu vyúčtovat po dosažení limitu kreditu (např. po platbě nad limit)."""
        threshold = -limit
        last = (
            self.vyuctovani.filter(reason=self.RezimVyuctovani.CASTKA)
            .order_by("-created_at")
            .first()
        )
        if not last:
            return True
        if (last.credit_end or Decimal("0")) > threshold:
            return True
        return self._max_kredit_od_vyuctovani(last) > threshold

    def mozna_uzavrit_podle_rezimu(self) -> bool:
        """Zda hráč splnil podmínky pro automatickou uzávěrku podle globálního nastavení."""
        nast = VyuctovaniNastaveni.load()
        rezim = nast.auto_rezim

        if rezim == VyuctovaniNastaveni.AutoRezim.MANUAL:
            return False

        if rezim == self.RezimVyuctovani.N_TRENINGU:
            return self.pocet_treninku_od_vyuctovani >= max(1, nast.auto_pocet_treninku)

        if rezim == self.RezimVyuctovani.CASTKA:
            limit = nast.auto_limit
            if limit <= 0:
                return False
            if self.kredit > -limit:
                return False
            return self._kredit_se_obnovil_nad_limit_po_castka_vyuctovani(limit)

        if rezim == self.RezimVyuctovani.MESICNE:
            return self._mesicni_uzavirka_pripravena(nast)

        return False

    def _uz_mesicne_vyuctovano_v_tomto_mesici(self) -> bool:
        if not self.posledni_vyuctovani_at:
            return False
        last = dj_tz.localtime(self.posledni_vyuctovani_at)
        today = dj_tz.localdate()
        return last.year == today.year and last.month == today.month

    def _ma_aktivitu_od_posledni_uzaverky(self) -> bool:
        if self._qs_transakci_od_posledni_uzaverky().exists():
            return True
        qs = self.dochazky.filter(prisel=True)
        if self.posledni_vyuctovani_at:
            qs = qs.filter(trening__datum__gt=self.posledni_vyuctovani_at)
        return qs.exists()

    def prepocitat_stav_uzaverky(self) -> None:
        """Přepočítá cache uzávěrky podle existujících záznamů Vyuctovani (po smazání apod.)."""
        last = self.vyuctovani.order_by("-created_at").first()
        nova_posledni = last.created_at if last else None

        qs = self.dochazky.filter(prisel=True, transakce_nauc__isnull=False)
        if nova_posledni:
            qs = qs.filter(trening__datum__gt=nova_posledni)
        novy_pocet = qs.count()

        if (
            self.posledni_vyuctovani_at != nova_posledni
            or self.pocet_treninku_od_vyuctovani != novy_pocet
        ):
            self.posledni_vyuctovani_at = nova_posledni
            self.pocet_treninku_od_vyuctovani = novy_pocet
            self.save(update_fields=["posledni_vyuctovani_at", "pocet_treninku_od_vyuctovani"])

    def _mesicni_uzavirka_pripravena(self, nast: "VyuctovaniNastaveni") -> bool:
        today = dj_tz.localdate()
        if today.day < nast.mesicni_den:
            return False
        if self._uz_mesicne_vyuctovano_v_tomto_mesici():
            return False
        return self._ma_aktivitu_od_posledni_uzaverky()

    def duvod_auto_vyuctovani(self) -> str:
        """Důvod záznamu při automatickém vyúčtování."""
        return VyuctovaniNastaveni.load().auto_rezim

    def spustit_auto_vyuctovani(self):
        """Vytvoří vyúčtování a pošle e-mail, pokud jsou splněny podmínky."""
        with transaction.atomic():
            hrac = Hrac.objects.select_for_update().get(pk=self.pk)
            if not hrac.mozna_uzavrit_podle_rezimu():
                return None
            nast = VyuctovaniNastaveni.load()
            override_amount = None
            if nast.auto_castka_k_uhrade and nast.auto_castka_k_uhrade > 0:
                override_amount = nast.auto_castka_k_uhrade
            return hrac.vygeneruj_vyuctovani(
                duvod=hrac.duvod_auto_vyuctovani(),
                send_email=nast.auto_posilat_email,
                email_variant=nast.email_variant,
                override_amount_due=override_amount,
                override_period_from=_zacatek_obdobi_pro_auto_vyuctovani(),
            )


# =========================
#  Ceník (OPRAVENO S VALIDACÍ)
# =========================
# =========================
#  Formáty ceníku (registr)
# =========================
class CenikFormat(models.Model):
    """Registr formátů – uživatel spravuje název, kód zůstává stabilní."""

    kod = models.CharField("Kód", max_length=15, unique=True)
    nazev = models.CharField("Název formátu", max_length=120, unique=True)
    poradi = models.PositiveSmallIntegerField("Pořadí", default=0)

    # Výchozí mapování kód → název (pro migraci a záložní zobrazení)
    VYCHOZI_KODY = {
        "SOLO_C": "Solo (1 hráč) - Člen",
        "DVOJICE_C": "Dvojice (2 hráči) - Člen",
        "TROJICE_C": "Trojice (3 hráči) - Člen",
        "CTVRICE_C": "Čtveřice (4 hráči) - Člen",
        "PETICE": "Pětice (5 a více hráčů) - Člen",
        "SOLO_NC": "Solo (1 hráč) - Nečlen",
        "DVOJICE_NC": "Dvojice (2 hráči) - Nečlen",
        "TROJICE_NC": "Trojice (3 hráči) - Nečlen",
        "CTVRICE_NC": "Čtveřice (4 hráči) - Nečlen",
        "SOBOTA_TRE": "Trénink - Sobota",
        "KURT_TRE": "Kurt - Rezervace",
        "V_STAND": "Výplet - Standard",
        "V_EXCEL": "Výplet - Express",
        "V_VLAST": "Výplet - Vlastní",
    }
    VYCHOZI_PORADI = {
        "SOLO_C": 10,
        "DVOJICE_C": 20,
        "TROJICE_C": 30,
        "CTVRICE_C": 40,
        "PETICE": 50,
        "SOLO_NC": 60,
        "DVOJICE_NC": 70,
        "TROJICE_NC": 80,
        "CTVRICE_NC": 90,
        "SOBOTA_TRE": 100,
        "KURT_TRE": 110,
        "V_STAND": 120,
        "V_EXCEL": 130,
        "V_VLAST": 140,
    }
    DEFAULT_KOD = "DVOJICE_C"

    class Meta:
        verbose_name = _("Formát ceníku")
        verbose_name_plural = _("Formáty ceníku")
        ordering = ("poradi", "nazev")

    def __str__(self) -> str:
        return self.nazev

    @classmethod
    def nazev_pro(cls, hodnota: str) -> str:
        """Vrátí zobrazovaný název. Po free-text migraci je hodnota už název."""
        if not hodnota:
            return ""
        if hodnota in cls.VYCHOZI_KODY.values():
            return hodnota
        fmt = cls.objects.filter(kod=hodnota).values_list("nazev", flat=True).first()
        if fmt:
            return fmt
        return cls.VYCHOZI_KODY.get(hodnota, hodnota)

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Jen uživatelské záznamy – bez pevných Solo/Dvojice fallbacků."""
        return list(cls.objects.order_by("poradi", "nazev").values_list("kod", "nazev"))

    @classmethod
    def default_kod(cls) -> str:
        first = cls.objects.order_by("poradi", "nazev").values_list("kod", flat=True).first()
        return first or ""

    @classmethod
    def _generuj_kod(cls, nazev: str) -> str:
        ascii_nazev = (
            unicodedata.normalize("NFKD", nazev)
            .encode("ascii", "ignore")
            .decode("ascii")
            .upper()
        )
        base = re.sub(r"[^A-Z0-9]+", "_", ascii_nazev).strip("_")[:10] or "FMT"
        kod = base
        n = 1
        while cls.objects.filter(kod=kod).exists():
            suffix = f"_{n}"
            kod = f"{base[: 15 - len(suffix)]}{suffix}"
            n += 1
        return kod[:15]

    @classmethod
    def pridej(cls, nazev: str) -> "CenikFormat":
        nazev = (nazev or "").strip()
        max_poradi = cls.objects.order_by("-poradi").values_list("poradi", flat=True).first() or 0
        return cls.objects.create(
            kod=cls._generuj_kod(nazev),
            nazev=nazev,
            poradi=max_poradi + 10,
        )

    def je_pouzity(self) -> bool:
        return Cenik.objects.filter(format=self.kod).exists() or Trening.objects.filter(format=self.kod).exists()


class Cenik(models.Model):
    # Legacy konstanty – hodnoty jsou zobrazované názvy (free text)
    class Format:
        SOLO_C = "Solo (1 hráč) - Člen"
        DVOJICE_C = "Dvojice (2 hráči) - Člen"
        TROJICE_C = "Trojice (3 hráči) - Člen"
        CTVRICE_C = "Čtveřice (4 hráči) - Člen"
        PETICE = "Pětice (5 a více hráčů) - Člen"
        SOLO_NC = "Solo (1 hráč) - Nečlen"
        DVOJICE_NC = "Dvojice (2 hráči) - Nečlen"
        TROJICE_NC = "Trojice (3 hráči) - Nečlen"
        CTVRICE_NC = "Čtveřice (4 hráči) - Nečlen"
        SOBOTA_TRE = "Trénink - Sobota"
        KURT_TRE = "Kurt - Rezervace"
        VYPLET_STAND = "Výplet - Standard"
        VYPLET_EXCEL = "Výplet - Express"
        VYPLET_VLASTNI = "Výplet - Vlastní"

        choices = tuple((v, v) for v in CenikFormat.VYCHOZI_KODY.values())

    class Kurt:
        """Volný text kurtu; konstanty = běžné názvy (ne DB kódy)."""

        VENEK = "Venku"
        HALA = "Hala"
        SLUZBA = "Služba"
        # Staré kódy (před migrací) – pro porovnání / sezónu
        VENEK_CODE = "VENEK"
        HALA_CODE = "HALA"
        SLUZBA_CODE = "SLUZBA"

        choices = ((VENEK, VENEK), (HALA, HALA), (SLUZBA, SLUZBA))

    format = models.CharField(_("Typ tréninku"), max_length=120)
    sezona = models.CharField(_("Sezóna"), max_length=64, blank=True, default="")
    kurt = models.CharField(_("Kurt"), max_length=64)
    cena_za_hodinu = models.DecimalField(_("Cena za hodinu"), max_digits=8, decimal_places=2)

    platnost_od = models.DateField(_("Platnost od"), default=timezone.now)
    platnost_do = models.DateField(_("Platnost do"), blank=True, null=True)
    v_kalendari = models.BooleanField(
        _("Přidat do kalendáře"),
        default=True,
        help_text=_("Zobrazit typ tréninku v legendě a barvách rozvrhu."),
    )

    def get_format_display(self) -> str:
        return CenikFormat.nazev_pro(self.format)

    def get_kurt_display(self) -> str:
        return self.kurt or ""

    def get_sezona_display(self) -> str:
        return self.sezona or ""

    # --- ZDE BYL PŘIDÁN KÓD ---
    def clean(self):
        """
        Zabrání uložení, pokud se období platnosti pro stejný typ, sezónu a kurt překrývá
        s již existujícím záznamem.
        """
        super().clean()
        self.format = (self.format or "").strip()
        self.sezona = (self.sezona or "").strip()
        self.kurt = (self.kurt or "").strip()
        if not self.format:
            raise ValidationError({"format": _("Zadejte typ tréninku.")})
        if not self.kurt:
            raise ValidationError({"kurt": _("Zadejte kurt.")})

        qs = Cenik.objects.filter(format=self.format, sezona=self.sezona, kurt=self.kurt)
        if self.pk:
            qs = qs.exclude(pk=self.pk)

        overlap_qs = qs.filter(
            Q(platnost_do__gte=self.platnost_od) | Q(platnost_do__isnull=True)
        )
        if self.platnost_do:
            overlap_qs = overlap_qs.filter(platnost_od__lte=self.platnost_do)

        if overlap_qs.exists():
            raise ValidationError(
                f"Období platnosti se překrývá s již existujícím ceníkem pro "
                f"'{self.get_format_display()}' / '{self.get_sezona_display() or '—'}' "
                f"na kurtu '{self.get_kurt_display()}'."
            )

    class Meta:
        verbose_name = _("Ceník")
        verbose_name_plural = _("Ceník")
        indexes = [
            models.Index(
                fields=["format", "sezona", "kurt", "platnost_od", "platnost_do"],
                name="core_cenik_format_sezona_idx",
            )
        ]

    def __str__(self) -> str:
        parts = [self.get_format_display()]
        if self.sezona:
            parts.append(self.sezona)
        parts.append(self.get_kurt_display())
        return f"{' • '.join(parts)} – {format_castka(self.cena_za_hodinu, per_hour=True)}"


# =========================
#  Trénink (lekce) (OPRAVENO)
# =========================
class Trening(models.Model):
    trener = models.ForeignKey(User, on_delete=models.PROTECT)
    datum = models.DateTimeField()
    delka_minut = models.PositiveIntegerField(default=60)

    format = models.CharField(_("Typ tréninku"), max_length=120)
    sezona = models.CharField(_("Sezóna"), max_length=64, blank=True, default="")
    kurt = models.CharField(_("Kurt"), max_length=64)

    poznamka = models.CharField(max_length=240, blank=True)

    hraci = models.ManyToManyField(Hrac, through="Dochazka", related_name="treningy")

    def get_format_display(self) -> str:
        return CenikFormat.nazev_pro(self.format)

    def get_kurt_display(self) -> str:
        return self.kurt or ""

    def get_sezona_display(self) -> str:
        return self.sezona or self.sezona_display

    def __str__(self) -> str:
        return (
            f"{self.datum:%Y-%m-%d %H:%M} • "
            f"{self.get_format_display()} • "
            f"{self.get_kurt_display()} • "
            f"{self.trener.username}"
        )

    class Meta:
        verbose_name = _("Trénink")
        verbose_name_plural = _("Tréninky")

    @property
    def hodiny(self) -> Decimal:
        return (Decimal(self.delka_minut) / Decimal(60)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def sezona_display(self) -> str:
        """Sezóna z pole, nebo odhad z kurtu (legacy)."""
        from django.utils.translation import gettext as _gettext

        if (self.sezona or "").strip():
            return self.sezona.strip()
        kurt = (self.kurt or "").strip().casefold()
        if kurt in {Cenik.Kurt.VENEK.casefold(), Cenik.Kurt.VENEK_CODE.casefold(), "venek"}:
            return _gettext("Léto")
        if kurt in {Cenik.Kurt.HALA.casefold(), Cenik.Kurt.HALA_CODE.casefold()}:
            return _gettext("Zima")
        return _gettext("Celoroční")

    def aktualni_cenik(self) -> "Cenik | None":
        d = self.datum.date()
        base = Cenik.objects.filter(format=self.format, kurt=self.kurt).filter(
            Q(platnost_od__lte=d), Q(platnost_do__gte=d) | Q(platnost_do__isnull=True)
        )
        sezona = (self.sezona or "").strip()
        if sezona:
            qs = base.filter(sezona=sezona).order_by("-platnost_od")
            hit = qs.first()
            if hit:
                return hit
        # Fallback: prázdná sezóna v ceníku (celoroční / legacy)
        return base.filter(sezona="").order_by("-platnost_od").first() or base.order_by("-platnost_od").first()

    def cena_na_hrace(self) -> Decimal:
        pravidlo = self.aktualni_cenik()
        if not pravidlo:
            return Decimal("0.00")
        amount = pravidlo.cena_za_hodinu * self.hodiny
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ==== sazba trenéra dle data ====
    @property
    def sazba_trenera(self) -> Decimal:
        return sazba_trenera_k_datu(self.trener, self.datum)

    @property
    def odmena_trenera(self) -> Decimal:
        return (self.hodiny * self.sazba_trenera).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# =========================
#  Docházka
# =========================
class Dochazka(models.Model):
# ... zbytek je v pořádku ...
    trening = models.ForeignKey(Trening, on_delete=models.CASCADE, related_name="dochazky")
    hrac = models.ForeignKey(Hrac, on_delete=models.CASCADE, related_name="dochazky")
    prisel = models.BooleanField(default=True)  # přišel/nepřišel

    # informace o automatickém naúčtování
    transakce_nauc = models.ForeignKey(
        "Transakce", null=True, blank=True, on_delete=models.SET_NULL, related_name="zdroj_dochazky"
    )
    castka_nauc = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    nauceno_kdy = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("trening", "hrac")
        verbose_name_plural = _("Hráči")

    def __str__(self) -> str:
        return f"{self.hrac.cele_jmeno} @ {self.trening}"


# =========================
#  Pohyby na účtu hráče
# =========================
class Transakce(models.Model):
# ... zbytek je v pořádku ...
    class Typ(models.TextChoices):
        NAUCTOVANO = "NAUCTOVANO", _("Naúčtováno")
        PLATBA = "PLATBA", _("Platba")
        VRATKA = "VRATKA", _("Vrácení/bonifikace")
        UPRAVA = "UPRAVA", _("Úprava")

    hrac = models.ForeignKey(Hrac, related_name="transakce", on_delete=models.CASCADE, verbose_name=_("Hráč"))
    typ = models.CharField(max_length=12, choices=Typ.choices, verbose_name=_("Typ"))
    castka = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("Částka"))
    popis = models.CharField(max_length=240, blank=True, verbose_name=_("Poznámka"))
    trening = models.ForeignKey(Trening, null=True, blank=True, on_delete=models.CASCADE)
    vytvoreno = models.DateTimeField(_("Datum platby"), default=timezone.now)

    class Meta:
        ordering = ["-vytvoreno"]
        verbose_name = _("Platba")
        verbose_name_plural = _("Platby")

    def __str__(self) -> str:
        sign = "+" if self.typ in [self.Typ.PLATBA, self.Typ.VRATKA] else "-"
        return f"{self.hrac.cele_jmeno}: {self.get_typ_display()} {format_castka(self.castka)} ({sign})"


# =========================
#  Souhrnné vyúčtování (log)
# =========================
class Vyuctovani(models.Model):
    class Reason(models.TextChoices):
        MANUAL = "manual", _("Ručně")
        MESICNE = "MESICNE", _("Měsíčně")
        N_TRENINGU = "N_TRENINGU", _("Po N trénincích")
        CASTKA = "CASTKA", _("Limit kreditu")
        AUTO = "AUTO", _("Automaticky (limit kreditu)")
        RODINA = "rodina", _("Rodina")

    hrac = models.ForeignKey(Hrac, on_delete=models.CASCADE, related_name="vyuctovani", verbose_name=_("Hráč"))
    period_from = models.DateTimeField(_("Období od"), null=True, blank=True)
    period_to = models.DateTimeField(_("Období do"))
    sessions_count = models.PositiveIntegerField(_("Počet tréninků"), default=0)

    charges_total = models.DecimalField(_("Naúčtováno"), max_digits=10, decimal_places=2, default=Decimal("0.00"))
    payments_total = models.DecimalField(_("Platby a vratky"), max_digits=10, decimal_places=2, default=Decimal("0.00"))
    amount_due = models.DecimalField(_("K úhradě"), max_digits=10, decimal_places=2)

    credit_start = models.DecimalField(_("Kredit na začátku"), max_digits=10, decimal_places=2, default=Decimal("0.00"))
    credit_end = models.DecimalField(_("Kredit na konci"), max_digits=10, decimal_places=2, default=Decimal("0.00"))

    reason = models.CharField(_("Důvod"), max_length=32, default="manual")
    snapshot_transakce_pk = models.PositiveIntegerField(
        _("Poslední transakce v uzávěrce"),
        default=0,
        help_text=_("Interní ukotvení pro detekci opakovaného vyúčtování."),
    )
    created_at = models.DateTimeField(_("Vytvořeno"), auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Vyúčtování")
        verbose_name_plural = _("Vyúčtování")

    def __str__(self) -> str:
        frm = self.period_from.strftime("%Y-%m-%d %H:%M") if self.period_from else "—"
        return f"Vyúčtování {self.hrac.cele_jmeno} [{frm} → {self.period_to:%Y-%m-%d %H:%M}] = {format_castka(self.amount_due)}"

    # ---- HELPERY / SOUČTY PRO ADMIN ----
    def _qs_in_period(self):
        qs = self.hrac.transakce.filter(vytvoreno__lte=self.period_to)
        if self.period_from:
            qs = qs.filter(vytvoreno__gt=self.period_from)
        return qs

    def _sum_types_in_period(self, types) -> Decimal:
        s = self._qs_in_period().filter(typ__in=types).aggregate(Sum("castka"))["castka__sum"] or Decimal("0")
        return Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def nacitano_v_obdobi(self) -> Decimal:
        return self._sum_types_in_period([Transakce.Typ.NAUCTOVANO])

    @property
    def platby_v_obdobi(self) -> Decimal:
        return self._sum_types_in_period([Transakce.Typ.PLATBA, Transakce.Typ.VRATKA])

    def kredit_k_datu(self, dt) -> Decimal:
        if not dt:
            return Decimal("0.00")
        qs = self.hrac.transakce.filter(vytvoreno__lte=dt)
        nauct = qs.filter(typ=Transakce.Typ.NAUCTOVANO).aggregate(Sum("castka"))["castka__sum"] or Decimal("0")
        plat = qs.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).aggregate(Sum("castka"))["castka__sum"] or Decimal("0")
        return (Decimal(plat) - Decimal(nauct)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def kredit_na_zacatku(self) -> Decimal:
        return self.kredit_k_datu(self.period_from) if self.period_from else Decimal("0.00")

    @property
    def kredit_na_konci(self) -> Decimal:
        return self.kredit_k_datu(self.period_to)


# =========================
#  Nastavení vyúčtování (dnes singleton; po tenantech 1 řádek = 1 klub)
# =========================
class VyuctovaniNastaveni(models.Model):
    """Platební a auto-vyúčtovací politika klubu (per-tenant).

    Patří sem: režim uzávěrky, limity, čísla účtů, názvy variant e-mailu, VS text.
    Nepatří sem: SMTP credentials (platforma), jazyk/vzhled (SystemNastaveni).
    """

    class AutoRezim(models.TextChoices):
        CASTKA = "CASTKA", _("Limit kreditu")
        MESICNE = "MESICNE", _("Měsíčně")
        N_TRENINGU = "N_TRENINGU", _("Dle odehraných tréninků")
        MANUAL = "MANUAL", _("Pouze manuálně")

    class EmailVarianta(models.TextChoices):
        UCET_1 = "1", _("Účet 1")
        UCET_2 = "2", _("Účet 2")

    auto_rezim = models.CharField(
        _("Způsob vyúčtování"),
        max_length=16,
        choices=AutoRezim.choices,
        default=AutoRezim.CASTKA,
    )
    auto_limit = models.DecimalField(
        _("Limit kreditu"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("5000.00"),
        help_text=_("Vyúčtování se vytvoří, když kredit hráče klesne na tuto zápornou částku nebo níže (např. −5000)."),
    )
    auto_castka_k_uhrade = models.DecimalField(
        _("Částka k zaplacení v e-mailu"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("5000.00"),
        help_text=_("Částka zobrazená v e-mailu jako požadavek k úhradě. Ponechte 0 pro automatický výpočet z období."),
    )
    auto_pocet_treninku = models.PositiveIntegerField(
        _("Počet tréninků"),
        default=10,
        help_text=_("Po tolika odehraných trénincích od poslední uzávěrky se vyúčtuje."),
    )
    mesicni_den = models.PositiveSmallIntegerField(
        _("Den v měsíci"),
        default=1,
        help_text=_("Od tohoto dne v měsíci (po dalším tréninku) proběhne měsíční uzávěrka."),
    )
    auto_posilat_email = models.BooleanField(
        _("Posílat e-mail při automatickém vyúčtování"),
        default=True,
    )
    email_variant = models.CharField(
        _("Výchozí varianta e-mailu"),
        max_length=1,
        choices=EmailVarianta.choices,
        default=EmailVarianta.UCET_1,
    )
    ucet_nazev_1 = models.CharField(
        _("Název účtu – varianta 1"),
        max_length=64,
        default="Účet 1",
        help_text=_("Zobrazí se ve výběru varianty e-mailu (např. hlavní účet klubu)."),
    )
    ucet_nazev_2 = models.CharField(
        _("Název účtu – varianta 2"),
        max_length=64,
        default="Účet 2",
    )
    ucet_varianta_1 = models.CharField(
        _("Číslo účtu – varianta 1"),
        max_length=32,
        blank=True,
        default="",
    )
    ucet_varianta_2 = models.CharField(
        _("Číslo účtu – varianta 2"),
        max_length=32,
        blank=True,
        default="",
    )
    variabilni_symbol_popis = models.CharField(
        _("Variabilní symbol (text v e-mailu)"),
        max_length=120,
        default="Jméno hráče",
        help_text=_("Text zobrazený u VS v e-mailu vyúčtování."),
    )

    class Meta:
        verbose_name = _("Nastavení vyúčtování")
        verbose_name_plural = _("Nastavení vyúčtování")

    def __str__(self) -> str:
        return str(_("Nastavení vyúčtování"))

    def save(self, *args, **kwargs):
        # Singleton do zavedení tenantů; potom: unikátní řádek per tenant.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "VyuctovaniNastaveni":
        """Vrátí nastavení klubu. Po tenantech: load(tenant=…)."""
        defaults = {
            "auto_rezim": cls.AutoRezim.CASTKA,
            "auto_limit": Decimal(str(getattr(settings, "VYUCTOVANI_AUTO_LIMIT", "5000"))),
            "auto_castka_k_uhrade": Decimal(str(getattr(settings, "VYUCTOVANI_AUTO_LIMIT", "5000"))),
            "email_variant": str(getattr(settings, "VYUCTOVANI_EMAIL_VARIANT", "1")),
        }
        obj, _ = cls.objects.get_or_create(pk=1, defaults=defaults)
        return obj

    def email_variant_label(self, variant: str) -> str:
        if str(variant) == "2":
            return (self.ucet_nazev_2 or "").strip() or str(_("Účet 2"))
        return (self.ucet_nazev_1 or "").strip() or str(_("Účet 1"))

    def email_variant_choices(self) -> list[tuple[str, str]]:
        return [
            ("1", self.email_variant_label("1")),
            ("2", self.email_variant_label("2")),
        ]

    def get_email_variant_display(self) -> str:
        return self.email_variant_label(self.email_variant)

    def popis_rezimu(self) -> str:
        if self.auto_rezim == self.AutoRezim.MANUAL:
            return _("Vyúčtování pouze ručně z profilu hráče")
        if self.auto_rezim == self.AutoRezim.CASTKA:
            return _("Při kreditu −%(limit)s nebo níže") % {"limit": format_castka(abs(self.auto_limit))}
        if self.auto_rezim == self.AutoRezim.N_TRENINGU:
            return _("Po %(count)s odehraných trénincích") % {"count": self.auto_pocet_treninku}
        if self.auto_rezim == self.AutoRezim.MESICNE:
            return _("Každý měsíc od %(day)s. dne (po tréninku)") % {"day": self.mesicni_den}
        return "—"

    def spustit_mesicni_vyuctovani_vsem(self) -> int:
        """Hromadné měsíční vyúčtování – vhodné pro cron v den uzávěrky."""
        if self.auto_rezim != self.AutoRezim.MESICNE:
            return 0
        if dj_tz.localdate().day < self.mesicni_den:
            return 0
        count = 0
        for hrac in Hrac.objects.all():
            if hrac.spustit_auto_vyuctovani():
                count += 1
        return count


# =========================
#  Nastavení systému (dnes singleton; po tenantech 1 řádek = 1 klub)
# =========================
class SystemNastaveni(models.Model):
    """Branding a provozní preference klubu (per-tenant).

    Patří sem: název, logo, kontakt, jazyk, vzhled, e-mail From/prefix/podpis,
    výchozí trénink/rozvrh, práh dluhu, stránkování.
    Nepatří sem: čísla účtů (VyuctovaniNastaveni), SMTP heslo (env / platforma).
    """

    DELKA_MINUT_CHOICES = (
        (30, "30 min"),
        (45, "45 min"),
        (60, "1 h"),
        (90, "1,5 h"),
        (120, "2 h"),
        (150, "2,5 h"),
        (180, "3 h"),
    )

    class RozvrhZobrazeni(models.TextChoices):
        TYDEN = "week", _("Týden")
        DEN = "day", _("Den")

    nazev_klubu = models.CharField(
        _("Název klubu / systému"),
        max_length=120,
        default="TenisSystém",
        help_text=_("Zobrazí se v hlavičce a v e-mailech."),
    )
    kontakt_email = models.EmailField(
        _("Kontaktní e-mail"),
        max_length=254,
        blank=True,
        default="",
        help_text=_("Zobrazí se na veřejné stránce a v patičce e-mailů."),
    )
    kontakt_telefon = models.CharField(
        _("Telefon"),
        max_length=32,
        blank=True,
        default="",
    )
    kontakt_adresa = models.CharField(
        _("Adresa klubu"),
        max_length=200,
        blank=True,
        default="",
    )
    slogan = models.CharField(
        _("Slogan"),
        max_length=160,
        blank=True,
        default="",
        help_text=_("Krátký text na veřejné stránce."),
    )
    logo = models.ImageField(
        _("Logo klubu"),
        upload_to="club/",
        blank=True,
        null=True,
        help_text=_("PNG nebo JPG."),
    )
    favicon = models.ImageField(
        _("Favicon"),
        upload_to="club/",
        blank=True,
        null=True,
    )
    email_odesilatel = models.CharField(
        _("Odesílatel e-mailů"),
        max_length=120,
        blank=True,
        default="",
        help_text=_("Formát: Jméno <email@domena.cz>"),
    )
    email_predmet_prefix = models.CharField(
        _("Prefix předmětu e-mailu"),
        max_length=60,
        blank=True,
        default="[TenisSystém] ",
    )
    email_podpis = models.TextField(
        _("Podpis e-mailů"),
        blank=True,
        default="S pozdravem,\n\nTenisSystém",
    )
    sezona_venek_od = models.PositiveSmallIntegerField(
        _("Venkovní sezóna od (měsíc)"),
        default=4,
    )
    sezona_venek_do = models.PositiveSmallIntegerField(
        _("Venkovní sezóna do (měsíc)"),
        default=10,
    )
    sezona_automaticky_kurt = models.BooleanField(
        _("Automaticky volit kurt dle sezóny"),
        default=True,
    )
    prah_dluhu_dashboard = models.DecimalField(
        _("Práh dluhu na dashboardu"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=_("0 = všichni se záporným kreditem, −1000 = dluh od 1000 jednotek měny."),
    )
    mena = models.CharField(
        _("Měna"),
        max_length=8,
        choices=MENA_CHOICES,
        default=DEFAULT_MENA,
        help_text=_("Zobrazí se u všech cen a částek v systému (Kč, €, $ …)."),
    )
    zvyraznit_zaporny_kredit = models.BooleanField(
        _("Zvýraznit záporný kredit v seznamu hráčů"),
        default=True,
    )
    radku_na_stranku = models.PositiveSmallIntegerField(
        _("Řádků na stránku v tabulkách"),
        default=50,
        choices=((25, "25"), (50, "50"), (100, "100")),
    )
    vlastni_barvy = models.BooleanField(
        _("Vlastní barvy (místo palety)"),
        default=False,
    )
    vychozi_delka_minut = models.PositiveSmallIntegerField(
        _("Výchozí délka tréninku"),
        default=60,
        choices=DELKA_MINUT_CHOICES,
    )
    vychozi_kurt = models.CharField(
        _("Výchozí kurt"),
        max_length=64,
        default="",
        blank=True,
    )
    vychozi_sezona = models.CharField(
        _("Výchozí sezóna"),
        max_length=64,
        default="",
        blank=True,
    )
    rozvrh_od_hodina = models.PositiveSmallIntegerField(
        _("Rozvrh od (hodina)"),
        default=6,
    )
    rozvrh_do_hodina = models.PositiveSmallIntegerField(
        _("Rozvrh do (hodina)"),
        default=22,
    )
    vychozi_zobrazeni_rozvrhu = models.CharField(
        _("Výchozí zobrazení rozvrhu"),
        max_length=8,
        choices=RozvrhZobrazeni.choices,
        default=RozvrhZobrazeni.TYDEN,
    )
    barevna_varianta = models.CharField(
        _("Barevná varianta"),
        max_length=16,
        choices=THEME_CHOICES,
        default=DEFAULT_THEME,
        help_text=_("Paleta barev ve stylu Excel – mění celý vzhled systému."),
    )
    tmavy_rezim = models.BooleanField(
        _("Tmavý režim"),
        default=False,
        help_text=_("Tmavé pozadí, světlý text a upravené barvy tabulek."),
    )
    barva_brand = models.CharField("Primární akcent", max_length=7, blank=True, default="")
    barva_brand_600 = models.CharField("Akcent tlačítek", max_length=7, blank=True, default="")
    barva_brand_100 = models.CharField("Světlé pozadí akcentu", max_length=7, blank=True, default="")
    barva_pozadi = models.CharField("Pozadí stránky", max_length=7, blank=True, default="")
    barva_plochy = models.CharField("Karty a formuláře", max_length=7, blank=True, default="")
    barva_text = models.CharField("Text", max_length=7, blank=True, default="")
    barva_text_silny = models.CharField("Tučný text", max_length=7, blank=True, default="")
    barva_tabulka_hlava = models.CharField("Hlavička tabulek", max_length=7, blank=True, default="")
    barva_tabulka_radek = models.CharField("Střídavý řádek tabulky", max_length=7, blank=True, default="")
    barva_tabulka_hover = models.CharField("Hover řádku tabulky", max_length=7, blank=True, default="")
    barva_ohraniceni = models.CharField("Ohraničení", max_length=7, blank=True, default="")
    vychozi_jazyk = models.CharField(
        _("Výchozí jazyk systému"),
        max_length=10,
        choices=SYSTEM_LANGUAGES,
        default=DEFAULT_LANGUAGE,
        help_text=_("Jazyk rozhraní pro celý systém."),
    )

    class Meta:
        verbose_name = _("Nastavení systému")
        verbose_name_plural = _("Nastavení systému")

    def __str__(self) -> str:
        return "Nastavení systému"

    def save(self, *args, **kwargs):
        sync_colors = kwargs.pop("sync_colors", True)
        if sync_colors:
            from .system_theme import MODEL_FIELD_MAP, preset_colors

            colors = preset_colors(self.barevna_varianta or DEFAULT_THEME, dark=self.tmavy_rezim)
            for key, field in MODEL_FIELD_MAP.items():
                setattr(self, field, colors[key])
        # Singleton do zavedení tenantů; potom: unikátní řádek per tenant.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "SystemNastaveni":
        """Vrátí nastavení klubu. Po tenantech: load(tenant=…)."""
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "nazev_klubu": "TenisSystém",
                "barevna_varianta": DEFAULT_THEME,
                "tmavy_rezim": False,
            },
        )
        return obj

    def effective_colors(self) -> dict[str, str]:
        from .system_theme import resolve_theme_colors

        return resolve_theme_colors(self)

    def schedule_hours(self) -> list[int]:
        """Hodiny zobrazené v týdenním rozvrhu (včetně konce)."""
        start = max(0, min(int(self.rozvrh_od_hodina), 23))
        end = max(start + 1, min(int(self.rozvrh_do_hodina), 23))
        return list(range(start, end + 1))

    @property
    def schedule_hour_count(self) -> int:
        return len(self.schedule_hours())

    @classmethod
    def training_defaults(cls, for_date=None) -> dict:
        """Výchozí délka a sezóna pro nové tréninky."""
        try:
            nast = cls.load()
            return {
                "delka_minut": int(nast.vychozi_delka_minut or 60),
                "sezona": (nast.vychozi_sezona or "").strip(),
                "kurt": (nast.vychozi_kurt or "").strip(),
            }
        except Exception:
            return {"delka_minut": 60, "sezona": "", "kurt": ""}

    def kurt_pro_datum(self, datum) -> str:
        """Zpětná kompatibilita – dříve kurt, nyní sezóna z nastavení."""
        return (self.vychozi_sezona or self.vychozi_kurt or "").strip()

    def from_email_parts(self) -> tuple[str, str]:
        """Rozdělí uloženého odesílatele na jméno a adresu."""
        raw = (self.email_odesilatel or "").strip()
        if not raw:
            return "", ""
        m = re.match(r"^(.+?)\s*<([^>]+)>$", raw)
        if m:
            return m.group(1).strip().strip('"'), m.group(2).strip()
        if "@" in raw:
            return "", raw
        return raw, ""

    @classmethod
    def compose_from_email(cls, jmeno: str, adresa: str) -> str:
        jmeno = (jmeno or "").strip()
        adresa = (adresa or "").strip()
        if jmeno and adresa:
            return f"{jmeno} <{adresa}>"
        return adresa or jmeno

    def subject_tag_display(self) -> str:
        """Text pro formulář – bez hranatých závorek."""
        val = (self.email_predmet_prefix or "").strip()
        if val.startswith("[") and "]" in val:
            return val[1 : val.index("]")].strip()
        return val.rstrip()

    @classmethod
    def compose_subject_prefix(cls, oznaceni: str) -> str:
        oznaceni = (oznaceni or "").strip()
        if not oznaceni:
            return ""
        if oznaceni.startswith("[") and oznaceni.endswith("]"):
            oznaceni = oznaceni[1:-1].strip()
        return f"[{oznaceni}] "

    def effective_from_email(self) -> str:
        from django.conf import settings

        val = (self.email_odesilatel or "").strip()
        return val or getattr(settings, "DEFAULT_FROM_EMAIL", "")

    def effective_subject_prefix(self) -> str:
        val = (self.email_predmet_prefix or "").strip()
        if not val:
            return ""
        if not val.startswith("["):
            val = self.compose_subject_prefix(val)
        return val

    def effective_podpis(self) -> str:
        val = (self.email_podpis or "").strip()
        return val or "S pozdravem,"

    def format_email_subject(self, subject: str) -> str:
        prefix = self.effective_subject_prefix()
        if not prefix or subject.startswith(prefix):
            return subject
        if not prefix.endswith(" "):
            prefix = prefix + " "
        return f"{prefix}{subject}"

    def email_subject_preview(self) -> str:
        return self.format_email_subject("Přehled tréninků – Jméno hráče")

    def podpis_html(self) -> str:
        from django.utils.html import escape

        return escape(self.effective_podpis()).replace("\n", "<br>")

    def debt_filter_q(self):
        """Podmínka pro výběr dlužníků podle prahu (vyžaduje anotaci _kredit_calculated)."""
        prah = Decimal(self.prah_dluhu_dashboard or 0)
        if prah >= 0:
            return Q(_kredit_calculated__lt=Decimal("0"))
        return Q(_kredit_calculated__lte=prah)

    def filter_debtors(self, qs):
        """Omezí queryset hráčů podle prahu dluhu."""
        return qs.filter(self.debt_filter_q())

    def sync_colors_from_preset(self, *, commit: bool = False) -> None:
        """Vyplní barevná pole podle zvolené palety a režimu."""
        from .system_theme import MODEL_FIELD_MAP, preset_colors

        colors = preset_colors(self.barevna_varianta, dark=self.tmavy_rezim)
        for key, field in MODEL_FIELD_MAP.items():
            setattr(self, field, colors[key])
        if commit:
            self.save()


# =========================================================
#  INTELIGENTNÍ SYNC DOCHÁZKY A TRANSAKCÍ (VYLEPŠENO)
# =========================================================

@receiver(post_save, sender=Dochazka)
def auto_naucet_pri_dochazce(sender, instance: "Dochazka", created: bool, **kwargs):
    """
    Řeší vytvoření ALE I AKTUALIZACI transakce při změně docházky.
    """
    if kwargs.get("raw"):
        return

    # 1. Pokud hráč "nepřišel", smažeme případnou existující transakci
    if not instance.prisel:
        if instance.transakce_nauc_id:
            instance.transakce_nauc.delete()
            instance.transakce_nauc = None
            instance.castka_nauc = None
            instance.nauceno_kdy = None
            instance.save(update_fields=["transakce_nauc", "castka_nauc", "nauceno_kdy"])
        return

    # 2. Získáme trénink a ceník
    trening = instance.trening
    pravidlo = trening.aktualni_cenik()
    
    # Pokud není ceník, nemůžeme nic účtovat (nebo je zdarma)
    if not pravidlo:
        return

    nov_castka = (pravidlo.cena_za_hodinu * trening.hodiny).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    popis_text = (
        f"Trénink {trening.get_format_display().lower()} • "
        f"{trening.get_kurt_display().lower()} "
        f"{trening.datum:%Y-%m-%d} ({trening.delka_minut} min)"
    )

    # 3. Pokud transakce už existuje -> AKTUALIZUJEME JI (To vám chybělo)
    if instance.transakce_nauc_id:
        tx = instance.transakce_nauc
        zmena = False
        
        # Kontrola: Změnil se hráč? (např. v adminu jste přepsali jméno v dropdownu)
        if tx.hrac != instance.hrac:
            tx.hrac = instance.hrac
            zmena = True
        
        # Kontrola: Změnila se cena (např. změna délky tréninku) nebo datum?
        if tx.castka != nov_castka:
            tx.castka = nov_castka
            zmena = True
            
        if tx.vytvoreno != trening.datum:
            tx.vytvoreno = trening.datum
            zmena = True
            
        # Vždy aktualizujeme popis, kdyby se změnil formát tréninku
        if tx.popis != popis_text:
            tx.popis = popis_text
            zmena = True

        if zmena:
            tx.save()
            # Aktualizujeme i cache hodnoty v docházce
            instance.castka_nauc = nov_castka
            instance.save(update_fields=["castka_nauc"])
        return

    # 4. Pokud transakce neexistuje -> VYTVOŘÍME JI
    # (Nejprve kontrola, zda už neexistuje "volná" transakce pro stejný trénink a hráče, abychom nedublovali)
    exists = Transakce.objects.filter(
        hrac=instance.hrac, trening=trening, typ=Transakce.Typ.NAUCTOVANO
    ).first()
    
    if exists:
        # Pokud existuje, jen ji napojíme
        instance.transakce_nauc = exists
        instance.castka_nauc = exists.castka
        instance.nauceno_kdy = timezone.now()
        instance.save(update_fields=["transakce_nauc", "castka_nauc", "nauceno_kdy"])
        return

    # Vytvoření nové
    tx = Transakce.objects.create(
        hrac=instance.hrac,
        typ=Transakce.Typ.NAUCTOVANO,
        castka=nov_castka,
        popis=popis_text,
        trening=trening,
        vytvoreno=trening.datum # Datum transakce = datum tréninku
    )

    instance.transakce_nauc = tx
    instance.castka_nauc = nov_castka
    instance.nauceno_kdy = timezone.now()
    instance.save(update_fields=["transakce_nauc", "castka_nauc", "nauceno_kdy"])

    # Logika pro počítadla vyúčtování
    hrac = instance.hrac
    hrac.pocet_treninku_od_vyuctovani = (hrac.pocet_treninku_od_vyuctovani or 0) + 1
    hrac.save(update_fields=["pocet_treninku_od_vyuctovani"])

    _schedule_auto_vyuctovani(hrac.pk)


# --- NOVÉ: Smazání transakce při smazání hráče z tréninku ---
@receiver(post_delete, sender=Dochazka)
def smaz_transakci_pri_smazani_dochazky(sender, instance, **kwargs):
    """
    Když v adminu kliknete na 'Odstranit' u hráče (nebo celý trénink),
    musí zmizet i peněžní transakce.
    """
    if kwargs.get("raw"):
        return
    if instance.transakce_nauc_id:
        instance.transakce_nauc.delete()


# --- NOVÉ: Automatická aktualizace cen při změně Tréninku ---
@receiver(post_save, sender=Trening)
def aktualizuj_transakce_pri_zmene_treningu(sender, instance, created, **kwargs):
    """
    Když změníte DATUM, DÉLKU nebo TYP tréninku, tento signál projde
    všechny přihlášené hráče a přepočítá jim cenu/datum v transakcích.
    """
    if kwargs.get("raw") or created:
        return

    # Projdeme všechny docházky tohoto tréninku
    for dochazka in instance.dochazky.all():
        # Zavoláme uložení docházky, což spustí funkci 'auto_naucet_pri_dochazce'
        # a ta provede přepočet ceny a aktualizaci data.
        dochazka.save()


# ===== Trenér – profil (výchozí sazba) =====
class TrenerProfil(models.Model):
# ... zbytek je v pořádku ...
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="trener_profil")
    sazba_za_hodinu = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("500.00"))

    class Meta:
        verbose_name = _("Trenér – sazba")
        verbose_name_plural = _("Trenéři – sazby")

    def __str__(self):
        jmeno = self.user.get_full_name() or self.user.username
        return f"{jmeno} – {format_castka(self.sazba_za_hodinu, per_hour=True)}"


@receiver(post_save, sender=User)
def _ensure_trener_profil(sender, instance, created, **kwargs):
    if kwargs.get("raw") or not created:
        return
    TrenerProfil.objects.create(user=instance)
    UserPreference.objects.get_or_create(user=instance)


# ===== Preference vzhledu uživatele =====
class UserPreference(models.Model):
    """Osobní vzhled adminu – má přednost před systémovým výchozím."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="preference",
        verbose_name=_("Uživatel"),
    )
    barevna_varianta = models.CharField(
        _("Barevná varianta"),
        max_length=16,
        choices=THEME_CHOICES,
        blank=True,
        default="",
        help_text=_("Prázdné = výchozí vzhled klubu."),
    )
    tmavy_rezim = models.BooleanField(
        _("Tmavý režim"),
        null=True,
        blank=True,
        help_text=_("Prázdné = výchozí režim klubu."),
    )

    class Meta:
        verbose_name = _("Preference uživatele")
        verbose_name_plural = _("Preference uživatelů")

    def __str__(self) -> str:
        return f"Preference: {self.user.get_username()}"

    @classmethod
    def for_user(cls, user) -> "UserPreference":
        pref, _ = cls.objects.get_or_create(user=user)
        return pref


# ===== Datumově účinné sazby trenéra =====
class TrenerSazba(models.Model):
# ... zbytek je v pořádku ...
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="trenerske_sazby")
    platnost_od = models.DateField()                         # včetně
    platnost_do = models.DateField(blank=True, null=True)    # včetně; None = bez konce
    sazba_za_hodinu = models.DecimalField(max_digits=9, decimal_places=2)

    class Meta:
        verbose_name = _("Trenér – sazba (období)")
        verbose_name_plural = _("Trenéři – sazby (období)")
        ordering = ("-platnost_od",)
        indexes = [models.Index(fields=["user", "platnost_od", "platnost_do"])]

    def __str__(self):
        od = self.platnost_od.strftime("%d.%m.%Y")
        do = self.platnost_do.strftime("%d.%m.%Y") if self.platnost_do else "—"
        jmeno = self.user.get_full_name() or self.user.username
        return f"{jmeno}: {format_castka(self.sazba_za_hodinu, per_hour=True)} ({od} – {do})"

    def clean(self):
        """Zákaz překryvů období pro stejného trenéra."""
        qs = TrenerSazba.objects.filter(user=self.user)
        if self.pk:
            qs = qs.exclude(pk=self.pk)

        od = self.platnost_od
        do = self.platnost_do
        overlap = qs.filter(
            Q(platnost_do__isnull=True, platnost_od__lte=(do or od)) | Q(platnost_do__gte=od)
        ).filter(platnost_od__lte=(do or od)).exists()

        if overlap:
            raise ValidationError("Období sazby se překrývá s jinou sazbou tohoto trenéra.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    # +++ NOVÉ: bezpečně nastaví novou sazbu od data a uzavře případné otevřené období do včera
    @classmethod
    def set_rate_from(cls, user: User, effective_from, rate: Decimal, end_date=None):
        """
        Vytvoří záznam sazby (effective_from … end_date) a
        všem překrývajícím se záznamům pro stejného trenéra,
        které běží přes 'effective_from', nastaví platnost_do = effective_from - 1 den.
        """
        # normalizace na date
        if hasattr(effective_from, "date"):
            effective_from = effective_from.date()

        close_to = effective_from - timedelta(days=1)

        with transaction.atomic():
            overlapping = (
                cls.objects
                .select_for_update()
                .filter(user=user, platnost_od__lte=effective_from)
                .filter(Q(platnost_do__isnull=True) | Q(platnost_do__gte=effective_from))
            )
            for rec in overlapping:
                if rec.platnost_do is None or rec.platnost_do >= effective_from:
                    rec.platnost_do = close_to
                    rec.full_clean()
                    rec.save(update_fields=["platnost_do"])

            new_rec = cls(
                user=user,
                platnost_od=effective_from,
                platnost_do=end_date,
                sazba_za_hodinu=rate,
            )
            new_rec.full_clean()
            new_rec.save()
            return new_rec


# ===== Výplaty trenérům =====
class TrenerPlatba(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="trener_platby")
    castka = models.DecimalField(max_digits=10, decimal_places=2)
    poznamka = models.CharField(max_length=240, blank=True)
    vytvoreno = models.DateTimeField("Datum výplaty", default=timezone.now)

    class Meta:
        ordering = ["-vytvoreno"]
        verbose_name = _("Výplata trenérovi")
        verbose_name_plural = _("Výplaty trenérům")
        indexes = [models.Index(fields=["user", "vytvoreno"])]

    def __str__(self) -> str:
        jmeno = self.user.get_full_name() or self.user.username
        return f"{jmeno}: {format_castka(self.castka)} ({self.vytvoreno:%Y-%m-%d})"


# ===== Ostatní provozní náklady =====
class OstatniNaklad(models.Model):
    class Kategorie(models.TextChoices):
        ENERGIE = "ENERGIE", _("Energie")
        NAJEM = "NAJEM", _("Nájem")
        BONUSY = "BONUSY", _("Bonusy")
        MIC = "MIC", _("Míče a protže")
        VYBAVENI = "VYBAVENI", _("Vybavení")
        UDRZBA = "UDRZBA", _("Údržba kurtů")
        POJISTENI = "POJISTENI", _("Pojištění")
        MARKETING = "MARKETING", _("Marketing")
        DOPRAVA = "DOPRAVA", _("Doprava")
        ADMIN = "ADMIN", _("Administrativa")
        OSTATNI = "OSTATNI", _("Ostatní")

    mesic = models.DateField(_("Datum"), help_text=_("Den, ke kterému se náklad vztahuje"))
    kategorie = models.CharField(_("Kategorie"), max_length=20, choices=Kategorie.choices)
    castka = models.DecimalField(_("Částka"), max_digits=12, decimal_places=2, default=Decimal("0.00"))
    poznamka = models.CharField(_("Poznámka"), max_length=240, blank=True, default="")
    vytvoreno = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Ostatní náklad")
        verbose_name_plural = _("Ostatní náklady")
        ordering = ["-mesic", "kategorie"]
        constraints = [
            models.UniqueConstraint(fields=["mesic", "kategorie"], name="uniq_ostatni_naklad_mesic_kat"),
        ]
        indexes = [models.Index(fields=["mesic"])]

    def __str__(self) -> str:
        return f"{self.get_kategorie_display()} {self.mesic:%d.%m.%Y}: {format_castka(self.castka)}"


# ===== Helper: sazba platná k datu =====
def sazba_trenera_k_datu(user: User, dt) -> Decimal:
# ... zbytek je v pořádku ...
    """
    Vrátí sazbu trenéra platnou k datu `dt` (date nebo datetime):
    1) Hledá TrenerSazba pro dané datum
    2) Fallback na TrenerProfil.sazba_za_hodinu
    3) Fallback na 500.00
    """
    if hasattr(dt, "date"):
        # pokud je aware, převeď na lokální čas
        if dj_tz.is_aware(dt):
            dt = dj_tz.localtime(dt)
        dt = dt.date()

    rec = (
        TrenerSazba.objects.filter(user=user, platnost_od__lte=dt)
        .filter(Q(platnost_do__gte=dt) | Q(platnost_do__isnull=True))
        .order_by("-platnost_od")
        .first()
    )
    if rec:
        return rec.sazba_za_hodinu # <--- NÁVRAT HODNOTY!

    # Fallback 2: Hledá profil trenéra
    try:
        return user.trener_profil.sazba_za_hodinu
    except TrenerProfil.DoesNotExist:
        pass

    # Fallback 3: Výchozí sazba (pokud profil neexistuje)
    return Decimal("500.00")


@receiver(pre_save, sender=Hrac)
def hrac_vyuctovani_defaults(sender, instance: Hrac, **kwargs):
    """Novým hráčům nastaví režim vyúčtování podle globálního nastavení."""
    if kwargs.get("raw") or instance.pk:
        return
    nast = VyuctovaniNastaveni.load()
    instance.vyuctovani_rezim = nast.auto_rezim
    instance.vyuctovani_n = nast.auto_pocet_treninku
    instance.vyuctovani_threshold = nast.auto_limit


@receiver(post_delete, sender=Vyuctovani)
def synchronizuj_hrace_po_smazani_vyuctovani(sender, instance: Vyuctovani, **kwargs):
    """Po smazání vyúčtování přepočítá stav uzávěrky u hráče."""
    hrac_id = instance.hrac_id
    if not hrac_id:
        return
    hrac = Hrac.objects.filter(pk=hrac_id).first()
    if hrac:
        hrac.prepocitat_stav_uzaverky()