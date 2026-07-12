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

        # Generate first billing
        vyuct1 = self.hrac.vygeneruj_vyuctovani(
            duvod="manual",
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
            "ucet_varianta_1": nast.ucet_varianta_1,
            "ucet_varianta_2": nast.ucet_varianta_2,
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