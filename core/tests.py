"""
Unit tests for critical billing logic.
"""
from decimal import Decimal
from datetime import datetime, timedelta, date

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import (
    Rodina,
    Hrac,
    Trening,
    Dochazka,
    Cenik,
    Transakce,
    Vyuctovani,
    TrenerProfil,
    TrenerSazba,
    sazba_trenera_k_datu,
)


class BillingLogicTests(TestCase):
    """Tests for critical billing calculations."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="testcoach", password="test")
        self.hrac = Hrac.objects.create(jmeno="Test", prijmeni="Player", email="test@example.com")
        self.rodina = Rodina.objects.create(nazev="Test Family")
        self.hrac.rodina = self.rodina
        self.hrac.save()

    def test_player_credit_calculation(self):
        """Test player credit calculation."""
        # Initial credit should be 0
        self.assertEqual(self.hrac.kredit, Decimal("0.00"))
        self.assertEqual(self.hrac.zustatek, Decimal("0.00"))

        # Add a charge
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("500.00"),
            popis="Test charge"
        )
        self.hrac.refresh_from_db()
        self.assertEqual(self.hrac.zustatek, Decimal("500.00"))
        self.assertEqual(self.hrac.kredit, Decimal("-500.00"))

        # Add a payment
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.PLATBA,
            castka=Decimal("300.00"),
            popis="Test payment"
        )
        self.hrac.refresh_from_db()
        self.assertEqual(self.hrac.zustatek, Decimal("200.00"))
        self.assertEqual(self.hrac.kredit, Decimal("-200.00"))

    def test_billing_statement_generation(self):
        """Test billing statement generation."""
        # Create some transactions
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("1000.00"),
            popis="Charge 1"
        )
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.PLATBA,
            castka=Decimal("500.00"),
            popis="Payment 1"
        )

        # Generate billing statement
        vyuct = self.hrac.vygeneruj_vyuctovani(
            duvod="manual",
            send_email=False
        )

        self.assertIsNotNone(vyuct)
        self.assertEqual(vyuct.charges_total, Decimal("1000.00"))
        self.assertEqual(vyuct.payments_total, Decimal("500.00"))
        self.assertEqual(vyuct.amount_due, Decimal("500.00"))  # bez override = spočtená částka
        self.hrac.refresh_from_db()
        self.assertIsNotNone(self.hrac.posledni_vyuctovani_at)  # manuál také uzavírá období

    def test_billing_statement_with_override_amount(self):
        """Test billing with override amount."""
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("1000.00"),
            popis="Charge"
        )

        vyuct = self.hrac.vygeneruj_vyuctovani(
            duvod="manual",
            send_email=False,
            override_amount_due=Decimal("800.00")
        )

        self.assertEqual(vyuct.amount_due, Decimal("800.00"))

    def test_manual_billing_empty_defaults_to_debt_and_last_payment(self):
        """Bez data a částky: amount = dluh, období od poslední platby."""
        pay_at = timezone.now() - timedelta(days=10)
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.PLATBA,
            castka=Decimal("2000.00"),
            popis="Platba",
            vytvoreno=pay_at,
        )
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("3240.00"),
            popis="Trénink",
            vytvoreno=timezone.now() - timedelta(days=2),
        )
        self.assertEqual(self.hrac.kredit, Decimal("-1240.00"))

        amount = max(Decimal("0.00"), -self.hrac.kredit)
        period_from = self.hrac.zacatek_obdobi_od_posledni_platby()
        vyuct = self.hrac.vygeneruj_vyuctovani(
            duvod="manual",
            send_email=False,
            override_amount_due=amount,
            override_period_from=period_from,
        )

        self.assertEqual(vyuct.amount_due, Decimal("1240.00"))
        self.assertEqual(
            timezone.localtime(vyuct.period_from).date(),
            timezone.localtime(pay_at).date(),
        )

    def test_castka_k_uhrade_dluh_plus_surplus(self):
        """Hromadné: dluh + surplus; při kladném kreditu jen surplus."""
        self.assertEqual(
            self.hrac.castka_k_uhrade_dluh_plus_surplus(5000),
            Decimal("5000.00"),
        )

        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("250.00"),
            popis="Dluh",
        )
        self.assertEqual(self.hrac.kredit, Decimal("-250.00"))
        self.assertEqual(
            self.hrac.castka_k_uhrade_dluh_plus_surplus(5000),
            Decimal("5250.00"),
        )
        self.assertEqual(
            self.hrac.castka_k_uhrade_dluh_plus_surplus(3000),
            Decimal("3250.00"),
        )

        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.PLATBA,
            castka=Decimal("1000.00"),
            popis="Platba",
        )
        self.assertEqual(self.hrac.kredit, Decimal("750.00"))
        self.assertEqual(
            self.hrac.castka_k_uhrade_dluh_plus_surplus(5000),
            Decimal("5000.00"),
        )

    def test_overview_only_does_not_create_billing_or_close_period(self):
        """Přehled tréninků neuzavírá období a nevytváří Vyuctovani."""
        from core.models import Vyuctovani

        before = self.hrac.posledni_vyuctovani_at
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("660.00"),
            popis="Charge",
        )
        result = self.hrac.vygeneruj_vyuctovani(
            duvod="prehled",
            send_email=False,
            overview_only=True,
        )
        self.assertIsNone(result)
        self.assertEqual(Vyuctovani.objects.filter(hrac=self.hrac).count(), 0)
        self.hrac.refresh_from_db()
        self.assertEqual(self.hrac.posledni_vyuctovani_at, before)

    def test_billing_period_filtering(self):
        """Test that billing correctly filters transactions by period."""
        now = timezone.now()
        past = now - timedelta(days=10)
        future = now + timedelta(days=5)

        # Transaction in past (should be included if period_from is None)
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("500.00"),
            popis="Past charge",
            vytvoreno=past
        )

        # Transaction in future (should not be included)
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("300.00"),
            popis="Future charge",
            vytvoreno=future
        )

        # Generate billing with period_to = now
        vyuct = self.hrac.vygeneruj_vyuctovani(
            duvod="manual",
            send_email=False,
            override_period_to=now
        )

        # Should only include past transaction
        self.assertEqual(vyuct.charges_total, Decimal("500.00"))

    def test_nedoplatek_od_posledni_uzaverky(self):
        """Test calculation of amount due since last billing."""
        # Create initial charge
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("1000.00"),
            popis="Initial charge"
        )

        # Generate first billing (automatic closure updates posledni_vyuctovani_at)
        vyuct1 = self.hrac.vygeneruj_vyuctovani(
            duvod="CASTKA",
            send_email=False
        )
        self.hrac.refresh_from_db()

        # Create new charge after billing
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("500.00"),
            popis="New charge"
        )

        # Check amount due since last billing
        nedoplatek = self.hrac.nedoplatek_od_posledni_uzaverky()
        self.assertEqual(nedoplatek, Decimal("500.00"))


class PricingTests(TestCase):
    """Tests for pricing logic."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="testcoach", password="test")
        self.hrac = Hrac.objects.create(jmeno="Test", prijmeni="Player")
        self.cenik = Cenik.objects.create(
            format=Cenik.Format.SOLO_C,
            kurt=Cenik.Kurt.VENEK,
            cena_za_hodinu=Decimal("500.00"),
            platnost_od=date.today() - timedelta(days=30),
            platnost_do=None
        )

    def test_training_price_calculation(self):
        """Test training price calculation."""
        trening = Trening.objects.create(
            trener=self.user,
            datum=timezone.now(),
            delka_minut=60,
            format=Cenik.Format.SOLO_C,
            kurt=Cenik.Kurt.VENEK
        )

        price = trening.cena_na_hrace()
        self.assertEqual(price, Decimal("500.00"))

    def test_training_price_with_different_duration(self):
        """Test price calculation for different training durations."""
        trening = Trening.objects.create(
            trener=self.user,
            datum=timezone.now(),
            delka_minut=90,
            format=Cenik.Format.SOLO_C,
            kurt=Cenik.Kurt.VENEK
        )

        price = trening.cena_na_hrace()
        # 90 minutes = 1.5 hours * 500 = 750
        self.assertEqual(price, Decimal("750.00"))

    def test_training_price_falls_back_to_billed_amount_when_cenik_expired(self):
        """When ceník no longer covers the training date, show the originally billed amount."""
        from core.models import SystemNastaveni

        # Kalendář musí sedět s kurtem, jinak se částka přepočítá kvůli sezónnímu nesouladu.
        nast = SystemNastaveni.load()
        nast.sezona_venek_od = 1
        nast.sezona_venek_od_den = 1
        nast.sezona_venek_do = 12
        nast.sezona_venek_do_den = 31
        nast.save()

        old_date = date.today() - timedelta(days=10)
        self.cenik.platnost_od = date.today()
        self.cenik.platnost_do = None
        self.cenik.save()

        trening = Trening.objects.create(
            trener=self.user,
            datum=timezone.make_aware(datetime.combine(old_date, datetime.min.time())),
            delka_minut=60,
            format=Cenik.Format.SOLO_C,
            kurt=Cenik.Kurt.VENEK,
        )
        Dochazka.objects.create(
            trening=trening,
            hrac=self.hrac,
            prisel=True,
            castka_nauc=Decimal("500.00"),
        )

        self.assertEqual(trening.cena_na_hrace(), Decimal("500.00"))

    def test_training_price_prefers_billed_amount_over_new_cenik(self):
        """Already billed trainings keep the original charged amount even if ceník price changed."""
        from core.models import SystemNastaveni

        nast = SystemNastaveni.load()
        nast.sezona_venek_od = 1
        nast.sezona_venek_od_den = 1
        nast.sezona_venek_do = 12
        nast.sezona_venek_do_den = 31
        nast.save()

        old_date = date.today() - timedelta(days=10)
        trening = Trening.objects.create(
            trener=self.user,
            datum=timezone.make_aware(datetime.combine(old_date, datetime.min.time())),
            delka_minut=60,
            format=Cenik.Format.CTVRICE_C,
            kurt=Cenik.Kurt.VENEK,
        )
        Dochazka.objects.create(
            trening=trening,
            hrac=self.hrac,
            prisel=True,
            castka_nauc=Decimal("400.00"),
        )

        self.cenik.format = Cenik.Format.CTVRICE_C
        self.cenik.cena_za_hodinu = Decimal("440.00")
        self.cenik.platnost_od = old_date - timedelta(days=30)
        self.cenik.platnost_do = None
        self.cenik.save()

        self.assertEqual(trening.cena_na_hrace(), Decimal("400.00"))

    def test_pricing_period_validation(self):
        """Test that overlapping pricing periods are rejected."""
        # Create first pricing
        Cenik.objects.create(
            format=Cenik.Format.SOLO_C,
            kurt=Cenik.Kurt.VENEK,
            cena_za_hodinu=Decimal("500.00"),
            platnost_od=date.today(),
            platnost_do=None
        )

        # Try to create overlapping pricing
        with self.assertRaises(Exception):  # ValidationError
            cenik2 = Cenik(
                format=Cenik.Format.SOLO_C,
                kurt=Cenik.Kurt.VENEK,
                cena_za_hodinu=Decimal("600.00"),
                platnost_od=date.today() - timedelta(days=10),
                platnost_do=None
            )
            cenik2.full_clean()
            cenik2.save()

    def test_leto_training_keeps_leto_price_in_winter_calendar(self):
        """Zadaná sezóna léto (VENEK) se účtuje letní sazbou i po konci kalendářní sezóny."""
        from core.models import SystemNastaveni

        nast = SystemNastaveni.load()
        nast.sezona_venek_od = 4
        nast.sezona_venek_od_den = 1
        nast.sezona_venek_do = 10
        nast.sezona_venek_do_den = 10
        nast.sezona_automaticky_kurt = True
        nast.save()

        Cenik.objects.all().delete()
        Cenik.objects.create(
            format=Cenik.Format.SOLO_NC,
            kurt=Cenik.Kurt.VENEK,
            cena_za_hodinu=Decimal("690.00"),
            platnost_od=date(2026, 1, 1),
            platnost_do=None,
        )
        Cenik.objects.create(
            format=Cenik.Format.SOLO_NC,
            kurt=Cenik.Kurt.HALA,
            cena_za_hodinu=Decimal("930.00"),
            platnost_od=date(2026, 1, 1),
            platnost_do=None,
        )

        trening = Trening.objects.create(
            trener=self.user,
            datum=timezone.make_aware(datetime(2026, 10, 15, 14, 0)),
            delka_minut=60,
            format=Cenik.Format.SOLO_NC,
            kurt=Cenik.Kurt.VENEK,
        )
        self.assertEqual(SystemNastaveni.kurt_kalendar_pro_datum(date(2026, 10, 15)), Cenik.Kurt.HALA)
        self.assertEqual(trening.cena_pro_nove_nauceni(), Decimal("690.00"))

    def test_zima_training_keeps_zima_price_in_summer_calendar(self):
        """Zadaná sezóna zima (HALA) se účtuje zimní sazbou i v kalendářním létě."""
        from core.models import SystemNastaveni

        nast = SystemNastaveni.load()
        nast.sezona_venek_od = 4
        nast.sezona_venek_od_den = 1
        nast.sezona_venek_do = 10
        nast.sezona_venek_do_den = 31
        nast.sezona_automaticky_kurt = True
        nast.save()

        Cenik.objects.all().delete()
        Cenik.objects.create(
            format=Cenik.Format.SOLO_NC,
            kurt=Cenik.Kurt.VENEK,
            cena_za_hodinu=Decimal("690.00"),
            platnost_od=date(2026, 1, 1),
            platnost_do=None,
        )
        Cenik.objects.create(
            format=Cenik.Format.SOLO_NC,
            kurt=Cenik.Kurt.HALA,
            cena_za_hodinu=Decimal("930.00"),
            platnost_od=date(2026, 1, 1),
            platnost_do=None,
        )

        trening = Trening.objects.create(
            trener=self.user,
            datum=timezone.make_aware(datetime(2026, 8, 15, 11, 0)),
            delka_minut=60,
            format=Cenik.Format.SOLO_NC,
            kurt=Cenik.Kurt.HALA,
        )
        self.assertEqual(SystemNastaveni.kurt_kalendar_pro_datum(date(2026, 8, 15)), Cenik.Kurt.VENEK)
        self.assertEqual(trening.cena_pro_nove_nauceni(), Decimal("930.00"))


