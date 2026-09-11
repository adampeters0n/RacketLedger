"""Aplikuje seed branding / účty pro známý klub (alias na bootstrap seed část)."""

from django.core.management.base import BaseCommand, CommandError

from core.club_seed import CLUB_SEEDS, apply_club_seed, resolve_seed


class Command(BaseCommand):
    help = (
        "Nastaví branding a platební údaje podle seed dat klubu. "
        "Slug je povinný (viz katalog v core/club_seed.py)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "slug",
            help=f"Slug klubu ze seed katalogu. Dostupné: {', '.join(sorted(CLUB_SEEDS)) or '(žádné)'}",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Jen vypsat, co by se změnilo",
        )

    def handle(self, *args, **options):
        slug = (options["slug"] or "").strip()
        if not slug:
            known = ", ".join(sorted(CLUB_SEEDS)) or "(žádné)"
            raise CommandError(f"Zadej slug klubu. Dostupné: {known}")

        try:
            seed = resolve_seed(slug)
        except KeyError as exc:
            raise CommandError(str(exc)) from exc

        if options["dry_run"]:
            self.stdout.write(f"Dry-run seed pro {slug}:")
            self.stdout.write(repr(apply_club_seed(seed, dry_run=True)))
            return

        apply_club_seed(seed)
        self.stdout.write(self.style.SUCCESS(
            f"Seed „{slug}“ aplikován na SystemNastaveni / VyuctovaniNastaveni."
        ))
