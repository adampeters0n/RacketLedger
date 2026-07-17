"""Export dat z databáze do JSON (pro přenos na lokální vývoj)."""
import io
import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

DEFAULT_OUTPUT = Path("data/production_dump.json")

EXCLUDE = (
    "contenttypes",
    "auth.permission",
    "sessions",
    "admin.logentry",
)


class Command(BaseCommand):
    help = (
        "Exportuje data z databáze do JSON souboru. "
        "Spusť na Renderu, nebo lokálně s DATABASE_URL z Neonu."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "-o",
            "--output",
            default=str(DEFAULT_OUTPUT),
            help=f"Cílový soubor (výchozí: {DEFAULT_OUTPUT})",
        )
        parser.add_argument(
            "--stdout",
            action="store_true",
            help="Vypsat JSON na stdout místo do souboru",
        )

    def _prepare_postgres_export(self):
        """Postgres + dumpdata: vypnout server-side cursory (jinak 'cursor already exists')."""
        engine = settings.DATABASES["default"]["ENGINE"]
        if "postgresql" not in engine:
            return
        settings.DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
        connections.close_all()

    def _run_dump(self, stdout):
        call_command(
            "dumpdata",
            "auth.user",
            "core",
            natural_foreign=True,
            natural_primary=True,
            indent=2,
            stdout=stdout,
            exclude=list(EXCLUDE),
        )

    def handle(self, *args, **options):
        output_path = Path(options["output"])
        to_stdout = options["stdout"]

        self.stdout.write("Exportuji data (může trvat desítky sekund)…")

        from core.data_export import build_production_dump_json

        try:
            raw = build_production_dump_json()
        except json.JSONDecodeError as exc:
            raise CommandError(
                f"Export vytvořil neplatný JSON ({exc}). "
                "Zkus export znovu – možná se přerušilo připojení k Neonu."
            ) from exc

        data = json.loads(raw)

        if to_stdout:
            self.stdout.write(raw)
            return

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=".dump_tmp_",
            suffix=".json",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(raw)

        tmp_path.replace(output_path)
        size_kb = output_path.stat().st_size / 1024
        self.stdout.write(self.style.SUCCESS(
            f"Hotovo: {output_path} ({size_kb:.0f} KB, {len(data)} záznamů)\n"
            f"Databáze: {settings.DATABASES['default']['ENGINE']}"
        ))