class AutomaticBillingTests(TestCase):
    """Tests for automatic billing triggers."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="testcoach", password="test")
        self.hrac = Hrac.objects.create(
            jmeno="Test",
            prijmeni="Player",
            vyuctovani_rezim=Hrac.RezimVyuctovani.N_TRENINGU,
            vyuctovani_n=3
        )
        self.cenik = Cenik.objects.create(
            format=Cenik.Format.SOLO_C,
            kurt=Cenik.Kurt.VENEK,
            cena_za_hodinu=Decimal("500.00"),
            platnost_od=date.today() - timedelta(days=30),
            platnost_do=None
        )

    def _create_dochazka(self, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return Dochazka.objects.create(**kwargs)

    def test_automatic_charge_on_attendance(self):
        """Test that attendance automatically creates charge."""
        trening = Trening.objects.create(
            trener=self.user,
            datum=timezone.now(),
            delka_minut=60,
            format=Cenik.Format.SOLO_C,
            kurt=Cenik.Kurt.VENEK
        )

        # Create attendance
        dochazka = self._create_dochazka(
            trening=trening,
            hrac=self.hrac,
            prisel=True
        )

        # Check that transaction was created
        transakce = Transakce.objects.filter(
            hrac=self.hrac,
            trening=trening,
            typ=Transakce.Typ.NAUCTOVANO
        ).first()

        self.assertIsNotNone(transakce)
        self.assertEqual(transakce.castka, Decimal("500.00"))
        self.assertEqual(dochazka.transakce_nauc, transakce)

    def test_no_charge_when_not_attending(self):
        """Test that no charge is created when player doesn't attend."""
        trening = Trening.objects.create(
            trener=self.user,
            datum=timezone.now(),
            delka_minut=60,
            format=Cenik.Format.SOLO_C,
            kurt=Cenik.Kurt.VENEK
        )

        # Create attendance marked as not present
        Dochazka.objects.create(
            trening=trening,
            hrac=self.hrac,
            prisel=False
        )

        # Check that no transaction was created
        transakce = Transakce.objects.filter(
            hrac=self.hrac,
            trening=trening,
            typ=Transakce.Typ.NAUCTOVANO
        ).first()

        self.assertIsNone(transakce)

    def test_automatic_billing_after_n_trainings(self):
        """Test automatic billing after N trainings."""
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = Hrac.RezimVyuctovani.N_TRENINGU
        nast.auto_pocet_treninku = 3
        nast.save()

        for i in range(3):
            trening = Trening.objects.create(
                trener=self.user,
                datum=timezone.now() + timedelta(days=i),
                delka_minut=60,
                format=Cenik.Format.SOLO_C,
                kurt=Cenik.Kurt.VENEK
            )
            self._create_dochazka(
                trening=trening,
                hrac=self.hrac,
                prisel=True
            )

        # Check that billing was generated after 3rd training
        vyuct = Vyuctovani.objects.filter(hrac=self.hrac).first()
        self.assertIsNotNone(vyuct)
        self.assertEqual(vyuct.reason, Hrac.RezimVyuctovani.N_TRENINGU)

    def test_automatic_billing_at_credit_limit(self):
        """Test automatic billing when total credit hits global limit."""
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = Hrac.RezimVyuctovani.CASTKA
        nast.auto_limit = Decimal("5000.00")
        nast.save()

        self.hrac.email = "test@example.com"
        self.hrac.save()

        for i in range(10):
            trening = Trening.objects.create(
                trener=self.user,
                datum=timezone.now() + timedelta(days=i),
                delka_minut=60,
                format=Cenik.Format.SOLO_C,
                kurt=Cenik.Kurt.VENEK,
            )
            self._create_dochazka(
                trening=trening,
                hrac=self.hrac,
                prisel=True,
            )

        self.hrac.refresh_from_db()
        self.assertEqual(self.hrac.kredit, Decimal("-5000.00"))

        vyuct = Vyuctovani.objects.filter(hrac=self.hrac).order_by("-created_at").first()
        self.assertIsNotNone(vyuct)
        self.assertEqual(vyuct.reason, Hrac.RezimVyuctovani.CASTKA)
        self.assertEqual(vyuct.amount_due, Decimal("5000.00"))
        self.assertEqual(vyuct.credit_end, Decimal("-5000.00"))

    def test_automatic_billing_credit_limit_no_duplicate(self):
        """No second auto billing while credit stays below limit."""
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = Hrac.RezimVyuctovani.CASTKA
        nast.auto_limit = Decimal("5000.00")
        nast.save()

        for i in range(10):
            trening = Trening.objects.create(
                trener=self.user,
                datum=timezone.now() + timedelta(days=i),
                delka_minut=60,
                format=Cenik.Format.SOLO_C,
                kurt=Cenik.Kurt.VENEK,
            )
            self._create_dochazka(trening=trening, hrac=self.hrac, prisel=True)

        self.assertEqual(Vyuctovani.objects.filter(hrac=self.hrac).count(), 1)

        trening11 = Trening.objects.create(
            trener=self.user,
            datum=timezone.now() + timedelta(days=11),
            delka_minut=60,
            format=Cenik.Format.SOLO_C,
            kurt=Cenik.Kurt.VENEK,
        )
        self._create_dochazka(trening=trening11, hrac=self.hrac, prisel=True)

        self.assertEqual(Vyuctovani.objects.filter(hrac=self.hrac).count(), 1)
        self.assertEqual(self.hrac.kredit, Decimal("-5500.00"))

    def test_automatic_billing_credit_limit_after_recovery(self):
        """Re-trigger after payment brings credit above limit and it drops again."""
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = Hrac.RezimVyuctovani.CASTKA
        nast.auto_limit = Decimal("5000.00")
        nast.save()

        for i in range(10):
            trening = Trening.objects.create(
                trener=self.user,
                datum=timezone.now() + timedelta(days=i),
                delka_minut=60,
                format=Cenik.Format.SOLO_C,
                kurt=Cenik.Kurt.VENEK,
            )
            self._create_dochazka(trening=trening, hrac=self.hrac, prisel=True)

        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.PLATBA,
            castka=Decimal("5000.00"),
            popis="Platba",
        )
        self.hrac.refresh_from_db()
        self.assertEqual(self.hrac.kredit, Decimal("0.00"))
        self.assertFalse(self.hrac.auto_castka_ceka_na_obnovu)

        for i in range(10, 20):
            trening = Trening.objects.create(
                trener=self.user,
                datum=timezone.now() + timedelta(days=i),
                delka_minut=60,
                format=Cenik.Format.SOLO_C,
                kurt=Cenik.Kurt.VENEK,
            )
            self._create_dochazka(trening=trening, hrac=self.hrac, prisel=True)

        self.assertEqual(Vyuctovani.objects.filter(hrac=self.hrac).count(), 2)

    def test_automatic_billing_credit_limit_after_deleting_trainings(self):
        """Po smazání tréninků (obnova kreditu) se auto e-mail znovu pošle při dalším limitu."""
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = Hrac.RezimVyuctovani.CASTKA
        nast.auto_limit = Decimal("5000.00")
        nast.save()

        treningy = []
        for i in range(10):
            trening = Trening.objects.create(
                trener=self.user,
                datum=timezone.now() + timedelta(days=i),
                delka_minut=60,
                format=Cenik.Format.SOLO_C,
                kurt=Cenik.Kurt.VENEK,
            )
            self._create_dochazka(trening=trening, hrac=self.hrac, prisel=True)
            treningy.append(trening)

        self.assertEqual(Vyuctovani.objects.filter(hrac=self.hrac).count(), 1)
        self.hrac.refresh_from_db()
        self.assertTrue(self.hrac.auto_castka_ceka_na_obnovu)

        # Smazání části tréninků → kredit stoupne nad limit → odblokování
        for t in treningy[:6]:
            t.delete()

        self.hrac.refresh_from_db()
        self.assertEqual(self.hrac.kredit, Decimal("-2000.00"))
        self.assertFalse(self.hrac.auto_castka_ceka_na_obnovu)

        for i in range(20, 26):
            trening = Trening.objects.create(
                trener=self.user,
                datum=timezone.now() + timedelta(days=i),
                delka_minut=60,
                format=Cenik.Format.SOLO_C,
                kurt=Cenik.Kurt.VENEK,
            )
            self._create_dochazka(trening=trening, hrac=self.hrac, prisel=True)

        self.hrac.refresh_from_db()
        self.assertEqual(self.hrac.kredit, Decimal("-5000.00"))
        self.assertEqual(Vyuctovani.objects.filter(hrac=self.hrac).count(), 2)

    def test_automatic_billing_credit_limit_after_deleting_payments(self):
        """Po smazání plateb a opětovném překročení limitu se auto e-mail pošle znovu."""
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = Hrac.RezimVyuctovani.CASTKA
        nast.auto_limit = Decimal("5000.00")
        nast.save()

        for i in range(10):
            trening = Trening.objects.create(
                trener=self.user,
                datum=timezone.now() + timedelta(days=i),
                delka_minut=60,
                format=Cenik.Format.SOLO_C,
                kurt=Cenik.Kurt.VENEK,
            )
            self._create_dochazka(trening=trening, hrac=self.hrac, prisel=True)

        platba = Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.PLATBA,
            castka=Decimal("5000.00"),
            popis="Platba",
        )
        self.hrac.refresh_from_db()
        self.assertFalse(self.hrac.auto_castka_ceka_na_obnovu)

        # Smazání platby + části tréninků (jako při „resetu“ dat) a nové naúčtování do limitu
        platba.delete()
        for doch in list(self.hrac.dochazky.all())[:6]:
            doch.trening.delete()

        self.hrac.refresh_from_db()
        self.assertEqual(self.hrac.kredit, Decimal("-2000.00"))
        self.assertFalse(self.hrac.auto_castka_ceka_na_obnovu)

        for i in range(30, 36):
            trening = Trening.objects.create(
                trener=self.user,
                datum=timezone.now() + timedelta(days=i),
                delka_minut=60,
                format=Cenik.Format.SOLO_C,
                kurt=Cenik.Kurt.VENEK,
            )
            self._create_dochazka(trening=trening, hrac=self.hrac, prisel=True)

        self.assertEqual(Vyuctovani.objects.filter(hrac=self.hrac).count(), 2)

    def test_automatic_billing_custom_email_amount(self):
        """Configured email amount overrides computed period total."""
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = Hrac.RezimVyuctovani.CASTKA
        nast.auto_limit = Decimal("5000.00")
        nast.auto_castka_k_uhrade = Decimal("3000.00")
        nast.save()

        for i in range(10):
            trening = Trening.objects.create(
                trener=self.user,
                datum=timezone.now() + timedelta(days=i),
                delka_minut=60,
                format=Cenik.Format.SOLO_C,
                kurt=Cenik.Kurt.VENEK,
            )
            self._create_dochazka(trening=trening, hrac=self.hrac, prisel=True)

        vyuct = Vyuctovani.objects.filter(hrac=self.hrac).first()
        self.assertIsNotNone(vyuct)
        self.assertEqual(vyuct.amount_due, Decimal("3000.00"))

    def test_automatic_billing_single_email_on_bulk_trainings(self):
        """Bulk training import in one transaction sends only one email."""
        from django.db import transaction
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = Hrac.RezimVyuctovani.CASTKA
        nast.auto_limit = Decimal("5000.00")
        nast.save()

        self.hrac.email = "test@example.com"
        self.hrac.save()

        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                for i in range(12):
                    trening = Trening.objects.create(
                        trener=self.user,
                        datum=timezone.now() + timedelta(days=i),
                        delka_minut=60,
                        format=Cenik.Format.SOLO_C,
                        kurt=Cenik.Kurt.VENEK,
                    )
                    Dochazka.objects.create(trening=trening, hrac=self.hrac, prisel=True)

        self.assertEqual(Vyuctovani.objects.filter(hrac=self.hrac).count(), 1)

    def test_automatic_billing_manual_mode_disabled(self):
        """Manual mode never triggers automatic billing."""
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = VyuctovaniNastaveni.AutoRezim.MANUAL
        nast.save()

        for i in range(12):
            trening = Trening.objects.create(
                trener=self.user,
                datum=timezone.now() + timedelta(days=i),
                delka_minut=60,
                format=Cenik.Format.SOLO_C,
                kurt=Cenik.Kurt.VENEK,
            )
            self._create_dochazka(trening=trening, hrac=self.hrac, prisel=True)

        self.assertEqual(Vyuctovani.objects.filter(hrac=self.hrac).count(), 0)

    def test_automatic_billing_period_from_first_training_when_no_payment(self):
        """Bez platby: rozpis od prvního tréninku (ne od 3 měsíců zpět)."""
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = Hrac.RezimVyuctovani.CASTKA
        nast.auto_limit = Decimal("5000.00")
        nast.auto_castka_k_uhrade = Decimal("0")
        nast.save()

        self.hrac.posledni_vyuctovani_at = timezone.now() - timedelta(hours=2)
        self.hrac.save()

        old_charge = timezone.now() - timedelta(days=45)
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("6500.00"),
            popis="Starší trénink",
            vytvoreno=old_charge,
        )

        self.hrac.spustit_auto_vyuctovani()

        vyuct = Vyuctovani.objects.filter(hrac=self.hrac).order_by("-created_at").first()
        self.assertIsNotNone(vyuct)
        self.assertEqual(
            timezone.localtime(vyuct.period_from).date(),
            timezone.localtime(old_charge).date(),
        )
        self.assertEqual(vyuct.charges_total, Decimal("6500.00"))

    def test_automatic_billing_period_from_last_payment(self):
        """S platbou: rozpis od poslední platby (včetně platby + tréninků po ní)."""
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = Hrac.RezimVyuctovani.CASTKA
        nast.auto_limit = Decimal("5000.00")
        nast.auto_castka_k_uhrade = Decimal("0")
        nast.save()

        pay_at = timezone.now() - timedelta(days=10)
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.PLATBA,
            castka=Decimal("2000.00"),
            popis="Platba",
            vytvoreno=pay_at,
        )
        charge_at = timezone.now() - timedelta(days=3)
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("7500.00"),
            popis="Tréninky po platbě",
            vytvoreno=charge_at,
        )
        # kredit = 2000 - 7500 = -5500 → pod limitem −5000
        self.assertEqual(self.hrac.kredit, Decimal("-5500.00"))

        self.hrac.spustit_auto_vyuctovani()

        vyuct = Vyuctovani.objects.filter(hrac=self.hrac).order_by("-created_at").first()
        self.assertIsNotNone(vyuct)
        self.assertEqual(
            timezone.localtime(vyuct.period_from).date(),
            timezone.localtime(pay_at).date(),
        )
        self.assertEqual(vyuct.charges_total, Decimal("7500.00"))
        self.assertEqual(vyuct.payments_total, Decimal("2000.00"))


class VyuctovaniNastaveniFormTests(TestCase):
    def test_form_saves_mesicne_without_castka_fields_in_post(self):
        from core.forms import VyuctovaniNastaveniForm
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = VyuctovaniNastaveni.AutoRezim.CASTKA
        nast.auto_limit = Decimal("5000")
        nast.save()

        data = {
            "auto_rezim": VyuctovaniNastaveni.AutoRezim.MESICNE,
            "mesicni_den": "5",
            "auto_posilat_email": "on",
            "email_variant": nast.email_variant,
            "ucet_nazev_1": nast.ucet_nazev_1,
            "ucet_nazev_2": nast.ucet_nazev_2,
            "ucet_nazev_3": nast.ucet_nazev_3,
            "ucet_varianta_1": nast.ucet_varianta_1,
            "ucet_varianta_2": nast.ucet_varianta_2,
            "ucet_varianta_3": nast.ucet_varianta_3,
            "variabilni_symbol_popis": nast.variabilni_symbol_popis,
        }
        form = VyuctovaniNastaveniForm(data, instance=nast)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        nast.refresh_from_db()
        self.assertEqual(nast.auto_rezim, VyuctovaniNastaveni.AutoRezim.MESICNE)
        self.assertEqual(nast.mesicni_den, 5)
        self.assertEqual(nast.auto_limit, Decimal("5000.00"))


