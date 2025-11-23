from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta, datetime, time

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from core.utils.email_archive import send_and_append_to_sent
from django.db import models, transaction
from django.db.models import Q, Sum
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone as dj_tz # Ponechávám dj_tz pro zkrácený zápis
from django.utils import timezone           # Ponechávám timezone pro default=timezone.now
from django.utils.html import format_html
import logging
logger = logging.getLogger(__name__)


# =========================
#  Rodina
# =========================
class Rodina(models.Model):
# ... kód Rodina je v pořádku ...
    nazev = models.CharField("Název rodiny (např. Peterkovi)", max_length=120, blank=True, default="")
    kontakt_email = models.EmailField(blank=True, null=True)
    kontakt_telefon = models.CharField(max_length=40, blank=True, default="")
    poznamka = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Rodina"
        verbose_name_plural = "Rodiny"
        ordering = ("nazev", "id")   

    def __str__(self):
        return self.nazev or "Rodina"


# =========================
#  Hráč
# =========================
class Hrac(models.Model):
    class RezimVyuctovani(models.TextChoices):
        MESICNE = "MESICNE", "Měsíčně"
        N_TRENINGU = "N_TRENINGU", "Po N trénincích"
        CASTKA = "CASTKA", "Po dosažení částky"

    jmeno = models.CharField(max_length=120)
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
        max_digits=10, decimal_places=2, default=Decimal("2000.00")
    )
    posledni_vyuctovani_at = models.DateTimeField(blank=True, null=True)
    pocet_treninku_od_vyuctovani = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Hráč"
        verbose_name_plural = "Hráči"
        ordering = ("jmeno",)   # rozumné výchozí řazení

    def __str__(self) -> str:
        return self.jmeno

    # Bezpečný fallback – používáš self.cele_jmeno v e-mailu
    @property
    def cele_jmeno(self) -> str:
        return self.jmeno

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
        email_variant: str = "1",  # <-- NOVÝ PARAMETR
        override_amount_due: Decimal | None = None,
        override_period_from=None,   # date/datetime/None
        override_period_to=None,     # date/datetime/None
    ):
        """
        Uzávěrka za období.
        """
        def _normalize_dt(x, is_end=False):
            """date -> datetime (min/max), zajištění timezone-aware pokud USE_TZ."""
            if not x:
                return None
            if isinstance(x, datetime):
                dt = x
            else:
                dt = datetime.combine(x, time.max if is_end else time.min)
            if dj_tz.is_naive(dt) and settings.USE_TZ:
                dt = dj_tz.make_aware(dt, dj_tz.get_current_timezone())
            return dt

        now = dj_tz.now()

        period_from = _normalize_dt(override_period_from) if override_period_from else self.posledni_vyuctovani_at
        period_to = _normalize_dt(override_period_to, is_end=True) if override_period_to else now

        # Transakce v období
        tx_qs = self.transakce.filter(vytvoreno__lte=period_to)
        if period_from:
            tx_qs = tx_qs.filter(vytvoreno__gt=period_from)

        charges = tx_qs.filter(typ=Transakce.Typ.NAUCTOVANO).aggregate(Sum("castka"))["castka__sum"] or Decimal("0")
        pays = tx_qs.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA]).aggregate(Sum("castka"))["castka__sum"] or Decimal("0")

        computed_amount = (Decimal(charges) - Decimal(pays)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        amount_due = (
            Decimal(override_amount_due).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if override_amount_due is not None else computed_amount
        )

        # Docházky v období – jen skutečně odehrané (pro statistiku)
        sessions = self.dochazky.filter(
            prisel=True,
            trening__datum__lte=period_to,
            **({"trening__datum__gt": period_from} if period_from else {})
        ).count()

        # Snapshoty kreditu
        credit_end = self.kredit
        delta_credit = (Decimal(pays) - Decimal(charges)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        credit_start = (credit_end - delta_credit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        vyuct = Vyuctovani.objects.create(
            hrac=self,
            period_from=period_from,
            period_to=period_to,
            sessions_count=sessions,
            charges_total=Decimal(charges).quantize(Decimal("0.01")),
            payments_total=Decimal(pays).quantize(Decimal("0.01")),
            amount_due=amount_due,
            credit_start=credit_start,
            credit_end=credit_end,
            reason=duvod,
        )

        # Posuň kurzor jen pokud se nepoužilo ruční období
        if not (override_period_from or override_period_to):
            self.posledni_vyuctovani_at = now
            self.pocet_treninku_od_vyuctovani = 0
            self.save(update_fields=["posledni_vyuctovani_at", "pocet_treninku_od_vyuctovani"])

        # ===== E-mail (volitelně) – historie podobná admin tabulce =====
        if send_email and self.email:
            charges_qs = (
                tx_qs.filter(typ=Transakce.Typ.NAUCTOVANO)
                .select_related("trening")
                .order_by("trening__datum")
            )
            pays_qs = (
                tx_qs.filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA])
                .order_by("vytvoreno")
            )

            start_credit = Decimal("0.00")
            if period_from:
                before_charges = (
                    self.transakce
                    .filter(typ=Transakce.Typ.NAUCTOVANO, vytvoreno__lt=period_from) 
                    .aggregate(s=Sum("castka"))["s"] or 0
                )
                before_pays = (
                    self.transakce
                    .filter(typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA], vytvoreno__lt=period_from)
                    .aggregate(s=Sum("castka"))["s"] or 0
                )
                start_credit = (Decimal(before_pays) - Decimal(before_charges)).quantize(Decimal("0.01"))

            events = []
            for tx in charges_qs:
                dt = tx.trening.datum if tx.trening else tx.vytvoreno
                if dj_tz.is_aware(dt):
                    dt = dj_tz.localtime(dt)
                events.append(("CHARGE", dt, tx))
            for tx in pays_qs:
                dt = tx.vytvoreno
                if dj_tz.is_aware(dt):
                    dt = dj_tz.localtime(dt)
                events.append(("PAY", dt, tx))
            events.sort(key=lambda t: t[1])

            # Zjistíme poslední datum v seznamu pro přesnější text e-mailu
            last_event_date = events[-1][1] if events else period_to
            display_period_to = last_event_date if override_period_to else period_to

            running_credit = start_credit
            sum_cena = Decimal("0")
            sum_paid = Decimal("0")

            lines = ["Datum\tČas\tSkupina\tCena\tZaplaceno\tKredit"]
            rows_html_parts = []

            for typ, dt, tx in events:
                datum_str = dt.strftime("%d.%m.%Y")
                cas_str = dt.strftime("%H:%M")

                skupina = "—"
                cena = zaplaceno = ""

                if typ == "CHARGE":
                    if tx.trening:
                        skupina = tx.trening.get_format_display() 
                    amt = Decimal(tx.castka or 0)
                    sum_cena += amt
                    running_credit -= amt
                    cena = f"{amt:.0f} Kč"
                else:  # PAY
                    amt = Decimal(tx.castka or 0)
                    sum_paid += amt
                    running_credit += amt
                    zaplaceno = f"{amt:.0f} Kč"

                kredit_str = f"{running_credit:.0f} Kč"

                lines.append(f"{datum_str}\t{cas_str}\t{skupina}\t{cena or '—'}\t{zaplaceno or '—'}\t{kredit_str}")

                rows_html_parts.append(
                    "<tr>"
                    f"<td>{datum_str}</td>"
                    f"<td>{cas_str}</td>"
                    f"<td>{skupina}</td>"
                    f"<td align='center'>{cena or '—'}</td>" # ZMĚNA: align='center'
                    f"<td align='center'>{zaplaceno or '—'}</td>" # ZMĚNA: align='center'
                    f"<td align='center'><strong>{kredit_str}</strong></td>" # ZMĚNA: align='center'
                    "</tr>"
                )

            if not rows_html_parts:
                rows_html_parts.append("<tr><td colspan='6' align='center'>—</td></tr>")

            totals_html = (
                "<tr style='background:#f9fafb'>"
                "<td colspan='3' align='right'><strong>Součty</strong></td>"
                f"<td align='center'><strong>{sum_cena:.0f} Kč</strong></td>" # ZMĚNA: align='center'
                f"<td align='center'><strong>{sum_paid:.0f} Kč</strong></td>" # ZMĚNA: align='center'
                f"<td align='center'><strong>{running_credit:.0f} Kč</strong></td>" # ZMĚNA: align='center'
                "</tr>"
            )
            rows_html = "".join(rows_html_parts) + totals_html
            table_txt = "\n".join(lines + [f"Součty\t\t\t{sum_cena:.0f} Kč\t{sum_paid:.0f} Kč\t{running_credit:.0f} Kč"])

            kredit_po_uhrade = (credit_end + amount_due).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            
            subject = f"Přehled tréninků a vyúčtování – {self.cele_jmeno}"
            
            if email_variant == "2":
                cislo_uctu_text = "2108539314/2700"
                cislo_uctu_html = "<strong>2108539314/2700</strong>"
            else:
                cislo_uctu_text = "2102303853/2700"
                cislo_uctu_html = "<strong>2102303853/2700</strong>"

            text_body = (
                f"Zasílám přehled tréninků a vyúčtování za období od {period_from.strftime('%d.%m.%Y') if period_from else 'začátku'} do {display_period_to.strftime('%d.%m.%Y')}.\n\n"
                "Níže je přiložen podrobný rozpis všech položek.\n\n"
                "---\n"
                "**Přehled kreditu:**\n\n"
                f"Aktuální kredit (před platbou): {credit_end:.0f} Kč\n"
                f"Celková cena tréninků v tomto období: {sum_cena:.0f} Kč\n\n"
                "Pro vyrovnání kreditu a jeho navýšení na další období je třeba uhradit:\n\n"
                f"Částka k zaplacení: **{amount_due:.0f} Kč**\n\n"
                "Platební údaje:\n"
                f"Číslo účtu: **{cislo_uctu_text}**\n"
                "Variabilní symbol: **Jméno hráče**\n\n"
                f"Po připsání platby bude stav kreditu: {kredit_po_uhrade:.0f} Kč\n"
                "---\n\n"
                "Detailní rozpis tréninků:\n\n"
                f"{table_txt}\n\n"
                "Děkuji.\n\n"
                "S pozdravem,\n\n"
                "Kateřina Peterková\n"
                "Tenis Čimice"
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
                Aktuální kredit (před platbou): <strong>{credit_end:.0f} Kč</strong><br>
                Celková cena tréninků v tomto období: <strong>{sum_cena:.0f} Kč</strong>
              </div>

              <div style="margin: 20px 0;">
                Pro vyrovnání kreditu a jeho navýšení na další období je třeba uhradit:
              </div>
              
              <div style="background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 20px;">
                <div style="font-size: 1.1em; margin-bottom: 12px;">
                  Částka k zaplacení: <strong style="font-size: 1.3em; color: #111827;">{amount_due:.0f} Kč</strong>
                </div>
                <div style="line-height: 1.7;">
                  Platební údaje:<br>
                  Číslo účtu: {cislo_uctu_html}<br> Variabilní symbol: <strong>Jméno hráče</strong> 
                </div>
              </div>
              
              <div style="margin-bottom: 20px;">
                Po připsání platby bude stav kreditu: <strong>{kredit_po_uhrade:.0f} Kč</strong>
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
              <p style="margin-top:16px;">S pozdravem,<br><br>Kateřina Peterková<br>Tenis Čimice</p>
            </div>
            """

            ok_send, ok_archive = send_and_append_to_sent(
                subject=subject,
                body=text_body,
                html_body=html_body,
                to=self.email,
            )

            logger.info(
                ">>> VYUCTOVANI: email_send=%s, saved_to_sent=%s, hrac=%s, email=%s, subject=%s",
                ok_send, ok_archive, self.cele_jmeno, self.email, subject
            )


        return vyuct

    def mozna_uzavrit_podle_rezimu(self) -> bool:
        """Zda hráč splnil podmínky pro uzávěrku (měsíční dělá plánovač)."""
        if self.vyuctovani_rezim == self.RezimVyuctovani.N_TRENINGU:
            return self.pocet_treninku_od_vyuctovani >= max(1, self.vyuctovani_n)
        if self.vyuctovani_rezim == self.RezimVyuctovani.CASTKA:
            return self.nedoplatek_od_posledni_uzaverky() >= self.vyuctovani_threshold
        return False


# =========================
#  Ceník (OPRAVENO S VALIDACÍ)
# =========================
class Cenik(models.Model):
    class Format(models.TextChoices):
        # UNIKÁTNÍ KLÍČE jsou nezbytné pro správnou funkci TextChoices
        SOLO_C = "SOLO_C", "Solo (1 hráč) - Člen"
        DVOJICE_C = "DVOJICE_C", "Dvojice (2 hráči) - Člen"
        TROJICE_C = "TROJICE_C", "Trojice (3 hráči) - Člen"
        CTVRICE_C = "CTVRICE_C", "Čtveřice (4 hráči) - Člen"
        PETICE = "PETICE", "Pětice (5 a více hráčů)"
        
        SOLO_NC = "SOLO_NC", "Solo Nečlen (1 hráč)"
        DVOJICE_NC = "DVOJICE_NC", "Dvojice Nečlen (2 hráči)"
        TROJICE_NC = "TROJICE_NC", "Trojice Nečlen (3 hráči)"
        CTVRICE_NC = "CTVRICE_NC", "Čtveřice Nečlen (4 hráči)"
        
        SOBOTA_TRE = "SOBOTA_TRE", "Sobota Trénink"
        KURT_TRE = "KURT_TRE", "Kurt Hodina"

        VYPLET_STAND = "V_STAND", "Výplet (400 Kč) - Standard"
        VYPLET_EXCEL = "V_EXCEL", "Výplet excel (530 Kč)"
        VYPLET_VLASTNI = "V_VLAST", "Výplet vlastní (250 Kč)"

    class Kurt(models.TextChoices):
        VENEK = "VENEK", "Venku"
        HALA = "HALA", "Hala"
        SLUZBA = "SLUZBA", "Služba (neplatí pro kurt)"

    format = models.CharField(max_length=15, choices=Format.choices) 
    kurt = models.CharField(max_length=8, choices=Kurt.choices) 
    cena_za_hodinu = models.DecimalField(max_digits=8, decimal_places=2)

    platnost_od = models.DateField(default=timezone.now)
    platnost_do = models.DateField(blank=True, null=True)

    # --- ZDE BYL PŘIDÁN KÓD ---
    def clean(self):
        """
        Zabrání uložení, pokud se období platnosti pro stejný formát a kurt překrývá
        s již existujícím záznamem.
        """
        super().clean()

        # Najdi všechny ostatní záznamy pro stejný formát a kurt
        qs = Cenik.objects.filter(format=self.format, kurt=self.kurt)
        if self.pk:
            qs = qs.exclude(pk=self.pk) # Vyloučí sama sebe při úpravě

        # Zkontroluj překryv období
        # Nové období začíná: self.platnost_od
        # Nové období končí: self.platnost_do (může být None)
        overlap_qs = qs.filter(
            # Podmínka: Starý záznam končí PO začátku nového záznamu
            Q(platnost_do__gte=self.platnost_od) | Q(platnost_do__isnull=True)
        )
        if self.platnost_do:
            # A zároveň: Starý záznam začíná PŘED koncem nového záznamu
            overlap_qs = overlap_qs.filter(platnost_od__lte=self.platnost_do)

        if overlap_qs.exists():
            raise ValidationError(
                f"Období platnosti se překrývá s již existujícím ceníkem pro '{self.get_format_display()}' na kurtu '{self.get_kurt_display()}'."
            )
    # --- KONEC PŘIDANÉHO KÓDU ---

    class Meta:
        verbose_name = "Ceník"
        verbose_name_plural = "Ceník"
        indexes = [models.Index(fields=["format", "kurt", "platnost_od", "platnost_do"])]

    def __str__(self) -> str:
        return f"{self.get_format_display()} • {self.get_kurt_display()} – {self.cena_za_hodinu} Kč/h"


# =========================
#  Trénink (lekce) (OPRAVENO)
# =========================
class Trening(models.Model):
    trener = models.ForeignKey(User, on_delete=models.PROTECT)
    datum = models.DateTimeField()
    delka_minut = models.PositiveIntegerField(default=60)

    # formát a typ kurtu ovlivní ceník
    # ZMĚNA: max_length na 10, musí odpovídat Cenik.format
    format = models.CharField(max_length=10, choices=Cenik.Format.choices)
    kurt = models.CharField(max_length=8, choices=Cenik.Kurt.choices)

    poznamka = models.CharField(max_length=240, blank=True)

    hraci = models.ManyToManyField(Hrac, through="Dochazka", related_name="treningy")
# ... zbytek třídy Trening je v pořádku ...
    def __str__(self) -> str:
        return (
            f"{self.datum:%Y-%m-%d %H:%M} • "
            f"{self.get_format_display()} • "
            f"{self.get_kurt_display()} • "
            f"{self.trener.username}"
        )

    class Meta:
        verbose_name = "Trénink"
        verbose_name_plural = "Tréninky"

    @property
    def hodiny(self) -> Decimal:
        return (Decimal(self.delka_minut) / Decimal(60)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # NOVÁ LOGIKA SEZÓNY
    @property
    def sezona_display(self) -> str:
        """Vypočítá sezónu na základě kurtu."""
        if self.kurt == Cenik.Kurt.VENEK:
            return "Léto"
        elif self.kurt == Cenik.Kurt.HALA:
            return "Zima"
        return "Celoroční"

    def aktualni_cenik(self) -> "Cenik | None":
        d = self.datum.date()
        qs = (
            Cenik.objects.filter(format=self.format, kurt=self.kurt)
            .filter(Q(platnost_od__lte=d), Q(platnost_do__gte=d) | Q(platnost_do__isnull=True))
            .order_by("-platnost_od")
        )
        return qs.first()

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

    def __str__(self) -> str:
        return f"{self.hrac.jmeno} @ {self.trening}"


# =========================
#  Pohyby na účtu hráče
# =========================
class Transakce(models.Model):
# ... zbytek je v pořádku ...
    class Typ(models.TextChoices):
        NAUCTOVANO = "NAUCTOVANO", "Naúčtováno"
        PLATBA = "PLATBA", "Platba"
        VRATKA = "VRATKA", "Vrácení/bonifikace"
        UPRAVA = "UPRAVA", "Úprava"

    hrac = models.ForeignKey(Hrac, related_name="transakce", on_delete=models.CASCADE)
    typ = models.CharField(max_length=12, choices=Typ.choices)
    castka = models.DecimalField(max_digits=10, decimal_places=2)  # KLADNÁ částka
    popis = models.CharField(max_length=240, blank=True)
    trening = models.ForeignKey(Trening, null=True, blank=True, on_delete=models.CASCADE)
    vytvoreno = models.DateTimeField("Datum platby", default=timezone.now)

    class Meta:
        ordering = ["-vytvoreno"]
        verbose_name = "Platba"
        verbose_name_plural = "Platby"

    def __str__(self) -> str:
        sign = "+" if self.typ in [self.Typ.PLATBA, self.Typ.VRATKA] else "-"
        return f"{self.hrac.jmeno}: {self.get_typ_display()} {self.castka} Kč ({sign})"


# =========================
#  Souhrnné vyúčtování (log)
# =========================
class Vyuctovani(models.Model):
# ... zbytek je v pořádku ...
    hrac = models.ForeignKey(Hrac, on_delete=models.CASCADE, related_name="vyuctovani")
    period_from = models.DateTimeField(null=True, blank=True)  # od poslední uzávěrky
    period_to = models.DateTimeField()                         # uzávěrka do
    sessions_count = models.PositiveIntegerField(default=0)

    # snapshoty
    charges_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    payments_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)

    credit_start = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    credit_end = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    reason = models.CharField(max_length=32, default="manual")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Vyúčtování"
        verbose_name_plural = "Vyúčtování"

    def __str__(self) -> str:
        frm = self.period_from.strftime("%Y-%m-%d %H:%M") if self.period_from else "—"
        return f"Vyúčtování {self.hrac.jmeno} [{frm} → {self.period_to:%Y-%m-%d %H:%M}] = {self.amount_due} Kč"

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
#  Automatické NAUČTOVÁNÍ při uložení Docházky
# =========================
@receiver(post_save, sender=Dochazka)
def auto_naucet_pri_dochazce(sender, instance: "Dochazka", created: bool, **kwargs):
# ... zbytek je v pořádku ...
    """
    Prišel → vytvoř Transakci(NAUCTOVANO) podle ceníku a délky.
    Nepřišel → případný charge smaž.
    """
    if not instance.prisel:
        if instance.transakce_nauc:
            instance.transakce_nauc.delete()
            instance.transakce_nauc = None
            instance.castka_nauc = None
            instance.nauceno_kdy = None
            instance.save(update_fields=["transakce_nauc", "castka_nauc", "nauceno_kdy"])
        return

    if instance.transakce_nauc:
        return

    trening = instance.trening
    pravidlo = trening.aktualni_cenik()
    if not pravidlo:
        return

    castka = (pravidlo.cena_za_hodinu * trening.hodiny).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    exists = Transakce.objects.filter(
        hrac=instance.hrac, trening=trening, typ=Transakce.Typ.NAUCTOVANO
    ).exists()
    if exists:
        return

    tx = Transakce.objects.create(
        hrac=instance.hrac,
        typ=Transakce.Typ.NAUCTOVANO,
        castka=castka,
        popis=(
            f"Trénink {trening.get_format_display().lower()} • "
            f"{trening.get_kurt_display().lower()} "
            f"{trening.datum:%Y-%m-%d} ({trening.delka_minut} min)"
        ),
        trening=trening,
    )

    instance.transakce_nauc = tx
    instance.castka_nauc = castka
    instance.nauceno_kdy = timezone.now()
    instance.save(update_fields=["transakce_nauc", "castka_nauc", "nauceno_kdy"])

    hrac = instance.hrac
    hrac.pocet_treninku_od_vyuctovani = (hrac.pocet_treninku_od_vyuctovani or 0) + 1
    hrac.save(update_fields=["pocet_treninku_od_vyuctovani"])

    if hrac.mozna_uzavrit_podle_rezimu():
        hrac.vygeneruj_vyuctovani(duvod=hrac.vyuctovani_rezim)


# ===== Trenér – profil (výchozí sazba) =====
class TrenerProfil(models.Model):
# ... zbytek je v pořádku ...
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="trener_profil")
    sazba_za_hodinu = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("500.00"))

    class Meta:
        verbose_name = "Trenér – sazba"
        verbose_name_plural = "Trenéři – sazby"

    def __str__(self):
        jmeno = self.user.get_full_name() or self.user.username
        return f"{jmeno} – {self.sazba_za_hodinu} Kč/h"


@receiver(post_save, sender=User)
def _ensure_trener_profil(sender, instance, created, **kwargs):
    if created:
        TrenerProfil.objects.create(user=instance)


# ===== Datumově účinné sazby trenéra =====
class TrenerSazba(models.Model):
# ... zbytek je v pořádku ...
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="trenerske_sazby")
    platnost_od = models.DateField()                         # včetně
    platnost_do = models.DateField(blank=True, null=True)    # včetně; None = bez konce
    sazba_za_hodinu = models.DecimalField(max_digits=9, decimal_places=2)

    class Meta:
        verbose_name = "Trenér – sazba (období)"
        verbose_name_plural = "Trenéři – sazby (období)"
        ordering = ("-platnost_od",)
        indexes = [models.Index(fields=["user", "platnost_od", "platnost_do"])]

    def __str__(self):
        od = self.platnost_od.strftime("%d.%m.%Y")
        do = self.platnost_do.strftime("%d.%m.%Y") if self.platnost_do else "—"
        jmeno = self.user.get_full_name() or self.user.username
        return f"{jmeno}: {self.sazba_za_hodinu} Kč/h ({od} – {do})"

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
# ... zbytek je v pořádku ...
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="trener_platby")
    castka = models.DecimalField(max_digits=10, decimal_places=2)
    poznamka = models.CharField(max_length=240, blank=True)
    vytvoreno = models.DateTimeField("Datum výplaty", default=timezone.now)

    class Meta:
        ordering = ["-vytvoreno"]
        verbose_name = "Výplata trenérovi"
        verbose_name_plural = "Výplaty trenérům"
        indexes = [models.Index(fields=["user", "vytvoreno"])]

    def __str__(self) -> str:
        jmeno = self.user.get_full_name() or self.user.username
        return f"{jmeno}: {self.castka} Kč ({self.vytvoreno:%Y-%m-%d})"


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