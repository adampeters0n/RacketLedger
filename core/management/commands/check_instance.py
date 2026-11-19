"""Kontrola připravenosti single-tenant instance (branding + produkční hosty)."""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.checks import (
    _INSECURE_SECRET_MARKERS,
    check_production_email,
    check_production_hosts,
    check_production_secret,
    check_production_storage,
)
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


def _secret_looks_insecure(key: str) -> bool:
    key = (key or "").strip()
    low = key.casefold()
    return (not key) or len(key) < 32 or any(m in low for m in _INSECURE_SECRET_MARKERS)


class Command(BaseCommand):
    help = (
        "Ověří branding instance (bez legacy Čimice/Káťa textů) a "
        "produkční ALLOWED_HOSTS / CSRF / SECRET_KEY / SMTP."
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

        # Zrcadlení Django system checks (SECRET_KEY / SMTP) pro ops výstup.
        if not settings.DEBUG:
            for msg in check_production_secret(None):
                problems.append(str(msg.msg))
            for msg in check_production_email(None):
                problems.append(f"WARN: {msg.msg}")
            for msg in check_production_storage(None):
                problems.append(f"WARN: {msg.msg}")
            for msg in check_production_hosts(None):
                if msg.id not in {"core.E001", "core.E002", "core.E003", "core.W001"}:
                    problems.append(str(msg.msg))
        else:
            if _secret_looks_insecure(settings.SECRET_KEY):
                notes.append("SECRET_KEY vypadá jako vývojový default (OK při DEBUG=True).")
            email_host = (getattr(settings, "EMAIL_HOST", "") or "").strip()
            email_user = (getattr(settings, "EMAIL_HOST_USER", "") or "").strip()
            if not (email_host and email_user):
                notes.append("SMTP není nastavené (při DEBUG console backend).")
            if getattr(settings, "USE_S3", False):
                notes.append(f"USE_S3=on, bucket={getattr(settings, 'AWS_STORAGE_BUCKET_NAME', '') or '(prázdný)'}")
            else:
                notes.append("USE_S3=off (lokální MEDIA_ROOT).")

        for line in notes:
            self.stdout.write(line)

        if problems:
            for p in problems:
                style = self.style.WARNING if p.startswith("WARN:") else self.style.ERROR
                label = "WARN" if p.startswith("WARN:") else "FAIL"
                text = p.removeprefix("WARN: ").strip()
                self.stderr.write(style(f"{label}: {text}"))
            hard = [p for p in problems if not p.startswith("WARN:")]
            if hard:
                raise CommandError(f"check_instance: {len(hard)} problém(ů).")

        self.stdout.write(self.style.SUCCESS("check_instance: OK"))
