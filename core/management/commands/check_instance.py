"""Kontrola připravenosti single-tenant instance (branding + produkční hosty)."""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import SystemNastaveni, VyuctovaniNastaveni

_LEGACY_MARKERS = (
    "čimice",
    "cimice",
    "káťa",
    "kata",
    "kptenis",
    "kateřina peterková",
    "katerina peterkova",
    "aj sport",
)


def _contains_legacy(value: str) -> bool:
    low = (value or "").casefold()
    return any(marker in low for marker in _LEGACY_MARKERS)


class Command(BaseCommand):
    help = (
        "Ověří branding instance (bez legacy Čimice/Káťa textů) a "
        "produkční ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict-hosts",
            action="store_true",
            help="I při DEBUG=True vyžaduj neprázdné ALLOWED_HOSTS a CSRF_TRUSTED_ORIGINS.",
        )
        parser.add_argument(
            "--allow-legacy",
            action="store_true",
            help="Nepovažuj legacy klubové texty v DB za chybu (seed cimice).",
        )

    def handle(self, *args, **options):
        problems: list[str] = []
        notes: list[str] = []

        nast = SystemNastaveni.load()
        vyuct = VyuctovaniNastaveni.load()

        brand_fields = {
            "nazev_klubu": nast.nazev_klubu,
            "kontakt_email": nast.kontakt_email,
            "email_odesilatel": nast.email_odesilatel,
            "email_predmet_prefix": nast.email_predmet_prefix,
            "email_podpis": nast.email_podpis,
            "ucet_nazev_1": vyuct.ucet_nazev_1,
            "ucet_nazev_2": vyuct.ucet_nazev_2,
            "ucet_varianta_1": vyuct.ucet_varianta_1,
            "ucet_varianta_2": vyuct.ucet_varianta_2,
        }
        legacy_hits = [k for k, v in brand_fields.items() if _contains_legacy(str(v))]
        if legacy_hits and not options["allow_legacy"]:
            problems.append(
                "Legacy klubové texty v DB: "
                + ", ".join(legacy_hits)
                + " — spusť bootstrap_instance --nazev … nebo migraci scrub."
            )
        elif legacy_hits:
            notes.append("Legacy texty přítomné (--allow-legacy).")

        notes.append(f"Klub: {nast.nazev_klubu or '(prázdný)'}")
        notes.append(f"Kontakt: {nast.kontakt_email or '(prázdný)'}")
        notes.append(f"E-mail odesílatel: {nast.email_odesilatel or '(prázdný)'}")

        check_hosts = (not settings.DEBUG) or options["strict_hosts"]
        hosts = [h for h in (settings.ALLOWED_HOSTS or []) if h]
        origins = [o for o in (settings.CSRF_TRUSTED_ORIGINS or []) if o]

        if check_hosts:
            if not hosts:
                problems.append("ALLOWED_HOSTS je prázdné.")
            elif hosts == ["*"]:
                problems.append("ALLOWED_HOSTS=['*'] není vhodné pro produkci.")
            if not origins:
                problems.append("CSRF_TRUSTED_ORIGINS je prázdné.")
            else:
                bad = [o for o in origins if not o.startswith(("http://", "https://"))]
                if bad:
                    problems.append(
                        "CSRF_TRUSTED_ORIGINS bez schématu: " + ", ".join(bad[:5])
                    )
            notes.append(f"ALLOWED_HOSTS: {', '.join(hosts) or '(prázdné)'}")
            notes.append(f"CSRF_TRUSTED_ORIGINS: {', '.join(origins) or '(prázdné)'}")
        else:
            notes.append("Host check přeskočen (DEBUG=True; použij --strict-hosts).")

        for line in notes:
            self.stdout.write(line)

        if problems:
            for p in problems:
                self.stderr.write(self.style.ERROR(f"FAIL: {p}"))
            raise CommandError(f"check_instance: {len(problems)} problém(ů).")

        self.stdout.write(self.style.SUCCESS("check_instance: OK"))
