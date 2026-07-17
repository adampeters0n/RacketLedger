"""Aplikuje seed branding / účty pro známý klub (zatím singleton nastavení)."""

from django.core.management.base import BaseCommand, CommandError

from core.club_seed import CLUB_SEEDS
from core.models import SystemNastaveni, VyuctovaniNastaveni


class Command(BaseCommand):
    help = "Nastaví branding a platební údaje podle seed dat klubu (např. cimice)."

    def add_arguments(self, parser):
        parser.add_argument(
            "slug",
            nargs="?",
            default="cimice",
            help="Slug klubu ze seed katalogu (výchozí: cimice)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Jen vypsat, co by se změnilo",
        )

    def handle(self, *args, **options):
        slug = options["slug"]
        seed = CLUB_SEEDS.get(slug)
        if not seed:
            known = ", ".join(sorted(CLUB_SEEDS))
            raise CommandError(f"Neznámý klub {slug!r}. Dostupné: {known}")

        if options["dry_run"]:
            self.stdout.write(f"Dry-run seed pro {slug}:")
            self.stdout.write(repr(seed))
            return

        system = SystemNastaveni.load()
        for key, value in seed.get("system", {}).items():
            setattr(system, key, value)
        system.save(sync_colors=False)

        vyuct = VyuctovaniNastaveni.load()
        for key, value in seed.get("vyuctovani", {}).items():
            setattr(vyuct, key, value)
        vyuct.save()

        self.stdout.write(self.style.SUCCESS(
            f"Seed „{slug}“ aplikován na SystemNastaveni / VyuctovaniNastaveni."
        ))
