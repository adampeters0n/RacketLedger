"""Bootstrap white-label instance: role groups, branding, optional club_admin."""

from __future__ import annotations

import getpass
import os

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError

from core.club_seed import apply_club_seed, resolve_seed
from core.roles import CLUB_ADMIN_GROUP, ensure_role_groups

_BRANDING_OPTION_KEYS = (
    "nazev",
    "email",
    "telefon",
    "adresa",
    "slogan",
    "email_odesilatel",
    "email_predmet_prefix",
    "email_podpis",
    "ucet_nazev_1",
    "ucet_varianta_1",
    "ucet_nazev_2",
    "ucet_varianta_2",
)


class Command(BaseCommand):
    help = (
        "Připraví single-tenant instanci: role groups, branding (seed nebo CLI) "
        "a volitelně club_admin účet."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed",
            default="",
            help="Slug ze seed katalogu (např. cimice). Bez seedu se branding aplikuje jen s CLI poli.",
        )
        parser.add_argument("--nazev", default="", help="Název klubu")
        parser.add_argument("--email", default="", help="Kontaktní e-mail")
        parser.add_argument("--telefon", default="", help="Telefon")
        parser.add_argument("--adresa", default="", help="Adresa")
        parser.add_argument("--slogan", default="", help="Slogan na landing")
        parser.add_argument(
            "--email-odesilatel",
            default="",
            dest="email_odesilatel",
            help='Odesílatel e-mailů, např. \'Klub <info@klub.cz>\'',
        )
        parser.add_argument(
            "--email-prefix",
            default="",
            dest="email_predmet_prefix",
            help="Prefix předmětu e-mailu",
        )
        parser.add_argument(
            "--email-podpis",
            default="",
            dest="email_podpis",
            help="Podpis e-mailů",
        )
        parser.add_argument(
            "--ucet1-nazev",
            default="",
            dest="ucet_nazev_1",
            help="Název platebního účtu 1",
        )
        parser.add_argument(
            "--ucet1",
            default="",
            dest="ucet_varianta_1",
            help="Číslo účtu 1 (např. 123/0100)",
        )
        parser.add_argument(
            "--ucet2-nazev",
            default="",
            dest="ucet_nazev_2",
            help="Název platebního účtu 2",
        )
        parser.add_argument(
            "--ucet2",
            default="",
            dest="ucet_varianta_2",
            help="Číslo účtu 2",
        )
        parser.add_argument(
            "--skip-branding",
            action="store_true",
            help="Nepřepisovat SystemNastaveni / VyuctovaniNastaveni (jen role / admin).",
        )
        parser.add_argument(
            "--create-admin",
            nargs=2,
            metavar=("USERNAME", "EMAIL"),
            help="Vytvoří (nebo aktualizuje) staff uživatele ve skupině club_admin",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Jen vypsat, co by se změnilo",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        seed_slug = (options.get("seed") or "").strip() or None
        apply_branding = self._should_apply_branding(options)

        if apply_branding:
            try:
                seed = resolve_seed(seed_slug)
            except KeyError as exc:
                raise CommandError(str(exc)) from exc
        else:
            seed = None

        overrides = {
            "nazev_klubu": options.get("nazev") or "",
            "kontakt_email": options.get("email") or "",
            "kontakt_telefon": options.get("telefon") or "",
            "kontakt_adresa": options.get("adresa") or "",
            "slogan": options.get("slogan") or "",
            "email_odesilatel": options.get("email_odesilatel") or "",
            "email_predmet_prefix": options.get("email_predmet_prefix") or "",
            "email_podpis": options.get("email_podpis") or "",
            "ucet_nazev_1": options.get("ucet_nazev_1") or "",
            "ucet_varianta_1": options.get("ucet_varianta_1") or "",
            "ucet_nazev_2": options.get("ucet_nazev_2") or "",
            "ucet_varianta_2": options.get("ucet_varianta_2") or "",
        }

        label = seed_slug or "product-defaults"
        if dry_run:
            self.stdout.write(f"Dry-run bootstrap:")
            self.stdout.write(f"  role groups: ano")
            if apply_branding:
                payload = apply_club_seed(seed, dry_run=True, overrides=overrides)
                self.stdout.write(f"  branding ({label}): {payload!r}")
            else:
                self.stdout.write("  branding: přeskočeno (--skip-branding nebo bez seed/CLI)")
            if options.get("create_admin"):
                username, email = options["create_admin"]
                self.stdout.write(f"  club_admin: {username} <{email}>")
            return

        ensure_role_groups()
        self.stdout.write("Role groups OK (platform_admin, club_admin).")

        if apply_branding:
            apply_club_seed(seed, overrides=overrides)
            self.stdout.write(self.style.SUCCESS(
                f"Branding aplikován ({label}) na SystemNastaveni / VyuctovaniNastaveni."
            ))
        else:
            self.stdout.write("Branding přeskočen (--skip-branding nebo bez seed/CLI).")

        if options.get("create_admin"):
            username, email = options["create_admin"]
            self._ensure_club_admin(username, email)

    def _should_apply_branding(self, options: dict) -> bool:
        if options.get("skip_branding"):
            return False
        if (options.get("seed") or "").strip():
            return True
        return any((options.get(key) or "").strip() for key in _BRANDING_OPTION_KEYS)

    def _ensure_club_admin(self, username: str, email: str) -> None:
        password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
        user = User.objects.filter(username=username).first()
        created = user is None

        if created:
            if not password:
                if not getattr(self.stdin, "isatty", lambda: False)():
                    raise CommandError(
                        "Pro --create-admin nastav BOOTSTRAP_ADMIN_PASSWORD "
                        "nebo spusť interaktivně."
                    )
                password = getpass.getpass(f"Heslo pro {username}: ")
                if not password:
                    raise CommandError("Heslo nesmí být prázdné.")
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
            )
        else:
            if email:
                user.email = email
            if password:
                user.set_password(password)

        user.is_staff = True
        user.is_active = True
        user.save()

        group = Group.objects.get(name=CLUB_ADMIN_GROUP)
        user.groups.add(group)

        action = "vytvořen" if created else "aktualizován"
        self.stdout.write(self.style.SUCCESS(
            f"club_admin {action}: {username} <{user.email}>"
        ))
