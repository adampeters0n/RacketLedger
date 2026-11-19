"""Připraví Stripe sandbox pro lokální test (Product + Price).

Použití:
  1) Do .env dej STRIPE_SECRET_KEY=sk_test_…
  2) python manage.py setup_stripe_sandbox
  3) Volitelně: --write-env  (zapíše STRIPE_PRICE_ID do .env)
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Vytvoří Stripe test Product/Price pro SaaS předplatné a vypíše další kroky."

    def add_arguments(self, parser):
        parser.add_argument(
            "--write-env",
            action="store_true",
            help="Zapíše STRIPE_PRICE_ID do .env (pokud soubor existuje).",
        )
        parser.add_argument(
            "--amount",
            type=int,
            default=49000,
            help="Cena v nejmenších jednotkách měny (default 49000 = 490 Kč).",
        )
        parser.add_argument(
            "--currency",
            default="",
            help="Měna Price (default STRIPE_PLAYER_CURRENCY / czk).",
        )

    def handle(self, *args, **options):
        secret = (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
        if not secret:
            raise CommandError(
                "STRIPE_SECRET_KEY není nastavený.\n"
                "1) Stripe Dashboard (Test/Sandbox) → Developers → API keys\n"
                "2) Zkopíruj Secret key (sk_test_…) do .env jako STRIPE_SECRET_KEY=...\n"
                "3) Restartuj shell / runserver a spusť znovu: python manage.py setup_stripe_sandbox"
            )
        if not secret.startswith("sk_test_"):
            self.stdout.write(
                self.style.WARNING(
                    "Varování: klíč nezačíná sk_test_ — pro lokální test použij Sandbox/Test key."
                )
            )

        existing = (getattr(settings, "STRIPE_PRICE_ID", "") or "").strip()
        if existing:
            self.stdout.write(self.style.SUCCESS(f"STRIPE_PRICE_ID už je nastavené: {existing}"))
            self._print_next_steps(price_id=existing, created=False)
            return

        import stripe

        stripe.api_key = secret
        currency = (options["currency"] or getattr(settings, "STRIPE_PLAYER_CURRENCY", "czk") or "czk").lower()
        amount = int(options["amount"])

        self.stdout.write("Vytvářím Stripe Product + recurring Price…")
        try:
            product = stripe.Product.create(
                name="TenisSystém (sandbox)",
                description="Lokální test předplatného TenisSystém",
            )
            price = stripe.Price.create(
                product=product.id,
                unit_amount=amount,
                currency=currency,
                recurring={"interval": "month"},
            )
        except Exception as exc:
            raise CommandError(f"Stripe API chyba: {exc}") from exc

        price_id = price.id
        self.stdout.write(self.style.SUCCESS(f"OK Product={product.id}"))
        self.stdout.write(self.style.SUCCESS(f"OK Price={price_id} ({amount / 100:.2f} {currency.upper()}/měsíc)"))

        if options["write_env"]:
            self._write_env_price(price_id)
        else:
            self.stdout.write(
                self.style.NOTICE(
                    f"Do .env doplň:\nSTRIPE_PRICE_ID={price_id}\n"
                    "(nebo spusť znovu s --write-env)"
                )
            )

        self._print_next_steps(price_id=price_id, created=True)

    def _write_env_price(self, price_id: str) -> None:
        env_path = Path(settings.BASE_DIR) / ".env"
        if not env_path.exists():
            raise CommandError(f".env neexistuje: {env_path}")
        text = env_path.read_text(encoding="utf-8")
        if re.search(r"^STRIPE_PRICE_ID=.*$", text, flags=re.M):
            text = re.sub(r"^STRIPE_PRICE_ID=.*$", f"STRIPE_PRICE_ID={price_id}", text, flags=re.M)
        else:
            text = text.rstrip() + f"\nSTRIPE_PRICE_ID={price_id}\n"
        env_path.write_text(text, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Zapsáno do {env_path}: STRIPE_PRICE_ID={price_id}"))

    def _print_next_steps(self, *, price_id: str, created: bool) -> None:
        base = (getattr(settings, "PUBLIC_BASE_URL", "") or "http://127.0.0.1:8000").rstrip("/")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Další kroky (lokální test)"))
        self.stdout.write(
            "1) Stripe CLI webhook (druhý terminál):\n"
            "   brew install stripe/stripe-cli/stripe\n"
            "   stripe login\n"
            f"   stripe listen --forward-to {base}/stripe/webhook/\n"
            "   → zkopíruj whsec_… do .env jako STRIPE_WEBHOOK_SECRET=...\n"
            "2) Restart: python manage.py runserver\n"
            "3) Admin → Nastavení → Předplatné → Aktivovat předplatné\n"
            "   Test karta: 4242 4242 4242 4242\n"
            "4) Admin → Nastavení → Platby hráčů → Propojit Stripe\n"
            "5) Vygeneruj vyúčtování s částkou → v konzoli/e-mailu odkaz Zaplatit\n"
        )
        if created:
            self.stdout.write(f"Price ID: {price_id}")
