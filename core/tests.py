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
        self.assertEqual(vyuct.amount_due, Decimal("0.00"))  # manual mode = 0

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

    def test_automatic_billing_period_covers_three_months(self):
        """Auto billing uses rolling 3-month period, not just since last closure."""
        from core.models import VyuctovaniNastaveni, _zacatek_obdobi_pro_auto_vyuctovani

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
        expected_from = _zacatek_obdobi_pro_auto_vyuctovani()
        self.assertEqual(
            timezone.localtime(vyuct.period_from).date(),
            timezone.localtime(expected_from).date(),
        )
        self.assertEqual(vyuct.charges_total, Decimal("6500.00"))


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
            "ucet_varianta_1": nast.ucet_varianta_1,
            "ucet_varianta_2": nast.ucet_varianta_2,
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
        from core.models import SystemNastaveni, VyuctovaniNastaveni

        nast = SystemNastaveni.load()
        vyuct = VyuctovaniNastaveni.load()
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
            "vychozi_sezona": nast.vychozi_sezona,
            "rozvrh_od_hodina": nast.rozvrh_od_hodina,
            "rozvrh_do_hodina": nast.rozvrh_do_hodina,
            "vychozi_zobrazeni_rozvrhu": nast.vychozi_zobrazeni_rozvrhu,
            "prah_dluhu_dashboard": nast.prah_dluhu_dashboard,
            "zvyraznit_zaporny_kredit": nast.zvyraznit_zaporny_kredit,
            "radku_na_stranku": nast.radku_na_stranku,
            "vyuctovani_rezim": vyuct.auto_rezim,
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

class RolesAndImportGuardTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group, User
        from core.roles import CLUB_ADMIN_GROUP, ensure_role_groups

        ensure_role_groups()
        self.platform = User.objects.create_superuser("platform", "p@example.com", "x")
        self.club = User.objects.create_user("club", "c@example.com", "x", is_staff=True)
        self.club.groups.add(Group.objects.get(name=CLUB_ADMIN_GROUP))

    def test_platform_vs_club_permissions(self):
        from core.roles import (
            can_export_data,
            can_import_data,
            can_manage_users,
            is_club_admin,
            is_platform_admin,
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
        self.assertTrue(can_manage_users(self.club))

    def test_club_admin_group_has_core_model_perms(self):
        from core.roles import CLUB_ADMIN_GROUP, ensure_role_groups

        ensure_role_groups()
        self.assertTrue(self.club.has_perm("core.view_hrac"))
        self.assertTrue(self.club.has_perm("core.change_trening"))
        self.assertTrue(self.club.has_perm("auth.view_user"))
        self.assertFalse(self.club.has_perm("auth.change_group"))

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
        nast.save()
        self.assertEqual(nast.email_variant_label("1"), "Hlavní účet")
        self.assertEqual(nast.get_email_variant_display(), "Hlavní účet")


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

    def test_check_instance_strict_hosts_fails_when_empty(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from django.test import override_settings

        with override_settings(DEBUG=True, ALLOWED_HOSTS=[], CSRF_TRUSTED_ORIGINS=[]):
            with self.assertRaises(CommandError):
                call_command("check_instance", "--strict-hosts")


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
