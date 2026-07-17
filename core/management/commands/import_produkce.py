"""Import JSON dumpu do lokální SQLite databáze."""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.data_import import import_dump_file, validate_dump_file

DEFAULT_INPUT = Path("data/production_dump.json")


class Command(BaseCommand):
    help = (
        "Naimportuje export z produkce do lokální SQLite. "
        "Smaže stávající db.sqlite3 a znovu spustí migrate."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "input",
            nargs="?",
            default=str(DEFAULT_INPUT),
            help=f"JSON soubor (výchozí: {DEFAULT_INPUT})",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Nepotvrzovat smazání lokální databáze",
        )

    def handle(self, *args, **options):
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError(
                "Import lze spustit jen proti lokální SQLite. "
                "V .env odstraň DATABASE_URL a zkus znovu."
            )

        dump_path = Path(options["input"])
        if not dump_path.is_file():
            raise CommandError(
                f"Soubor {dump_path} neexistuje. "
                "Nejdřív spusť export_produkce (viz návod v odpovědi / scripts/import_z_produkce.sh)."
            )

        try:
            record_count = validate_dump_file(dump_path)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(f"Soubor {dump_path} není platný JSON: {exc}") from exc

        self.stdout.write(f"Dump OK – {record_count} záznamů.")

        db_path = Path(settings.DATABASES["default"]["NAME"])
        if db_path.exists() and not options["no_input"]:
            self.stdout.write(self.style.WARNING(
                f"Lokální databáze {db_path} bude smazána a nahrazena daty z produkce."
            ))
            if input("Pokračovat? [y/N] ").strip().lower() != "y":
                self.stdout.write("Zrušeno.")
                return

        backup = import_dump_file(dump_path, backup=True)
        if backup:
            self.stdout.write(f"Záloha: {backup}")

        self.stdout.write(self.style.SUCCESS(
            "Hotovo. Přihlas se stejným jménem a heslem jako v exportovaném prostředí."
        ))