class VyuctovaniDeleteSyncTests(TestCase):
    def setUp(self):
        self.hrac = Hrac.objects.create(jmeno="Anna", prijmeni="Šubrtová")

    def test_delete_last_vyuctovani_clears_hrac_closure_state(self):
        vyuct = Vyuctovani.objects.create(
            hrac=self.hrac,
            period_to=timezone.now(),
            amount_due=Decimal("5000.00"),
            credit_end=Decimal("-5000.00"),
            reason="CASTKA",
        )
        self.hrac.posledni_vyuctovani_at = vyuct.created_at
        self.hrac.pocet_treninku_od_vyuctovani = 0
        self.hrac.save()

        vyuct.delete()

        self.hrac.refresh_from_db()
        self.assertIsNone(self.hrac.posledni_vyuctovani_at)

    def test_delete_vyuctovani_restores_previous_closure(self):
        older = Vyuctovani.objects.create(
            hrac=self.hrac,
            period_to=timezone.now() - timedelta(days=30),
            amount_due=Decimal("3000.00"),
            credit_end=Decimal("-3000.00"),
            reason="CASTKA",
        )
        newer = Vyuctovani.objects.create(
            hrac=self.hrac,
            period_to=timezone.now(),
            amount_due=Decimal("5000.00"),
            credit_end=Decimal("-5000.00"),
            reason="CASTKA",
        )
        self.hrac.prepocitat_stav_uzaverky()

        newer.delete()

        self.hrac.refresh_from_db()
        self.assertEqual(self.hrac.posledni_vyuctovani_at, older.created_at)


class CoachRateTests(TestCase):
    """Tests for coach rate calculations."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="testcoach", password="test")
        # Signal _ensure_trener_profil vytvoří profil automaticky – jen upravíme sazbu.
        self.user.trener_profil.sazba_za_hodinu = Decimal("500.00")
        self.user.trener_profil.save()

    def test_default_coach_rate(self):
        """Test default coach rate from profile."""
        rate = sazba_trenera_k_datu(self.user, date.today())
        self.assertEqual(rate, Decimal("500.00"))

    def test_date_based_coach_rate(self):
        """Test date-based coach rate."""
        # Create rate for specific period
        TrenerSazba.objects.create(
            user=self.user,
            platnost_od=date.today() - timedelta(days=10),
            platnost_do=date.today() + timedelta(days=10),
            sazba_za_hodinu=Decimal("600.00")
        )

        rate = sazba_trenera_k_datu(self.user, date.today())
        self.assertEqual(rate, Decimal("600.00"))

    def test_coach_rate_fallback(self):
        """Test coach rate fallback when no profile exists."""
        user2 = User.objects.create_user(username="testcoach2", password="test")
        rate = sazba_trenera_k_datu(user2, date.today())
        # Should fallback to default 500.00
        self.assertEqual(rate, Decimal("500.00"))

    def test_coach_rate_set_rate_from(self):
        """Test setting new rate and closing overlapping periods."""
        # Create initial rate
        rate1 = TrenerSazba.objects.create(
            user=self.user,
            platnost_od=date.today() - timedelta(days=30),
            platnost_do=None,  # Open-ended
            sazba_za_hodinu=Decimal("500.00")
        )

        # Set new rate from today
        rate2 = TrenerSazba.set_rate_from(
            user=self.user,
            effective_from=date.today(),
            rate=Decimal("600.00")
        )

        # Check that old rate was closed
        rate1.refresh_from_db()
        self.assertEqual(rate1.platnost_do, date.today() - timedelta(days=1))

        # Check that new rate is active
        current_rate = sazba_trenera_k_datu(self.user, date.today())
        self.assertEqual(current_rate, Decimal("600.00"))


class CreditCalculationTests(TestCase):
    """Tests for credit calculation edge cases."""

    def setUp(self):
        """Set up test data."""
        self.hrac = Hrac.objects.create(jmeno="Test", prijmeni="Player")

    def test_credit_with_multiple_transactions(self):
        """Test credit calculation with multiple transactions."""
        # Add multiple charges
        for i in range(5):
            Transakce.objects.create(
                hrac=self.hrac,
                typ=Transakce.Typ.NAUCTOVANO,
                castka=Decimal("100.00"),
                popis=f"Charge {i}"
            )

        # Add multiple payments
        for i in range(3):
            Transakce.objects.create(
                hrac=self.hrac,
                typ=Transakce.Typ.PLATBA,
                castka=Decimal("150.00"),
                popis=f"Payment {i}"
            )

        self.hrac.refresh_from_db()
        # 5 * 100 - 3 * 150 = 500 - 450 = 50
        self.assertEqual(self.hrac.zustatek, Decimal("50.00"))
        self.assertEqual(self.hrac.kredit, Decimal("-50.00"))

    def test_credit_with_refund(self):
        """Test credit calculation with refund."""
        # Add charge
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.NAUCTOVANO,
            castka=Decimal("500.00"),
            popis="Charge"
        )

        # Add refund
        Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.VRATKA,
            castka=Decimal("100.00"),
            popis="Refund"
        )

        self.hrac.refresh_from_db()
        # 500 - 100 = 400
        self.assertEqual(self.hrac.zustatek, Decimal("400.00"))
        self.assertEqual(self.hrac.kredit, Decimal("-400.00"))

    def test_empty_credit(self):
        """Test credit when no transactions exist."""
        self.assertEqual(self.hrac.kredit, Decimal("0.00"))
        self.assertEqual(self.hrac.zustatek, Decimal("0.00"))

# --- ZDE VLOŽTE NOVÝ TEST (pozor na odsazení) ---
    def test_admin_sql_credit_matches_model_logic(self):
        """Ověří, že SQL výpočet v Adminu dává stejné číslo jako Python logika v Modelu."""
        # 1. Vytvoříme transakce
        Transakce.objects.create(hrac=self.hrac, typ=Transakce.Typ.NAUCTOVANO, castka=Decimal("1000"))
        Transakce.objects.create(hrac=self.hrac, typ=Transakce.Typ.PLATBA, castka=Decimal("400"))
        
        # 2. Spustíme stejnou query jako dělá Admin
        from django.db.models import Sum, Case, When, F, Value, DecimalField
        qs = Hrac.objects.filter(pk=self.hrac.pk).annotate(
            _kredit_sql=Sum(
                Case(
                    When(transakce__typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA], then=F("transakce__castka")),
                    When(transakce__typ=Transakce.Typ.NAUCTOVANO, then=-F("transakce__castka")),
                    default=Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
        )
        hrac_z_db = qs.first()

        # 3. Python výpočet (property v modelu)
        self.hrac.refresh_from_db()
        python_kredit = self.hrac.kredit

        # 4. Porovnání
        # SQL vrací -600 (kredit), Python vrací -600 (kredit)
        self.assertEqual(hrac_z_db._kredit_sql, python_kredit)


class ChangelistSearchTests(TestCase):
    """Vyhledávání v admin changelistu – datum a jméno."""

    def setUp(self):
        self.coach = User.objects.create_user(
            username="JanNovak",
            password="x",
            first_name="Jan",
            last_name="Novák",
        )
        self.hrac = Hrac.objects.create(jmeno="Petr", prijmeni="Svoboda", email="petr@example.com")
        self.training_day = timezone.make_aware(datetime(2025, 6, 7, 10, 0))
        self.other_day = timezone.make_aware(datetime(2025, 7, 15, 14, 0))
        self.trening_june = Trening.objects.create(
            trener=self.coach,
            datum=self.training_day,
            delka_minut=60,
            format=Cenik.Format.SOLO_C,
            kurt=Cenik.Kurt.VENEK,
            poznamka="ranní trénink",
        )
        self.trening_july = Trening.objects.create(
            trener=self.coach,
            datum=self.other_day,
            delka_minut=60,
            format=Cenik.Format.SOLO_C,
            kurt=Cenik.Kurt.VENEK,
        )
        Dochazka.objects.create(trening=self.trening_june, hrac=self.hrac, prisel=True)
        self.platba = Transakce.objects.create(
            hrac=self.hrac,
            typ=Transakce.Typ.PLATBA,
            castka=Decimal("500"),
            popis="platba červen",
            vytvoreno=self.training_day,
        )
        self.vyuctovani = Vyuctovani.objects.create(
            hrac=self.hrac,
            period_from=self.training_day,
            period_to=self.other_day,
            amount_due=Decimal("100"),
            reason="manual",
        )

    def test_parse_czech_date_parts_numeric(self):
        from core.admin_utils import parse_czech_date_parts

        parts = parse_czech_date_parts("7.6.2025")
        self.assertEqual(parts.day, 7)
        self.assertEqual(parts.month, 6)
        self.assertEqual(parts.year, 2025)

        parts_no_year = parse_czech_date_parts("7.6")
        self.assertEqual(parts_no_year.day, 7)
        self.assertEqual(parts_no_year.month, 6)
        self.assertIsNone(parts_no_year.year)

    def test_czech_name_ordering_puts_caron_after_base_letter(self):
        from core.admin_utils import czech_order_expr, czech_sort_key
        from core.models import Hrac

        names = ["Cattaneo", "Černý", "Dvořák", "Havel", "Chmel", "Ivan"]
        self.assertEqual(sorted(names, key=czech_sort_key), names)

        for name in names:
            Hrac.objects.get_or_create(jmeno="Test", prijmeni=name)

        ordered = list(
            Hrac.objects.filter(jmeno="Test", prijmeni__in=names)
            .order_by(czech_order_expr("prijmeni"), "id")
            .values_list("prijmeni", flat=True)
        )
        self.assertEqual(ordered, names)

    def test_trening_search_by_date_and_name(self):
        from core.admin.trening import TreningAdmin
        from core.models import Trening

        admin = TreningAdmin(Trening, None)
        qs = Trening.objects.all()

        date_qs, _ = admin.get_search_results(None, qs, "7.6.2025")
        self.assertEqual(list(date_qs), [self.trening_june])

        name_qs, _ = admin.get_search_results(None, qs, "Svoboda")
        self.assertIn(self.trening_june, list(name_qs))

    def test_transakce_search_by_date(self):
        from core.admin.transakce import TransakceAdmin
        from core.models import Transakce

        admin = TransakceAdmin(Transakce, None)
        qs = admin.get_queryset(None)
        found, _ = admin.get_search_results(None, qs, "7.6.2025")
        self.assertIn(self.platba, list(found))

    def test_vyuctovani_search_by_date(self):
        from core.admin.vyuctovani import VyuctovaniAdmin
        from core.models import Vyuctovani

        admin = VyuctovaniAdmin(Vyuctovani, None)
        qs = Vyuctovani.objects.all()
        found, _ = admin.get_search_results(None, qs, "7.6.2025")
        self.assertIn(self.vyuctovani, list(found))

    def test_trening_search_clear_returns_all(self):
        from core.admin.trening import TreningAdmin
        from core.models import Trening

        admin = TreningAdmin(Trening, None)
        qs = Trening.objects.all()
        filtered, _ = admin.get_search_results(None, qs, "7.6.2025")
        self.assertEqual(filtered.count(), 1)

        cleared, _ = admin.get_search_results(None, qs, "")
        self.assertEqual(cleared.count(), 2)


class SystemNastaveniTests(TestCase):
    def _form_data(self, **overrides):
        from core.models import SystemNastaveni

        nast = SystemNastaveni.load()
        data = {
            "nazev_klubu": nast.nazev_klubu,
            "slogan": nast.slogan,
            "kontakt_email": nast.kontakt_email,
            "kontakt_telefon": nast.kontakt_telefon,
            "kontakt_adresa": nast.kontakt_adresa,
            "email_jmeno": nast.from_email_parts()[0],
            "email_adresa": nast.from_email_parts()[1],
            "email_oznaceni": nast.subject_tag_display(),
            "email_podpis": nast.email_podpis,
            "tmavy_rezim": nast.tmavy_rezim,
            "barevna_varianta": nast.barevna_varianta,
            "vychozi_delka_minut": nast.vychozi_delka_minut,
            "vychozi_kurt": nast.vychozi_kurt,
            "pronajem_ceny": nast.pronajem_ceny or "420,440,530,580",
            "pronajem_ceny_venek": getattr(nast, "pronajem_ceny_venek", None) or "220,250",
            "staly_pronajem_od": (
                nast.staly_pronajem_od.isoformat()
                if getattr(nast, "staly_pronajem_od", None)
                else "2026-10-10"
            ),
            "staly_pronajem_do": (
                nast.staly_pronajem_do.isoformat()
                if getattr(nast, "staly_pronajem_do", None)
                else "2027-04-09"
            ),
            "sezona_automaticky_kurt": nast.sezona_automaticky_kurt,
            "sezona_venek_od": nast.sezona_venek_od,
            "sezona_venek_od_den": nast.sezona_venek_od_den,
            "sezona_venek_do": nast.sezona_venek_do,
            "sezona_venek_do_den": nast.sezona_venek_do_den,
            "rozvrh_od_hodina": nast.rozvrh_od_hodina,
            "rozvrh_do_hodina": nast.rozvrh_do_hodina,
            "vychozi_zobrazeni_rozvrhu": nast.vychozi_zobrazeni_rozvrhu,
            "prah_dluhu_dashboard": nast.prah_dluhu_dashboard,
            "zvyraznit_zaporny_kredit": nast.zvyraznit_zaporny_kredit,
            "radku_na_stranku": nast.radku_na_stranku,
        }
        data.update(overrides)
        return data

    def test_schedule_hours_respects_range(self):
        from core.forms import SystemNastaveniForm
        from core.models import SystemNastaveni

        nast = SystemNastaveni.load()
        nast.rozvrh_od_hodina = 7
        nast.rozvrh_do_hodina = 21
        nast.save(sync_colors=False)

        self.assertEqual(nast.schedule_hours(), list(range(7, 22)))
        self.assertEqual(nast.schedule_hour_count, 15)

    def test_form_rejects_invalid_schedule_range(self):
        from core.forms import SystemNastaveniForm

        form = SystemNastaveniForm(data=self._form_data(rozvrh_od_hodina=10, rozvrh_do_hodina=10))
        self.assertFalse(form.is_valid())
        self.assertIn("rozvrh_do_hodina", form.errors)

    def test_training_defaults_from_settings(self):
        from core.models import Cenik, SystemNastaveni

        nast = SystemNastaveni.load()
        nast.vychozi_delka_minut = 90
        nast.vychozi_kurt = Cenik.Kurt.HALA
        nast.sezona_automaticky_kurt = False
        nast.save(sync_colors=False)

        defaults = SystemNastaveni.training_defaults()
        self.assertEqual(defaults["delka_minut"], 90)
        self.assertEqual(defaults["kurt"], Cenik.Kurt.HALA)

    def test_training_defaults_respect_season_toggle(self):
        from datetime import date
        from core.models import Cenik, SystemNastaveni

        nast = SystemNastaveni.load()
        nast.vychozi_kurt = Cenik.Kurt.HALA
        nast.sezona_automaticky_kurt = True
        nast.sezona_venek_od = 4
        nast.sezona_venek_od_den = 15
        nast.sezona_venek_do = 10
        nast.sezona_venek_do_den = 15
        nast.save(sync_colors=False)

        self.assertEqual(
            SystemNastaveni.training_defaults(for_date=date(2026, 7, 1))["kurt"],
            Cenik.Kurt.VENEK,
        )
        self.assertEqual(
            SystemNastaveni.training_defaults(for_date=date(2026, 4, 14))["kurt"],
            Cenik.Kurt.HALA,
        )
        self.assertEqual(
            SystemNastaveni.training_defaults(for_date=date(2026, 4, 15))["kurt"],
            Cenik.Kurt.VENEK,
        )
        self.assertEqual(
            SystemNastaveni.training_defaults(for_date=date(2026, 1, 1))["kurt"],
            Cenik.Kurt.HALA,
        )

        nast.sezona_automaticky_kurt = False
        nast.save(sync_colors=False)
        self.assertEqual(
            SystemNastaveni.training_defaults(for_date=date(2026, 7, 1))["kurt"],
            Cenik.Kurt.HALA,
        )

    def test_season_month_selects_render_choices(self):
        from core.forms import SystemNastaveniForm
        from core.models import SystemNastaveni

        form = SystemNastaveniForm(instance=SystemNastaveni.load())
        html = str(form["sezona_venek_od"])
        self.assertIn("<option", html)
        self.assertIn('value="4"', html)
        self.assertIn("selected", html.lower())
        den_html = str(form["sezona_venek_od_den"])
        self.assertIn('value="1"', den_html)

    def test_home_uses_club_name_and_contact(self):
        from core.models import SystemNastaveni
        from core.views import home
        from django.test import RequestFactory

        nast = SystemNastaveni.load()
        nast.nazev_klubu = "Testovací klub"
        nast.kontakt_email = "klub@example.com"
        nast.kontakt_telefon = "+420 123 456"
        nast.save(sync_colors=False)

        request = RequestFactory().get("/")
        response = home(request)
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Testovací klub", content)
        self.assertIn("klub@example.com", content)
        self.assertIn("+420 123 456", content)

    def test_seasonal_kurt_in_summer(self):
        from datetime import date
        from core.models import Cenik, SystemNastaveni

        nast = SystemNastaveni.load()
        nast.sezona_automaticky_kurt = True
        nast.sezona_venek_od = 4
        nast.sezona_venek_od_den = 1
        nast.sezona_venek_do = 10
        nast.sezona_venek_do_den = 31
        nast.save(sync_colors=False)

        self.assertEqual(nast.kurt_pro_datum(date(2026, 7, 15)), Cenik.Kurt.VENEK)
        self.assertEqual(nast.kurt_pro_datum(date(2026, 1, 15)), Cenik.Kurt.HALA)
        self.assertEqual(nast.kurt_pro_datum(date(2026, 4, 1)), Cenik.Kurt.VENEK)
        self.assertEqual(nast.kurt_pro_datum(date(2026, 10, 31)), Cenik.Kurt.VENEK)
        self.assertEqual(nast.kurt_pro_datum(date(2026, 11, 1)), Cenik.Kurt.HALA)

    def test_email_subject_prefix(self):
        from core.models import SystemNastaveni

        self.assertEqual(
            SystemNastaveni.compose_subject_prefix("Tenis Čimice"),
            "[Tenis Čimice] ",
        )
        nast = SystemNastaveni.load()
        nast.email_predmet_prefix = "[Klub] "
        nast.save(sync_colors=False)
        self.assertEqual(nast.subject_tag_display(), "Klub")
        self.assertEqual(
            nast.format_email_subject("Test"),
            "[Klub] Test",
        )
        nast.email_predmet_prefix = SystemNastaveni.compose_subject_prefix("Nový klub")
        nast.save(sync_colors=False)
        self.assertEqual(
            nast.format_email_subject("Test"),
            "[Nový klub] Test",
        )

    def test_from_email_parts(self):
        from core.models import SystemNastaveni

        nast = SystemNastaveni(email_odesilatel="Tenis Čimice <kptenis@volny.cz>")
        jmeno, adresa = nast.from_email_parts()
        self.assertEqual(jmeno, "Tenis Čimice")
        self.assertEqual(adresa, "kptenis@volny.cz")
        self.assertEqual(
            SystemNastaveni.compose_from_email("Tenis Čimice", "kptenis@volny.cz"),
            "Tenis Čimice <kptenis@volny.cz>",
        )

    def test_vzhled_ajax_save(self):
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from core.admin_views import admin_nastaveni_vzhled_view
        from core.models import SystemNastaveni, UzivatelskyVzhled

        user = get_user_model().objects.create_superuser("admin", "admin@test.com", "pass")
        nast_before = SystemNastaveni.load()
        club_variant = nast_before.barevna_varianta
        club_dark = nast_before.tmavy_rezim

        request = RequestFactory().post(
            "/admin/nastaveni/vzhled/",
            {"barevna_varianta": "modra", "tmavy_rezim": "true"},
        )
        request.user = user

        resp = admin_nastaveni_vzhled_view(request)
        self.assertEqual(resp.status_code, 200)
        import json
        data = json.loads(resp.content)
        self.assertTrue(data["ok"])
        self.assertEqual(data["barevna_varianta"], "modra")
        self.assertTrue(data["tmavy_rezim"])
        self.assertIn("--brand: #2563EB", data["theme_style"])

        vzhled = UzivatelskyVzhled.objects.get(user=user)
        self.assertEqual(vzhled.barevna_varianta, "modra")
        self.assertTrue(vzhled.tmavy_rezim)

        nast = SystemNastaveni.load()
        self.assertEqual(nast.barevna_varianta, club_variant)
        self.assertEqual(nast.tmavy_rezim, club_dark)

    def test_user_appearance_overrides_system_theme(self):
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from core.context_processors import system_nastaveni
        from core.models import SystemNastaveni, UzivatelskyVzhled

        user = get_user_model().objects.create_superuser("themeuser", "tu@test.com", "pass")
        nast = SystemNastaveni.load()
        nast.barevna_varianta = "oranzova"
        nast.tmavy_rezim = False
        nast.save(sync_colors=True)

        UzivatelskyVzhled.objects.create(
            user=user,
            barevna_varianta="modra",
            tmavy_rezim=True,
        )

        request = RequestFactory().get("/admin/")
        request.user = user
        ctx = system_nastaveni(request)
        self.assertEqual(ctx["system_theme_variant"], "modra")
        self.assertTrue(ctx["system_tmavy_rezim"])
        self.assertEqual(ctx["system_theme_colors"]["brand"], "#2563EB")
        self.assertEqual(ctx["system_theme_state"]["mode"], "dark")

    def test_resolve_theme_ignores_stale_barva_fields(self):
        from core.models import SystemNastaveni
        from core.system_theme import resolve_theme_colors

        nast = SystemNastaveni.load()
        nast.barevna_varianta = "zelena"
        nast.barva_brand = "#E67817"
        nast.vlastni_barvy = False
        nast.save(sync_colors=False)

        colors = resolve_theme_colors(nast)
        self.assertEqual(colors["brand"], "#14833B")

    def test_changelist_includes_global_theme(self):
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from core.models import SystemNastaveni, Trening
        from django.contrib import admin

        user = get_user_model().objects.create_superuser("admin2", "a2@test.com", "pass")
        nast = SystemNastaveni.load()
        nast.barevna_varianta = "modra"
        nast.tmavy_rezim = True
        nast.save(sync_colors=True)

        request = RequestFactory().get("/admin/core/trening/")
        request.user = user
        ma = admin.site._registry[Trening]
        response = ma.changelist_view(request)
        response.render()
        html = response.content.decode()

        self.assertNotIn("admin/css/dark_mode.css", html)
        self.assertIn("system-theme-state", html)
        self.assertIn("--brand: #2563EB", html)
        self.assertIn("admin/js/theme.js", html)

    def test_autosave_ajax(self):
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from core.admin_views import admin_nastaveni_autosave_view
        from core.models import SystemNastaveni

        user = get_user_model().objects.create_superuser("admin3", "a3@test.com", "pass")
        nast = SystemNastaveni.load()
        request = RequestFactory().post(
            "/admin/nastaveni/ulozit/",
            {
                "nazev_klubu": "Test klub AJAX",
                "slogan": nast.slogan or "",
                "kontakt_email": nast.kontakt_email or "",
                "kontakt_telefon": nast.kontakt_telefon or "",
                "kontakt_adresa": nast.kontakt_adresa or "",
                "email_podpis": nast.email_podpis or "",
                "email_jmeno": "",
                "email_adresa": "",
                "email_oznaceni": "",
                "barevna_varianta": nast.barevna_varianta or "oranzova",
                "vychozi_delka_minut": str(nast.vychozi_delka_minut or 60),
                "vychozi_kurt": nast.vychozi_kurt or "HALA",
                "pronajem_ceny": nast.pronajem_ceny or "420,440,530,580",
                "pronajem_ceny_venek": getattr(nast, "pronajem_ceny_venek", None) or "220,250",
                "staly_pronajem_od": (
                    nast.staly_pronajem_od.isoformat()
                    if getattr(nast, "staly_pronajem_od", None)
                    else "2026-10-10"
                ),
                "staly_pronajem_do": (
                    nast.staly_pronajem_do.isoformat()
                    if getattr(nast, "staly_pronajem_do", None)
                    else "2027-04-09"
                ),
                "sezona_venek_od": str(nast.sezona_venek_od or 4),
                "sezona_venek_od_den": str(getattr(nast, "sezona_venek_od_den", None) or 1),
                "sezona_venek_do": str(nast.sezona_venek_do or 10),
                "sezona_venek_do_den": str(getattr(nast, "sezona_venek_do_den", None) or 31),
                "rozvrh_od_hodina": str(nast.rozvrh_od_hodina or 6),
                "rozvrh_do_hodina": str(nast.rozvrh_do_hodina or 22),
                "vychozi_zobrazeni_rozvrhu": nast.vychozi_zobrazeni_rozvrhu or "tyden",
                "prah_dluhu_dashboard": str(nast.prah_dluhu_dashboard or 0),
                "radku_na_stranku": str(nast.radku_na_stranku or 50),
            },
        )
        request.user = user

        resp = admin_nastaveni_autosave_view(request)
        self.assertEqual(resp.status_code, 200)
        import json
        data = json.loads(resp.content)
        self.assertTrue(data["ok"])
        self.assertEqual(data["nazev_klubu"], "Test klub AJAX")

        nast.refresh_from_db()
        self.assertEqual(nast.nazev_klubu, "Test klub AJAX")

    def test_debt_threshold_filter(self):
        from decimal import Decimal
        from django.db.models import Sum, Case, When, F, Value, DecimalField
        from core.models import Hrac, SystemNastaveni, Transakce

        nast = SystemNastaveni.load()
        nast.prah_dluhu_dashboard = Decimal("-500")
        nast.save(sync_colors=False)

        qs = Hrac.objects.annotate(
            _kredit_calculated=Sum(
                Case(
                    When(transakce__typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA], then=F("transakce__castka")),
                    When(transakce__typ=Transakce.Typ.NAUCTOVANO, then=-F("transakce__castka")),
                    default=Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
        ).filter(_kredit_calculated__isnull=False)

        filtered = list(nast.filter_debtors(qs).values_list("_kredit_calculated", flat=True))
        for val in filtered:
            self.assertLessEqual(val, Decimal("-500"))

class RolesAndImportGuardTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group, User
        from core.roles import CLUB_ADMIN_GROUP, CLUB_COACH_GROUP, ensure_role_groups

        ensure_role_groups()
        self.platform = User.objects.create_superuser("platform", "p@example.com", "x")
        self.club = User.objects.create_user("club", "c@example.com", "x", is_staff=True)
        self.club.groups.add(Group.objects.get(name=CLUB_ADMIN_GROUP))
        self.coach = User.objects.create_user("coach", "coach@example.com", "x", is_staff=True)
        self.coach.groups.add(Group.objects.get(name=CLUB_COACH_GROUP))
        self.admin_user = User.objects.create_superuser(
            "AdamPeterka", "admin@example.com", "x"
        )

    def test_platform_vs_club_permissions(self):
        from core.roles import (
            can_access_cenik,
            can_access_hraci,
            can_access_platby,
            can_export_data,
            can_import_data,
            can_manage_users,
            is_club_admin,
            is_club_coach,
            is_platform_admin,
            is_system_admin,
        )

        self.assertTrue(is_platform_admin(self.platform))
        self.assertTrue(is_club_admin(self.platform))
        self.assertTrue(can_import_data(self.platform))
        self.assertTrue(can_export_data(self.platform))
        self.assertTrue(can_manage_users(self.platform))

        self.assertFalse(is_platform_admin(self.club))
        self.assertTrue(is_club_admin(self.club))
        self.assertFalse(can_import_data(self.club))
        self.assertFalse(can_export_data(self.club))
        self.assertFalse(can_manage_users(self.club))

        self.assertTrue(is_system_admin(self.admin_user))
        self.assertTrue(is_platform_admin(self.admin_user))
        self.assertTrue(can_manage_users(self.admin_user))

        self.assertFalse(is_club_admin(self.coach))
        self.assertTrue(is_club_coach(self.coach))
        self.assertTrue(can_access_hraci(self.coach))
        self.assertFalse(can_access_cenik(self.coach))
        self.assertFalse(can_access_platby(self.coach))
        self.assertFalse(can_manage_users(self.coach))

        from core.roles import can_access_analytika, can_access_nastaveni, nastaveni_allowed_panels

        self.assertTrue(can_access_analytika(self.platform))
        self.assertTrue(can_access_analytika(self.admin_user))
        self.assertFalse(can_access_analytika(self.club))
        self.assertFalse(can_access_analytika(self.coach))
        self.assertTrue(can_access_cenik(self.club))
        self.assertFalse(can_access_platby(self.club))
        self.assertTrue(can_access_hraci(self.club))
        self.assertTrue(can_access_nastaveni(self.coach))
        self.assertEqual(
            nastaveni_allowed_panels(self.coach),
            frozenset({"obecne", "vzhled", "uzivatele"}),
        )
        self.assertEqual(
            nastaveni_allowed_panels(self.club),
            frozenset({"obecne", "vzhled", "uzivatele"}),
        )
        self.assertNotIn("provoz", nastaveni_allowed_panels(self.club))
        self.assertIn("provoz", nastaveni_allowed_panels(self.platform))
        self.assertIn("uzivatele", nastaveni_allowed_panels(self.platform))

    def test_platform_admin_keeps_full_access_with_club_group(self):
        """Admin/Provozovatel mají i club_admin skupinu — nesmí to omezit UI."""
        from django.contrib.auth.models import Group
        from core.roles import (
            CLUB_ADMIN_GROUP,
            can_access_analytika,
            can_access_platby,
            can_view_finance,
            nastaveni_allowed_panels,
            nav_permissions,
        )

        self.platform.groups.add(Group.objects.get(name=CLUB_ADMIN_GROUP))
        self.admin_user.groups.add(Group.objects.get(name=CLUB_ADMIN_GROUP))

        for user in (self.platform, self.admin_user):
            self.assertTrue(can_view_finance(user))
            self.assertTrue(can_access_platby(user))
            self.assertTrue(can_access_analytika(user))
            self.assertIn("provoz", nastaveni_allowed_panels(user))
            nav = nav_permissions(user)
            self.assertTrue(nav["nav_platby"])
            self.assertTrue(nav["nav_vyuctovani"])
            self.assertTrue(nav["nav_analytika"])

    def test_import_blocked_on_non_sqlite(self):
        from unittest.mock import patch
        from core.data_import import ImportNotAllowed, assert_full_db_import_allowed

        with patch("core.data_import.settings") as mock_settings:
            mock_settings.DATABASES = {
                "default": {"ENGINE": "django.db.backends.postgresql"}
            }
            with self.assertRaises(ImportNotAllowed):
                assert_full_db_import_allowed()

    def test_email_variant_labels_are_configurable(self):
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.ucet_nazev_1 = "Hlavní účet"
        nast.ucet_nazev_2 = "Vedlejší účet"
        nast.ucet_nazev_3 = "Účet Adam"
        nast.ucet_varianta_3 = "2111286178/2700"
        nast.save()
        self.assertEqual(nast.email_variant_label("1"), "Hlavní účet")
        self.assertEqual(nast.email_variant_label("3"), "Účet Adam")
        self.assertEqual(nast.get_email_variant_display(), "Hlavní účet")
        self.assertEqual(nast.cislo_uctu_pro_variantu("3"), "2111286178/2700")
        self.assertIn(("3", "Účet Adam"), nast.email_variant_choices())


class NeonFriendlyRuntimeTests(TestCase):
    """Spojení se zavírá, health check nechodí do DB, nastavení se cachuje."""

    def test_healthz_returns_ok_without_queries(self):
        with self.assertNumQueries(0):
            response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertTrue(response["Content-Type"].startswith("text/plain"))

    def test_healthz_trailing_slash_without_queries(self):
        with self.assertNumQueries(0):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_postgres_defaults_close_connections(self):
        import dj_database_url
        from django.conf import settings

        parsed = dj_database_url.config(
            default="postgres://user:pass@localhost:5432/db",
            conn_max_age=int("0"),
            conn_health_checks=False,
        )
        self.assertEqual(parsed["CONN_MAX_AGE"], 0)
        self.assertFalse(parsed.get("CONN_HEALTH_CHECKS", False))
        self.assertEqual(
            settings.CACHES["default"]["BACKEND"],
            "django.core.cache.backends.locmem.LocMemCache",
        )
        self.assertEqual(
            settings.MIDDLEWARE[0],
            "core.middleware.HealthCheckMiddleware",
        )

    def test_system_nastaveni_save_invalidates_cache(self):
        from django.core.cache import cache
        from core.models import SystemNastaveni
        from core.singleton_cache import cache_key

        nast = SystemNastaveni.load()
        nast.nazev_klubu = "Cached Club"
        cache.set(cache_key(SystemNastaveni), nast, 3600)

        nast.nazev_klubu = "New Club"
        nast.save(sync_colors=False)

        loaded = SystemNastaveni.load()
        self.assertEqual(loaded.nazev_klubu, "New Club")

    def test_vyuctovani_nastaveni_save_invalidates_cache(self):
        from django.core.cache import cache
        from core.models import VyuctovaniNastaveni
        from core.singleton_cache import cache_key

        nast = VyuctovaniNastaveni.load()
        nast.ucet_nazev_1 = "Cached účet"
        cache.set(cache_key(VyuctovaniNastaveni), nast, 3600)

        nast.ucet_nazev_1 = "Nový účet"
        nast.save()

        loaded = VyuctovaniNastaveni.load()
        self.assertEqual(loaded.ucet_nazev_1, "Nový účet")


class PronajemTests(TestCase):
    """Pronájmy kurtu/haly – cena z ceníku, oprávnění, analytika."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from core.roles import CLUB_ADMIN_GROUP, ensure_role_groups
        from core.models import Pronajem

        ensure_role_groups()
        self.platform = User.objects.create_superuser("plat_admin", "pa@example.com", "x")
        self.club = User.objects.create_user("club_staff", "cs@example.com", "x", is_staff=True)
        self.club.groups.add(Group.objects.get(name=CLUB_ADMIN_GROUP))

        self.cenik = Cenik.objects.create(
            format=Pronajem.FORMAT_DEFAULT,
            kurt=Cenik.Kurt.HALA,
            cena_za_hodinu=Decimal("400.00"),
            platnost_od=date(2020, 1, 1),
        )

    def test_cena_z_ceniku(self):
        from core.models import Pronajem

        cena = Pronajem.cena_z_ceniku(
            datum=date(2026, 10, 19),
            kurt=Cenik.Kurt.HALA,
            delka_minut=90,
        )
        self.assertEqual(cena, Decimal("600.00"))

    def test_pronajem_ceny_from_nastaveni(self):
        from core.models import SystemNastaveni

        nast = SystemNastaveni.load()
        nast.pronajem_ceny = "420,440,530,580"
        nast.pronajem_ceny_venek = "220,250"
        nast.save(sync_colors=False)
        ceny = SystemNastaveni.pronajem_ceny_choices(Cenik.Kurt.HALA)
        self.assertEqual(ceny, [
            Decimal("420.00"),
            Decimal("440.00"),
            Decimal("530.00"),
            Decimal("580.00"),
        ])
        self.assertEqual(
            SystemNastaveni.pronajem_ceny_choices(Cenik.Kurt.VENEK),
            [Decimal("220.00"), Decimal("250.00")],
        )

        nast.pronajem_ceny = "500,600"
        nast.pronajem_ceny_venek = "200,230"
        nast.save(sync_colors=False)
        self.assertEqual(
            SystemNastaveni.pronajem_ceny_choices(Cenik.Kurt.HALA),
            [Decimal("500.00"), Decimal("600.00")],
        )
        self.assertEqual(
            SystemNastaveni.pronajem_ceny_choices(Cenik.Kurt.VENEK),
            [Decimal("200.00"), Decimal("230.00")],
        )

    def test_staly_pronajem_platnost(self):
        from core.models import SystemNastaveni
        from core.predpokladany_pronajem import create_pronajem_from_staly_slot
        from core.models import StalyPronajemSlot

        nast = SystemNastaveni.load()
        nast.staly_pronajem_od = date(2026, 10, 10)
        nast.staly_pronajem_do = date(2027, 4, 9)
        nast.save(sync_colors=False)

        self.assertTrue(nast.staly_pronajem_platny(date(2026, 10, 10)))
        self.assertTrue(nast.staly_pronajem_platny(date(2027, 4, 9)))
        self.assertFalse(nast.staly_pronajem_platny(date(2026, 10, 9)))
        self.assertFalse(nast.staly_pronajem_platny(date(2027, 4, 10)))

        slot = StalyPronajemSlot.objects.create(
            den=0,
            cas_od=datetime.strptime("10:00", "%H:%M").time(),
            delka_minut=60,
            kurt=Cenik.Kurt.HALA,
            kurt_misto="HALA_1",
            rezervujici="Test",
            cena=Decimal("420.00"),
        )
        self.assertIsNone(create_pronajem_from_staly_slot(slot, date(2026, 10, 9)))
        obj = create_pronajem_from_staly_slot(slot, date(2026, 10, 12))  # pondělí
        # 12.10.2026 is Monday
        self.assertIsNotNone(obj)
        self.assertEqual(obj.rezervujici, "Test")

        from core.predpokladany_pronajem import backfill_pronajem_from_staly_slot
        from unittest.mock import patch

        slot2 = StalyPronajemSlot.objects.create(
            den=1,  # úterý
            cas_od=datetime.strptime("13:30", "%H:%M").time(),
            delka_minut=120,
            kurt=Cenik.Kurt.HALA,
            kurt_misto="HALA_1",
            rezervujici="Macecha",
            cena=Decimal("840.00"),
        )
        with patch(
            "core.predpokladany_pronajem.dj_tz.localdate",
            return_value=date(2026, 10, 22),
        ):
            result = backfill_pronajem_from_staly_slot(slot2)
        # úterky 13.10. a 20.10. v platnosti do 22.10.
        self.assertEqual(result["created"], 2)
        from core.models import Pronajem

        self.assertEqual(
            Pronajem.objects.filter(rezervujici="Macecha").count(),
            2,
        )

        # Více kurtů ve stejný čas se musí zapsat všechny
        slot_a = StalyPronajemSlot.objects.create(
            den=2,
            cas_od=datetime.strptime("14:00", "%H:%M").time(),
            delka_minut=60,
            kurt=Cenik.Kurt.HALA,
            kurt_misto="HALA_2",
            rezervujici="Petera",
            cena=Decimal("580.00"),
        )
        slot_b = StalyPronajemSlot.objects.create(
            den=2,
            cas_od=datetime.strptime("14:00", "%H:%M").time(),
            delka_minut=60,
            kurt=Cenik.Kurt.HALA,
            kurt_misto="HALA_4",
            rezervujici="Peter",
            cena=Decimal("580.00"),
        )
        with patch(
            "core.predpokladany_pronajem.dj_tz.localdate",
            return_value=date(2026, 10, 22),
        ):
            ra = backfill_pronajem_from_staly_slot(slot_a)
            rb = backfill_pronajem_from_staly_slot(slot_b)
        self.assertGreaterEqual(ra["created"], 1)
        self.assertGreaterEqual(rb["created"], 1)
        wed = date(2026, 10, 14)
        from core.predpokladany_pronajem import existing_pronajem_at

        self.assertIsNotNone(
            existing_pronajem_at(wed, datetime.strptime("14:00", "%H:%M").time(), kurt_misto="HALA_2")
        )
        self.assertIsNotNone(
            existing_pronajem_at(wed, datetime.strptime("14:00", "%H:%M").time(), kurt_misto="HALA_4")
        )

        from core.predpokladany_pronajem import delete_pronajem_linked_to_staly_slot

        linked = delete_pronajem_linked_to_staly_slot(slot_b)
        self.assertGreaterEqual(linked["pronajem"], 1)
        self.assertIsNone(
            existing_pronajem_at(wed, datetime.strptime("14:00", "%H:%M").time(), kurt_misto="HALA_4")
        )
        # Druhý kurt ve stejný čas zůstane
        self.assertIsNotNone(
            existing_pronajem_at(wed, datetime.strptime("14:00", "%H:%M").time(), kurt_misto="HALA_2")
        )

    def test_pronajem_save_stores_manual_price(self):
        from core.models import Pronajem
        from django.utils import timezone as dj_tz

        obj = Pronajem.objects.create(
            datum=dj_tz.make_aware(datetime(2026, 10, 19, 10, 0)),
            delka_minut=60,
            kurt=Cenik.Kurt.HALA,
            rezervujici="Firma XY",
            cena=Decimal("350.00"),
        )
        self.assertEqual(obj.cena, Decimal("350.00"))
        self.assertEqual(obj.format, Pronajem.FORMAT_DEFAULT)
        self.assertEqual(obj.rezervujici, "Firma XY")

    def test_schedule_forbidden_for_club_staff(self):
        self.client.force_login(self.club)
        resp = self.client.get("/admin/core/pronajem/schedule/")
        self.assertEqual(resp.status_code, 403)

    def test_schedule_ok_for_platform_admin(self):
        self.client.force_login(self.platform)
        resp = self.client.get("/admin/core/pronajem/schedule/")
        self.assertEqual(resp.status_code, 200)

    def test_schedule_modes_and_delka_7h(self):
        import json
        from core.models import StalyPronajemSlot, SystemNastaveni

        self.client.force_login(self.platform)
        for mode in ("aktualni", "staly", "predpokladany"):
            resp = self.client.get(f"/admin/core/pronajem/schedule/?rozvrh={mode}&view=week")
            self.assertEqual(resp.status_code, 200, mode)
            body = resp.content.decode()
            self.assertIn("Aktuální", body)
            self.assertIn("Stálý", body)
            self.assertIn("Předpokládaný", body)
            self.assertIn('data-kind="pronajem"', body)

        resp = self.client.get("/admin/core/pronajem/schedule/?rozvrh=aktualni&view=week")
        opts = json.loads(resp.context["quick_add_options_json"])
        delky = [int(d["value"]) for d in opts["delky"]]
        self.assertEqual(max(delky), 420)
        self.assertEqual(delky, [c[0] for c in SystemNastaveni.PRONAJEM_DELKA_MINUT_CHOICES])
        self.assertIn("HALA", opts["kurty_by_sezona"])
        self.assertEqual(
            [k["value"] for k in opts["kurty_by_sezona"]["HALA"]],
            ["HALA_1", "HALA_2", "HALA_3", "HALA_4"],
        )
        self.assertEqual(
            [k["value"] for k in opts["kurty_by_sezona"]["VENEK"]],
            ["KURT_1", "KURT_2", "ANTUKA_1", "ANTUKA_2", "KURT_V", "ANTUKA_N"],
        )
        self.assertEqual([c["value"] for c in opts["ceny_by_sezona"]["VENEK"]], ["220", "250"])

        resp = self.client.post(
            "/admin/core/pronajem/schedule/staly/",
            data=json.dumps({
                "dow": 1,
                "time": "08:00",
                "rezervujici": "Firma 7h",
                "delka_minut": 420,
                "sezona": Cenik.Kurt.HALA,
                "kurt": "HALA_2",
                "cena": "580",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        slot = StalyPronajemSlot.objects.get(pk=data["id"])
        self.assertEqual(slot.delka_minut, 420)
        self.assertEqual(slot.rezervujici, "Firma 7h")
        self.assertEqual(slot.kurt, Cenik.Kurt.HALA)
        self.assertEqual(slot.kurt_misto, "HALA_2")

    def test_quick_add_and_analytika_sum(self):
        import json
        from core.analytika_data import build_analytika_context, pronajmy_sum_between, revenue_sum_between
        from django.utils import timezone as dj_tz
        from django.test import RequestFactory

        self.client.force_login(self.platform)
        payload = {
            "date": dj_tz.localdate().isoformat(),
            "time": "14:00",
            "rezervujici": "Jan Novák",
            "sezona": Cenik.Kurt.HALA,
            "kurt": "HALA_1",
            "delka_minut": 180,
            "cena": "420",
        }
        resp = self.client.post(
            "/admin/core/pronajem/schedule/quick-add/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        from core.models import Pronajem

        obj = Pronajem.objects.get(pk=data["id"])
        self.assertEqual(obj.delka_minut, 180)
        self.assertEqual(obj.cena, Decimal("1260.00"))

        today = dj_tz.localdate()
        self.assertEqual(pronajmy_sum_between(today, today), Decimal("1260.00"))
        self.assertEqual(revenue_sum_between(today, today, "pronajmy"), Decimal("1260.00"))
        self.assertEqual(revenue_sum_between(today, today, "treningy"), Decimal("0"))
        self.assertEqual(revenue_sum_between(today, today, "vse"), Decimal("1260.00"))

        rf = RequestFactory()
        req = rf.get("/admin/analytika/prehled/?zdroj=pronajmy")
        req.user = self.platform
        ctx = build_analytika_context("prehled", req)
        self.assertEqual(ctx["analytika_zdroj"], "pronajmy")
        self.assertEqual(ctx["kpis"]["nauctovano_value"], 1260.0)
        self.assertEqual(ctx["kpis"]["pronajmy_current_value"], 1260.0)

class AxesAndLoggingTests(TestCase):
    def test_instance_log_filter_sets_instance(self):
        import logging
        from django.test import override_settings
        from core.logging_filters import InstanceContextFilter

        record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", (), None)
        with override_settings(INSTANCE_NAME="test-club"):
            self.assertTrue(InstanceContextFilter().filter(record))
        self.assertEqual(record.instance, "test-club")

    def test_axes_locks_after_failures(self):
        from django.contrib.auth.models import User
        from django.test import override_settings
        from axes.models import AccessAttempt

        User.objects.create_user("lockme", "lock@example.com", "RightPass123!", is_staff=True)
        with override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3, AXES_COOLOFF_TIME=1):
            for _ in range(3):
                self.client.post(
                    "/admin/login/",
                    {"username": "lockme", "password": "wrong", "next": "/admin/"},
                )
            locked = self.client.post(
                "/admin/login/",
                {"username": "lockme", "password": "RightPass123!", "next": "/admin/"},
            )
        self.assertIn(locked.status_code, (403, 429))
        self.assertTrue(AccessAttempt.objects.filter(username="lockme").exists())

class BillingStripeTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group, User
        from core.roles import ensure_role_groups, CLUB_ADMIN_GROUP

        ensure_role_groups()
        self.club_user = User.objects.create_user(
            "clubbill", "club@example.com", "SecretPass123!", is_staff=True
        )
        self.club_user.groups.add(Group.objects.get(name=CLUB_ADMIN_GROUP))
        self.platform_user = User.objects.create_superuser(
            "platbill", "plat@example.com", "SecretPass123!"
        )

    def test_stripe_configured_requires_customer(self):
        from django.test import override_settings
        from core.billing import stripe_configured
        from core.models import SoftwareBilling

        SoftwareBilling.load()
        with override_settings(STRIPE_SECRET_KEY="", STRIPE_CUSTOMER_ID=""):
            SoftwareBilling.objects.filter(pk=1).update(stripe_customer_id="")
            self.assertFalse(stripe_configured())
        with override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_CUSTOMER_ID=""):
            SoftwareBilling.objects.filter(pk=1).update(stripe_customer_id="")
            self.assertFalse(stripe_configured())
        with override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_CUSTOMER_ID="cus_x"):
            SoftwareBilling.objects.filter(pk=1).update(stripe_customer_id="")
            self.assertTrue(stripe_configured())

    def test_billing_active_follows_subscription_status(self):
        from django.test import override_settings
        from core.billing import billing_active
        from core.models import SoftwareBilling

        billing = SoftwareBilling.load()
        with override_settings(BILLING_ACTIVE=True, STRIPE_REQUIRE_SUBSCRIPTION=False):
            billing.stripe_subscription_status = "canceled"
            billing.save()
            self.assertFalse(billing_active())
            billing.stripe_subscription_status = "active"
            billing.save()
            self.assertTrue(billing_active())

    def test_require_subscription_locks_without_status(self):
        from django.test import override_settings
        from core.billing import billing_active
        from core.models import SoftwareBilling

        SoftwareBilling.objects.filter(pk=1).update(stripe_subscription_status="")
        with override_settings(
            BILLING_ACTIVE=True,
            STRIPE_REQUIRE_SUBSCRIPTION=True,
            STRIPE_SECRET_KEY="sk_test_x",
            STRIPE_PRICE_ID="price_x",
        ):
            self.assertFalse(billing_active())

    def test_billing_portal_redirects_when_configured(self):
        from unittest.mock import patch
        from django.test import override_settings

        self.client.force_login(self.club_user)
        with override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_CUSTOMER_ID="cus_x"):
            with patch(
                "core.billing.create_billing_portal_url",
                return_value="https://billing.stripe.com/test",
            ):
                response = self.client.get("/admin/nastaveni/billing-portal/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://billing.stripe.com/test")

    def test_billing_checkout_redirects_when_configured(self):
        from unittest.mock import patch
        from django.test import override_settings

        self.client.force_login(self.club_user)
        with override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_PRICE_ID="price_x"):
            with patch(
                "core.billing.create_checkout_session",
                return_value="https://checkout.stripe.com/test",
            ):
                response = self.client.get("/admin/nastaveni/billing-checkout/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://checkout.stripe.com/test")

    def test_webhook_checkout_completed_updates_billing(self):
        from unittest.mock import patch
        from django.test import override_settings
        from core.models import SoftwareBilling

        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "mode": "subscription",
                    "customer": "cus_wh_1",
                    "subscription": "sub_wh_1",
                }
            },
        }
        with override_settings(
            STRIPE_SECRET_KEY="sk_test_x",
            STRIPE_WEBHOOK_SECRET="whsec_test",
        ):
            with patch("core.billing.construct_webhook_event", return_value=event):
                with patch("core.billing.sync_from_subscription_object") as sync_mock:
                    response = self.client.post(
                        "/stripe/webhook/",
                        data=b"{}",
                        content_type="application/json",
                        HTTP_STRIPE_SIGNATURE="t=1,v1=fake",
                    )
        self.assertEqual(response.status_code, 200)
        billing = SoftwareBilling.load()
        self.assertEqual(billing.stripe_customer_id, "cus_wh_1")
        sync_mock.assert_called_once_with("sub_wh_1")

    def test_billing_inactive_blocks_club_post(self):
        from django.test import override_settings

        self.client.force_login(self.club_user)
        with override_settings(BILLING_ACTIVE=False):
            get = self.client.get("/admin/nastaveni/")
            self.assertEqual(get.status_code, 200)
            body = get.content.decode()
            self.assertIn("ts-billing-banner", body)
            self.assertIn("Předplatné TenisSystému není aktivní", body)

            response = self.client.post("/admin/nastaveni/", {"nazev_klubu": "Hack"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("nastaveni", response.url)

    def test_billing_active_hides_lock_banner(self):
        from django.test import override_settings

        self.client.force_login(self.club_user)
        with override_settings(BILLING_ACTIVE=True):
            response = self.client.get("/admin/nastaveni/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Předplatné TenisSystému není aktivní", response.content.decode())

    def test_billing_inactive_allows_platform_post_path_to_view(self):
        """Platform admin není middlewarem přesměrován pryč z POST."""
        from django.test import override_settings

        self.client.force_login(self.platform_user)
        with override_settings(BILLING_ACTIVE=False):
            response = self.client.get("/admin/nastaveni/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Předplatné")

    def test_nastaveni_shows_predplatne_panel(self):
        self.client.force_login(self.club_user)
        response = self.client.get("/admin/nastaveni/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="panel-predplatne"')

class BootstrapInstanceTests(TestCase):
    def test_bootstrap_sets_branding_and_club_admin(self):
        import os
        from django.contrib.auth.models import Group, User
        from django.core.management import call_command
        from core.models import SystemNastaveni, VyuctovaniNastaveni
        from core.roles import CLUB_ADMIN_GROUP

        os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "test-pass-123"
        try:
            call_command(
                "bootstrap_instance",
                "--nazev",
                "Tenis Test",
                "--email",
                "info@test.cz",
                "--ucet1",
                "111/0100",
                "--create-admin",
                "clubadmin",
                "admin@test.cz",
            )
        finally:
            os.environ.pop("BOOTSTRAP_ADMIN_PASSWORD", None)

        system = SystemNastaveni.load()
        self.assertEqual(system.nazev_klubu, "Tenis Test")
        self.assertEqual(system.kontakt_email, "info@test.cz")

        vyuct = VyuctovaniNastaveni.load()
        self.assertEqual(vyuct.ucet_varianta_1, "111/0100")

        user = User.objects.get(username="clubadmin")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.groups.filter(name=CLUB_ADMIN_GROUP).exists())
        self.assertTrue(Group.objects.filter(name=CLUB_ADMIN_GROUP).exists())

    def test_bootstrap_seed_demo(self):
        from django.core.management import call_command
        from core.models import SystemNastaveni

        call_command("bootstrap_instance", "--seed", "demo")
        system = SystemNastaveni.load()
        self.assertIn("Demo", system.nazev_klubu)

    def test_bootstrap_skip_branding_preserves_nazev(self):
        import os
        from django.core.management import call_command
        from core.models import SystemNastaveni

        nast = SystemNastaveni.load()
        nast.nazev_klubu = "Původní klub"
        nast.save(sync_colors=False)

        os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "test-pass-123"
        try:
            call_command(
                "bootstrap_instance",
                "--skip-branding",
                "--create-admin",
                "onlyadmin",
                "only@test.cz",
            )
        finally:
            os.environ.pop("BOOTSTRAP_ADMIN_PASSWORD", None)

        self.assertEqual(SystemNastaveni.load().nazev_klubu, "Původní klub")

    def test_bootstrap_without_seed_or_cli_skips_branding(self):
        from django.core.management import call_command
        from core.models import SystemNastaveni

        nast = SystemNastaveni.load()
        nast.nazev_klubu = "Neměnit"
        nast.save(sync_colors=False)

        call_command("bootstrap_instance")
        self.assertEqual(SystemNastaveni.load().nazev_klubu, "Neměnit")

class EmailOrUsernameAuthTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User

        self.user = User.objects.create_user(
            "coach1",
            "coach@example.com",
            "SecretPass123!",
            is_staff=True,
        )

    def test_authenticate_by_username(self):
        from django.contrib.auth import authenticate

        user = authenticate(username="coach1", password="SecretPass123!")
        self.assertEqual(user, self.user)

    def test_authenticate_by_email(self):
        from django.contrib.auth import authenticate

        user = authenticate(username="coach@example.com", password="SecretPass123!")
        self.assertEqual(user, self.user)

    def test_authenticate_by_email_case_insensitive(self):
        from django.contrib.auth import authenticate

        user = authenticate(username="Coach@Example.com", password="SecretPass123!")
        self.assertEqual(user, self.user)

    def test_seed_club_defaults_requires_slug(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("seed_club_defaults")

class FreshInstanceSmokeTests(TestCase):
    """Fresh bootstrap Tenis XY – žádné Čimice v brandingu / klíčových stránkách."""

    def setUp(self):
        import os
        from django.core.management import call_command

        os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "xy-pass-123"
        try:
            call_command(
                "bootstrap_instance",
                "--nazev",
                "Tenis XY",
                "--email",
                "info@xy.cz",
                "--email-odesilatel",
                "Tenis XY <info@xy.cz>",
                "--email-prefix",
                "[Tenis XY] ",
                "--email-podpis",
                "S pozdravem,\n\nTenis XY",
                "--ucet1-nazev",
                "Účet 1",
                "--ucet1",
                "123456789/0100",
                "--ucet2-nazev",
                "Účet 2",
                "--create-admin",
                "admin",
                "admin@xy.cz",
            )
        finally:
            os.environ.pop("BOOTSTRAP_ADMIN_PASSWORD", None)

    def test_branding_and_email_defaults(self):
        from core.models import SystemNastaveni, VyuctovaniNastaveni

        nast = SystemNastaveni.load()
        self.assertEqual(nast.nazev_klubu, "Tenis XY")
        self.assertEqual(nast.kontakt_email, "info@xy.cz")
        self.assertIn("Tenis XY", nast.email_odesilatel)
        self.assertEqual(nast.email_predmet_prefix.strip(), "[Tenis XY]")
        self.assertIn("Tenis XY", nast.email_podpis)
        for blob in (
            nast.nazev_klubu,
            nast.email_odesilatel,
            nast.email_predmet_prefix,
            nast.email_podpis,
        ):
            self.assertNotIn("Čimice", blob)
            self.assertNotIn("cimice", blob.casefold())
            self.assertNotIn("Káťa", blob)
            self.assertNotIn("kptenis", blob.casefold())

        vyuct = VyuctovaniNastaveni.load()
        self.assertEqual(vyuct.ucet_nazev_1, "Účet 1")
        self.assertEqual(vyuct.ucet_nazev_2, "Účet 2")
        self.assertNotIn("AJ Sport", vyuct.ucet_nazev_1)
        self.assertNotIn("Káťa", vyuct.ucet_nazev_2)

    def test_landing_and_admin_pages_show_club_not_cimice(self):
        from django.contrib.auth.models import User
        from django.test import override_settings

        with override_settings(TENNIS_SCHOOLS=[]):
            landing = self.client.get("/")
        self.assertEqual(landing.status_code, 200)
        self.assertContains(landing, "Tenis XY")
        self.assertContains(landing, "Vstup do systému")
        self.assertNotContains(landing, "Čimice")

        user = User.objects.get(username="admin")
        self.client.force_login(user)

        admin_index = self.client.get("/admin/")
        self.assertEqual(admin_index.status_code, 200)
        self.assertContains(admin_index, "Tenis XY")
        self.assertNotContains(admin_index, "Čimice")

        analytika = self.client.get("/admin/analytika/prehled/")
        self.assertEqual(analytika.status_code, 200)
        self.assertContains(analytika, "Tenis XY")
        self.assertNotContains(analytika, "Čimice")
        self.assertNotContains(analytika, "Přehled TS")

    def test_check_instance_passes(self):
        from django.core.management import call_command
        from django.test import override_settings
        from io import StringIO

        # Django test runner forces DEBUG=False, so check_instance validates hosts.
        # Provide CI-safe hosts; branding was set in setUp via bootstrap.
        out = StringIO()
        with override_settings(
            ALLOWED_HOSTS=["testserver", "localhost"],
            CSRF_TRUSTED_ORIGINS=["http://testserver", "http://localhost"],
        ):
            call_command("check_instance", stdout=out)
        self.assertIn("OK", out.getvalue())

class HealthEndpointTests(TestCase):
    def test_health_ok(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

class LandingSingleTenantTests(TestCase):
    def test_empty_tennis_schools_falls_back_to_system_nastaveni(self):
        from django.test import override_settings
        from core.models import SystemNastaveni

        nast = SystemNastaveni.load()
        nast.nazev_klubu = "Tenis Fallback"
        nast.kontakt_adresa = "Praha"
        nast.save(sync_colors=False)

        with override_settings(TENNIS_SCHOOLS=[]):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["single_school"])
        self.assertEqual(len(response.context["active_schools"]), 1)
        self.assertEqual(response.context["active_schools"][0]["name"], "Tenis Fallback")
        self.assertContains(response, "Vstup do systému")
        self.assertContains(response, 'href="/privacy/"')
        self.assertContains(response, 'href="/terms/"')

    def test_privacy_and_terms_pages(self):
        from core.models import SystemNastaveni

        nast = SystemNastaveni.load()
        nast.nazev_klubu = "Legal Klub"
        nast.kontakt_email = "legal@example.com"
        nast.save(sync_colors=False)

        privacy = self.client.get("/privacy/")
        self.assertEqual(privacy.status_code, 200)
        self.assertContains(privacy, "Ochrana soukromí")
        self.assertContains(privacy, "Legal Klub")
        self.assertContains(privacy, "legal@example.com")

        terms = self.client.get("/terms/")
        self.assertEqual(terms.status_code, 200)
        self.assertContains(terms, "Podmínky užívání")
        self.assertContains(terms, "Legal Klub")

    def test_multi_school_keeps_select_cta(self):
        from django.test import override_settings

        schools = [
            {
                "slug": "a",
                "name": "Škola A",
                "city": "Praha",
                "region": "",
                "admin_url": "/admin/",
                "active": True,
            },
            {
                "slug": "b",
                "name": "Škola B",
                "city": "Brno",
                "region": "",
                "admin_url": "/admin/",
                "active": True,
            },
        ]
        with override_settings(TENNIS_SCHOOLS=schools):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["single_school"])
        self.assertContains(response, "Vybrat školu")

class PasswordResetFlowTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from core.models import SystemNastaveni

        self.user = User.objects.create_user(
            "resetme",
            "reset@example.com",
            "OldPass123!",
            is_staff=True,
        )
        nast = SystemNastaveni.load()
        nast.nazev_klubu = "Reset Klub"
        nast.email_odesilatel = "Reset Klub <noreply@reset.example>"
        nast.save(sync_colors=False)

    def test_login_shows_password_reset_link(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/admin/password_reset/")

    def test_password_reset_sends_mail_with_club_from(self):
        from django.core import mail

        response = self.client.post(
            "/admin/password_reset/",
            {"email": "reset@example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["reset@example.com"])
        self.assertIn("noreply@reset.example", mail.outbox[0].from_email)
        self.assertIn("/admin/reset/", mail.outbox[0].body)

    def test_password_reset_unknown_email_still_redirects(self):
        from django.core import mail

        response = self.client.post(
            "/admin/password_reset/",
            {"email": "nobody@example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

class PlayerStripePaymentTests(TestCase):
    def setUp(self):
        from core.models import ClubStripeConnect, Hrac, Vyuctovani
        from django.utils import timezone

        self.hrac = Hrac.objects.create(jmeno="Jan", prijmeni="Novak", email="jan@example.com")
        self.vyuct = Vyuctovani.objects.create(
            hrac=self.hrac,
            period_to=timezone.now(),
            amount_due="1500.00",
            payment_status="pending",
        )
        connect = ClubStripeConnect.load()
        connect.stripe_account_id = "acct_test_club"
        connect.charges_enabled = True
        connect.details_submitted = True
        connect.payouts_enabled = True
        connect.player_payments_enabled = True
        connect.save()

    def test_checkout_completed_creates_platba(self):
        from core.models import Transakce, Vyuctovani
        from core.player_payments import handle_player_checkout_completed

        session = {
            "id": "cs_test_1",
            "mode": "payment",
            "payment_status": "paid",
            "payment_intent": "pi_test_1",
            "amount_total": 150000,
            "metadata": {
                "purpose": "player_payment",
                "hrac_id": str(self.hrac.pk),
                "vyuctovani_id": str(self.vyuct.pk),
            },
        }
        handle_player_checkout_completed(session)

        txs = Transakce.objects.filter(hrac=self.hrac, typ=Transakce.Typ.PLATBA)
        self.assertEqual(txs.count(), 1)
        tx = txs.get()
        self.assertEqual(tx.castka, Decimal("1500.00"))
        self.assertEqual(tx.stripe_payment_intent_id, "pi_test_1")
        self.assertEqual(tx.vyuctovani_id, self.vyuct.pk)

        self.vyuct.refresh_from_db()
        self.assertEqual(self.vyuct.payment_status, Vyuctovani.PaymentStatus.PAID)
        self.assertEqual(self.vyuct.stripe_payment_intent_id, "pi_test_1")

    def test_checkout_completed_is_idempotent(self):
        from core.models import Transakce
        from core.player_payments import handle_player_checkout_completed

        session = {
            "id": "cs_test_2",
            "mode": "payment",
            "payment_status": "paid",
            "payment_intent": "pi_test_dup",
            "amount_total": 150000,
            "metadata": {
                "purpose": "player_payment",
                "hrac_id": str(self.hrac.pk),
                "vyuctovani_id": str(self.vyuct.pk),
            },
        }
        handle_player_checkout_completed(session)
        handle_player_checkout_completed(session)
        self.assertEqual(
            Transakce.objects.filter(hrac=self.hrac, typ=Transakce.Typ.PLATBA).count(),
            1,
        )

    def test_billing_handler_routes_player_payment(self):
        from core.billing import handle_stripe_event
        from core.models import Transakce

        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_3",
                    "mode": "payment",
                    "payment_status": "paid",
                    "payment_intent": "pi_test_route",
                    "amount_total": 150000,
                    "metadata": {
                        "purpose": "player_payment",
                        "hrac_id": str(self.hrac.pk),
                        "vyuctovani_id": str(self.vyuct.pk),
                    },
                }
            },
        }
        handle_stripe_event(event)
        self.assertTrue(
            Transakce.objects.filter(stripe_payment_intent_id="pi_test_route").exists()
        )

    def test_player_payments_ready_requires_connect(self):
        from django.test import override_settings
        from core.models import ClubStripeConnect
        from core.player_payments import player_payments_ready

        with override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_CONNECT_TEST_BYPASS=False):
            self.assertTrue(player_payments_ready())
            ClubStripeConnect.objects.filter(pk=1).update(charges_enabled=False)
            self.assertFalse(player_payments_ready())

        with override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_CONNECT_TEST_BYPASS=True):
            ClubStripeConnect.objects.filter(pk=1).update(charges_enabled=False, details_submitted=False)
            self.assertTrue(player_payments_ready())

    def test_checkout_unpaid_is_ignored(self):
        from core.models import Transakce
        from core.player_payments import handle_player_checkout_completed

        session = {
            "id": "cs_test_unpaid",
            "mode": "payment",
            "payment_status": "unpaid",
            "payment_intent": "pi_test_unpaid",
            "amount_total": 150000,
            "metadata": {
                "purpose": "player_payment",
                "hrac_id": str(self.hrac.pk),
                "vyuctovani_id": str(self.vyuct.pk),
            },
        }
        handle_player_checkout_completed(session)
        self.assertFalse(
            Transakce.objects.filter(stripe_payment_intent_id="pi_test_unpaid").exists()
        )

    def test_public_base_url_prefers_setting(self):
        from django.test import override_settings
        from core.player_payments import public_base_url

        with override_settings(PUBLIC_BASE_URL="https://klub.example.com/"):
            self.assertEqual(public_base_url(), "https://klub.example.com")

    def test_vyuctovani_email_includes_pay_cta(self):
        from unittest.mock import patch
        from django.test import override_settings

        captured = {}

        def fake_send(**kwargs):
            captured["body"] = kwargs.get("body") or ""
            captured["html"] = kwargs.get("html_body") or ""
            return True, True

        with override_settings(STRIPE_SECRET_KEY="sk_test_x", PUBLIC_BASE_URL="https://klub.example.com"):
            with patch("core.models.send_and_append_to_sent", side_effect=fake_send):
                with patch(
                    "core.player_payments.maybe_attach_checkout",
                    return_value="https://checkout.stripe.com/c/pay/test",
                ):
                    self.hrac.vygeneruj_vyuctovani(
                        duvod="manual",
                        send_email=True,
                        override_amount_due=Decimal("1500.00"),
                    )

        self.assertIn("Zaplatit online", captured.get("html", ""))
        self.assertIn("https://checkout.stripe.com/c/pay/test", captured.get("body", ""))
        self.assertIn("Nebo převodem", captured.get("html", ""))

    def test_nastaveni_shows_platby_hracu_panel(self):
        from django.contrib.auth.models import Group, User
        from django.test import override_settings
        from core.models import ClubStripeConnect
        from core.roles import ensure_role_groups, CLUB_ADMIN_GROUP

        ClubStripeConnect.objects.filter(pk=1).update(
            stripe_account_id="",
            charges_enabled=False,
            details_submitted=False,
        )
        ensure_role_groups()
        user = User.objects.create_user(
            "clubpay", "clubpay@example.com", "SecretPass123!", is_staff=True
        )
        user.groups.add(Group.objects.get(name=CLUB_ADMIN_GROUP))
        self.client.force_login(user)
        with override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_CONNECT_TEST_BYPASS=False):
            response = self.client.get("/admin/nastaveni/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="panel-platby-hracu"')
        self.assertContains(response, "Propojit Stripe")

class ProductionHostsCheckTests(TestCase):
    def test_debug_skips_host_errors(self):
        from django.test import override_settings
        from core.checks import check_production_hosts

        with override_settings(DEBUG=True, ALLOWED_HOSTS=[], CSRF_TRUSTED_ORIGINS=[]):
            self.assertEqual(check_production_hosts(None), [])

    def test_production_empty_hosts_is_error(self):
        from django.test import override_settings
        from core.checks import check_production_hosts

        with override_settings(DEBUG=False, ALLOWED_HOSTS=[], CSRF_TRUSTED_ORIGINS=[]):
            msgs = check_production_hosts(None)
        ids = {m.id for m in msgs}
        self.assertIn("core.E001", ids)
        self.assertIn("core.W001", ids)

    def test_production_insecure_secret_is_error(self):
        from django.test import override_settings
        from core.checks import check_production_secret

        with override_settings(DEBUG=False, SECRET_KEY="dev-insecure-please-set-DJANGO_SECRET_KEY"):
            msgs = check_production_secret(None)
        self.assertTrue(any(m.id == "core.E004" for m in msgs))

    def test_production_strong_secret_passes(self):
        from django.test import override_settings
        from core.checks import check_production_secret

        strong = "x" * 48
        with override_settings(DEBUG=False, SECRET_KEY=strong):
            self.assertEqual(check_production_secret(None), [])

    def test_production_missing_smtp_is_warning(self):
        from django.test import override_settings
        from core.checks import check_production_email

        with override_settings(DEBUG=False, EMAIL_HOST="", EMAIL_HOST_USER=""):
            msgs = check_production_email(None)
        self.assertTrue(any(m.id == "core.W002" for m in msgs))

    def test_production_smtp_configured_passes(self):
        from django.test import override_settings
        from core.checks import check_production_email

        with override_settings(DEBUG=False, EMAIL_HOST="smtp.example.com", EMAIL_HOST_USER="u"):
            self.assertEqual(check_production_email(None), [])

    def test_production_local_media_is_warning(self):
        from django.test import override_settings
        from core.checks import check_production_storage

        with override_settings(DEBUG=False, USE_S3=False):
            msgs = check_production_storage(None)
        self.assertTrue(any(m.id == "core.W003" for m in msgs))

    def test_production_s3_without_bucket_is_warning(self):
        from django.test import override_settings
        from core.checks import check_production_storage

        with override_settings(
            DEBUG=False,
            USE_S3=True,
            AWS_STORAGE_BUCKET_NAME="",
            AWS_ACCESS_KEY_ID="key",
        ):
            msgs = check_production_storage(None)
        self.assertTrue(any(m.id == "core.W003" for m in msgs))

    def test_production_s3_configured_passes(self):
        from django.test import override_settings
        from core.checks import check_production_storage

        with override_settings(
            DEBUG=False,
            USE_S3=True,
            AWS_STORAGE_BUCKET_NAME="club-media",
            AWS_ACCESS_KEY_ID="key",
        ):
            self.assertEqual(check_production_storage(None), [])

    def test_check_instance_strict_hosts_fails_when_empty(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from django.test import override_settings

        with override_settings(DEBUG=True, ALLOWED_HOSTS=[], CSRF_TRUSTED_ORIGINS=[]):
            with self.assertRaises(CommandError):
                call_command("check_instance", "--strict-hosts")

class ScheduleLongPressAddTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group, User
        from core.roles import CLUB_ADMIN_GROUP, ensure_role_groups

        ensure_role_groups()
        self.user = User.objects.create_user(
            "schedlp", "schedlp@example.com", "SecretPass123!", is_staff=True
        )
        self.user.groups.add(Group.objects.get(name=CLUB_ADMIN_GROUP))
        self.client.force_login(self.user)

    def test_schedule_includes_longpress_hook(self):
        response = self.client.get("/admin/core/trening/schedule/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-longpress-slot")
        self.assertContains(response, "admin/js/kalendar.js")
        self.assertContains(response, "data-quick-add-url")
        self.assertContains(response, "data-move-url")
        self.assertContains(response, 'data-hold-ms="450"')
        self.assertContains(response, 'id="qa-overlay"')
        self.assertContains(response, 'id="qa-options"')

    def test_schedule_quick_add_creates_training(self):
        import json
        from django.utils import timezone as dj_tz
        from core.models import SystemNastaveni, Trening

        nast = SystemNastaveni.load()
        nast.vychozi_kurt = "Kurt 1"
        nast.vychozi_sezona = "Léto"
        nast.save(sync_colors=False)

        url = "/admin/core/trening/schedule/quick-add/"
        payload = {
            "date": "2026-09-24",
            "time": "09:30",
            "trener": self.user.pk,
            "format": "Solo (1 hráč) - Člen",
            "delka_minut": 60,
            "kurt": "Kurt 1",
            "sezona": "Léto",
            "poznamka": "z kalendáře",
            "hraci": [],
        }
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"), data)
        trening = Trening.objects.get(pk=data["id"])
        self.assertEqual(trening.trener_id, self.user.pk)
        self.assertEqual(trening.format, "Solo (1 hráč) - Člen")
        self.assertEqual(trening.kurt, "Kurt 1")
        self.assertEqual(trening.poznamka, "z kalendáře")
        local_dt = dj_tz.localtime(trening.datum) if dj_tz.is_aware(trening.datum) else trening.datum
        self.assertEqual(local_dt.hour, 9)
        self.assertEqual(local_dt.minute, 30)

    def test_add_form_prefills_date_and_time(self):
        response = self.client.get(
            f"/admin/core/trening/add/?date=2026-09-24&time=09:30&trener={self.user.pk}"
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertTrue(
            "2026-09-24" in content or "24.09.2026" in content,
            "expected prefilled date in add form",
        )
        self.assertTrue(
            "09:30" in content or "value=\"09:30:00\"" in content,
            "expected prefilled time in add form",
        )
        self.assertIn(f'value="{self.user.pk}"', content)

    def test_training_defaults_from_settings(self):
        from core.models import SystemNastaveni

        nast = SystemNastaveni.load()
        nast.vychozi_delka_minut = 90
        nast.vychozi_sezona = "Léto"
        nast.save(sync_colors=False)

        defaults = SystemNastaveni.training_defaults()
        self.assertEqual(defaults["delka_minut"], 90)
        self.assertEqual(defaults["sezona"], "Léto")

    def test_home_uses_club_name_and_contact(self):
        from core.models import SystemNastaveni
        from core.views import home
        from django.test import RequestFactory

        nast = SystemNastaveni.load()
        nast.nazev_klubu = "Testovací klub"
        nast.kontakt_email = "klub@example.com"
        nast.kontakt_telefon = "+420 123 456"
        nast.save(sync_colors=False)

        request = RequestFactory().get("/")
        response = home(request)
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Testovací klub", content)
        self.assertIn("klub@example.com", content)
        self.assertIn("+420 123 456", content)

    def test_kurt_pro_datum_uses_vychozi_sezona(self):
        from datetime import date
        from core.models import SystemNastaveni

        nast = SystemNastaveni.load()
        nast.vychozi_sezona = "Léto"
        nast.save(sync_colors=False)

        self.assertEqual(nast.kurt_pro_datum(date(2026, 7, 15)), "Léto")
        self.assertEqual(nast.kurt_pro_datum(date(2026, 1, 15)), "Léto")

    def test_email_subject_prefix(self):
        from core.models import SystemNastaveni

        self.assertEqual(
            SystemNastaveni.compose_subject_prefix("Tenis Test Club"),
            "[Tenis Test Club] ",
        )
        nast = SystemNastaveni.load()
        nast.email_predmet_prefix = "[Klub] "
        nast.save(sync_colors=False)
        self.assertEqual(nast.subject_tag_display(), "Klub")
        self.assertEqual(
            nast.format_email_subject("Test"),
            "[Klub] Test",
        )
        nast.email_predmet_prefix = SystemNastaveni.compose_subject_prefix("Nový klub")
        nast.save(sync_colors=False)
        self.assertEqual(
            nast.format_email_subject("Test"),
            "[Nový klub] Test",
        )

    def test_from_email_parts(self):
        from core.models import SystemNastaveni

        nast = SystemNastaveni(email_odesilatel="Tenis Test <info@test.cz>")
        jmeno, adresa = nast.from_email_parts()
        self.assertEqual(jmeno, "Tenis Test")
        self.assertEqual(adresa, "info@test.cz")
        self.assertEqual(
            SystemNastaveni.compose_from_email("Tenis Test", "info@test.cz"),
            "Tenis Test <info@test.cz>",
        )

    def test_vzhled_ajax_save(self):
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from core.admin_views import admin_nastaveni_vzhled_view
        from core.models import SystemNastaveni, UserPreference

        user = get_user_model().objects.create_superuser("admin", "admin@test.com", "pass")
        nast_before = SystemNastaveni.load()
        sys_variant = nast_before.barevna_varianta
        sys_tmavy = nast_before.tmavy_rezim

        request = RequestFactory().post(
            "/admin/nastaveni/vzhled/",
            {"barevna_varianta": "modra", "tmavy_rezim": "true"},
        )
        request.user = user

        resp = admin_nastaveni_vzhled_view(request)
        self.assertEqual(resp.status_code, 200)
        import json
        data = json.loads(resp.content)
        self.assertTrue(data["ok"])
        self.assertEqual(data["barevna_varianta"], "modra")
        self.assertTrue(data["tmavy_rezim"])
        self.assertIn("--brand: #2563EB", data["theme_style"])

        # Systémové výchozí zůstane; preference je na uživateli
        nast = SystemNastaveni.load()
        self.assertEqual(nast.barevna_varianta, sys_variant)
        self.assertEqual(nast.tmavy_rezim, sys_tmavy)
        pref = UserPreference.objects.get(user=user)
        self.assertEqual(pref.barevna_varianta, "modra")
        self.assertTrue(pref.tmavy_rezim)

    def test_user_theme_overrides_system(self):
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from core.models import SystemNastaveni, UserPreference, Trening
        from core.system_theme import resolve_effective_theme
        from django.contrib import admin

        user_a = get_user_model().objects.create_superuser("usera", "a@test.com", "pass")
        user_b = get_user_model().objects.create_superuser("userb", "b@test.com", "pass")
        nast = SystemNastaveni.load()
        nast.barevna_varianta = "oranzova"
        nast.tmavy_rezim = False
        nast.save(sync_colors=True)

        UserPreference.objects.update_or_create(
            user=user_a,
            defaults={"barevna_varianta": "modra", "tmavy_rezim": True},
        )

        va, da, ca = resolve_effective_theme(user=user_a, nastaveni=nast)
        vb, db, cb = resolve_effective_theme(user=user_b, nastaveni=nast)
        self.assertEqual(va, "modra")
        self.assertTrue(da)
        self.assertEqual(ca["brand"], "#2563EB")
        self.assertEqual(vb, "oranzova")
        self.assertFalse(db)

        request = RequestFactory().get("/admin/core/trening/")
        request.user = user_a
        ma = admin.site._registry[Trening]
        response = ma.changelist_view(request)
        response.render()
        html = response.content.decode()
        self.assertIn("--brand: #2563EB", html)

    def test_resolve_theme_ignores_stale_barva_fields(self):
        from core.models import SystemNastaveni
        from core.system_theme import resolve_theme_colors

        nast = SystemNastaveni.load()
        nast.barevna_varianta = "zelena"
        nast.barva_brand = "#E67817"
        nast.vlastni_barvy = False
        nast.save(sync_colors=False)

        colors = resolve_theme_colors(nast)
        self.assertEqual(colors["brand"], "#14833B")

    def test_changelist_includes_global_theme(self):
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from core.models import SystemNastaveni, Trening
        from django.contrib import admin

        user = get_user_model().objects.create_superuser("admin2", "a2@test.com", "pass")
        nast = SystemNastaveni.load()
        nast.barevna_varianta = "modra"
        nast.tmavy_rezim = True
        nast.save(sync_colors=True)

        request = RequestFactory().get("/admin/core/trening/")
        request.user = user
        ma = admin.site._registry[Trening]
        response = ma.changelist_view(request)
        response.render()
        html = response.content.decode()

        self.assertNotIn("admin/css/dark_mode.css", html)
        self.assertIn("system-theme-state", html)
        self.assertIn("--brand: #2563EB", html)
        self.assertIn("admin/js/theme.js", html)

    def test_autosave_ajax(self):
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from core.admin_views import admin_nastaveni_autosave_view
        from core.models import SystemNastaveni, VyuctovaniNastaveni

        user = get_user_model().objects.create_superuser("admin3", "a3@test.com", "pass")
        nast = SystemNastaveni.load()
        vyuct = VyuctovaniNastaveni.load()
        request = RequestFactory().post(
            "/admin/nastaveni/ulozit/",
            {
                "nazev_klubu": "Test klub AJAX",
                "slogan": nast.slogan or "",
                "kontakt_email": nast.kontakt_email or "",
                "kontakt_telefon": nast.kontakt_telefon or "",
                "kontakt_adresa": nast.kontakt_adresa or "",
                "email_podpis": nast.email_podpis or "",
                "email_jmeno": "",
                "email_adresa": "",
                "email_oznaceni": "",
                "barevna_varianta": nast.barevna_varianta or "oranzova",
                "vychozi_delka_minut": str(nast.vychozi_delka_minut or 60),
                "vychozi_sezona": nast.vychozi_sezona or "",
                "rozvrh_od_hodina": str(nast.rozvrh_od_hodina or 6),
                "rozvrh_do_hodina": str(nast.rozvrh_do_hodina or 22),
                "vychozi_zobrazeni_rozvrhu": nast.vychozi_zobrazeni_rozvrhu or "tyden",
                "prah_dluhu_dashboard": str(nast.prah_dluhu_dashboard or 0),
                "radku_na_stranku": str(nast.radku_na_stranku or 50),
                "vyuctovani_rezim": vyuct.auto_rezim,
            },
        )
        request.user = user

        resp = admin_nastaveni_autosave_view(request)
        self.assertEqual(resp.status_code, 200)
        import json
        data = json.loads(resp.content)
        self.assertTrue(data["ok"])
        self.assertEqual(data["nazev_klubu"], "Test klub AJAX")

        nast.refresh_from_db()
        self.assertEqual(nast.nazev_klubu, "Test klub AJAX")

    def test_debt_threshold_filter(self):
        from decimal import Decimal
        from django.db.models import Sum, Case, When, F, Value, DecimalField
        from core.models import Hrac, SystemNastaveni, Transakce

        nast = SystemNastaveni.load()
        nast.prah_dluhu_dashboard = Decimal("-500")
        nast.save(sync_colors=False)

        qs = Hrac.objects.annotate(
            _kredit_calculated=Sum(
                Case(
                    When(transakce__typ__in=[Transakce.Typ.PLATBA, Transakce.Typ.VRATKA], then=F("transakce__castka")),
                    When(transakce__typ=Transakce.Typ.NAUCTOVANO, then=-F("transakce__castka")),
                    default=Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
        ).filter(_kredit_calculated__isnull=False)

        filtered = list(nast.filter_debtors(qs).values_list("_kredit_calculated", flat=True))
        for val in filtered:
            self.assertLessEqual(val, Decimal("-500"))

class ScrubLegacyDefaultsTests(TestCase):
    def test_migration_logic_scrubs_cimice_values(self):
        import importlib.util
        from pathlib import Path
        from django.apps import apps
        from core.models import SystemNastaveni, VyuctovaniNastaveni

        nast = SystemNastaveni.load()
        nast.nazev_klubu = "Tenis systém Čimice"
        nast.email_odesilatel = "Tenis Čimice <kptenis@volny.cz>"
        nast.email_predmet_prefix = "[Tenis Čimice] "
        nast.email_podpis = "S pozdravem,\n\nKateřina Peterková\nTenis Čimice"
        nast.save(sync_colors=False)

        vyuct = VyuctovaniNastaveni.load()
        vyuct.ucet_nazev_1 = "Účet 1 AJ Sport"
        vyuct.ucet_nazev_2 = "Účet 2 Káťa"
        vyuct.save()

        mig_path = Path(__file__).resolve().parent / "migrations" / "0044_scrub_legacy_club_defaults.py"
        spec = importlib.util.spec_from_file_location("scrub_legacy_mig", mig_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        mod._scrub(apps, None)

        nast.refresh_from_db()
        vyuct.refresh_from_db()
        self.assertEqual(nast.nazev_klubu, "TenisSystém")
        self.assertNotIn("Čimice", nast.email_odesilatel)
        self.assertNotIn("kptenis", nast.email_odesilatel.casefold())
        self.assertEqual(vyuct.ucet_nazev_1, "Účet 1")
        self.assertEqual(vyuct.ucet_nazev_2, "Účet 2")

class SentrySettingsTests(TestCase):
    def test_sentry_dsn_env_documented_optional(self):
        """Bez DSN appka běží; settings modul má SENTRY_DSN atribut."""
        from django.conf import settings as dj_settings

        self.assertTrue(hasattr(dj_settings, "SENTRY_DSN"))

class UserAdminPrivilegeTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group, User
        from core.roles import CLUB_ADMIN_GROUP, ensure_role_groups

        ensure_role_groups()
        self.club = User.objects.create_user("clubmgr", "c@example.com", "x", is_staff=True)
        self.club.groups.add(Group.objects.get(name=CLUB_ADMIN_GROUP))
        self.client.force_login(self.club)

    def test_club_admin_user_form_hides_privileged_fields(self):
        response = self.client.get("/admin/auth/user/add/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="is_superuser"')
        self.assertNotContains(response, 'name="groups"')
        self.assertNotContains(response, 'name="user_permissions"')

    def test_club_admin_cannot_escalate_via_post(self):
        from django.contrib.auth.models import User

        response = self.client.post(
            "/admin/auth/user/add/",
            {
                "username": "newbie",
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
                "email": "n@example.com",
                "is_superuser": "on",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        newbie = User.objects.get(username="newbie")
        self.assertFalse(newbie.is_superuser)
        self.assertTrue(newbie.is_staff)
        self.assertTrue(newbie.groups.filter(name="club_admin").exists())

class VyuctovaniNastaveniViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        from core.models import VyuctovaniNastaveni

        User = get_user_model()
        self.user = User.objects.create_superuser(
            "vyuctset", "vyuctset@example.com", "SecretPass123!"
        )
        self.client.force_login(self.user)
        self.url = reverse("admin:core_vyuctovani_nastaveni")
        self.hrac = Hrac.objects.create(
            jmeno="Petr",
            prijmeni="Novák",
            vyuctovani_rezim=Hrac.RezimVyuctovani.CASTKA,
        )
        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = VyuctovaniNastaveni.AutoRezim.MANUAL
        nast.save()

    def test_post_mesicne_saves_and_syncs_players(self):
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        response = self.client.post(
            self.url,
            {
                "auto_rezim": VyuctovaniNastaveni.AutoRezim.MESICNE,
                "mesicni_den": "7",
                "auto_limit": str(nast.auto_limit),
                "auto_castka_k_uhrade": str(nast.auto_castka_k_uhrade),
                "auto_pocet_treninku": str(nast.auto_pocet_treninku),
                "auto_posilat_email": "on",
                "aplikovat_na_vsechny": "1",
                "email_variant": nast.email_variant,
                "ucet_nazev_1": nast.ucet_nazev_1,
                "ucet_nazev_2": nast.ucet_nazev_2,
                "ucet_varianta_1": nast.ucet_varianta_1,
                "ucet_varianta_2": nast.ucet_varianta_2,
                "variabilni_symbol_popis": nast.variabilni_symbol_popis,
            },
        )
        self.assertEqual(response.status_code, 302)
        nast.refresh_from_db()
        self.assertEqual(nast.auto_rezim, VyuctovaniNastaveni.AutoRezim.MESICNE)
        self.assertEqual(nast.mesicni_den, 7)
        self.hrac.refresh_from_db()
        self.assertEqual(self.hrac.vyuctovani_rezim, Hrac.RezimVyuctovani.MESICNE)

    def test_post_manual_saves_global_setting(self):
        from core.models import VyuctovaniNastaveni

        nast = VyuctovaniNastaveni.load()
        nast.auto_rezim = VyuctovaniNastaveni.AutoRezim.CASTKA
        nast.save()
        self.hrac.vyuctovani_rezim = Hrac.RezimVyuctovani.CASTKA
        self.hrac.save(update_fields=["vyuctovani_rezim"])

        response = self.client.post(
            self.url,
            {
                "auto_rezim": VyuctovaniNastaveni.AutoRezim.MANUAL,
                "mesicni_den": str(nast.mesicni_den),
                "auto_limit": str(nast.auto_limit),
                "auto_castka_k_uhrade": str(nast.auto_castka_k_uhrade),
                "auto_pocet_treninku": str(nast.auto_pocet_treninku),
                "aplikovat_na_vsechny": "1",
                "email_variant": nast.email_variant,
                "ucet_nazev_1": nast.ucet_nazev_1,
                "ucet_nazev_2": nast.ucet_nazev_2,
                "ucet_varianta_1": nast.ucet_varianta_1,
                "ucet_varianta_2": nast.ucet_varianta_2,
                "variabilni_symbol_popis": nast.variabilni_symbol_popis,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            VyuctovaniNastaveni.load().auto_rezim,
            VyuctovaniNastaveni.AutoRezim.MANUAL,
        )
        # Hráčský field nemá MANUAL — zůstane beze změny; automatika bere globální nastavení.
        self.hrac.refresh_from_db()
        self.assertEqual(self.hrac.vyuctovani_rezim, Hrac.RezimVyuctovani.CASTKA)
