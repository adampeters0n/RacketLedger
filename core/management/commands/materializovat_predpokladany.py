from django.core.management.base import BaseCommand
from django.utils import timezone as dj_tz
from datetime import datetime

from core.predpokladany import materialize_for_date


class Command(BaseCommand):
    help = (
        "Ze stálého / předpokládaného rozvrhu vytvoří chybějící tréninky na dnešek "
        "(vhodné pro Render Cron ve 22:00 Europe/Prague – zapíše tréninky daného dne)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            dest="date",
            default="",
            help="Datum YYYY-MM-DD (default: dnes).",
        )
        parser.add_argument(
            "--trener",
            dest="trener",
            default="",
            help="Volitelně jen jeden trenér (ID).",
        )

    def handle(self, *args, **options):
        date_raw = (options.get("date") or "").strip()
        target = None
        if date_raw:
            try:
                target = datetime.strptime(date_raw, "%Y-%m-%d").date()
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Neplatné datum: {date_raw}"))
                return

        result = materialize_for_date(target, trainer_id=options.get("trener") or None)
        day = result.get("date") or dj_tz.localdate().isoformat()
        self.stdout.write(
            self.style.SUCCESS(
                f"Předpokládaný {day}: vytvořeno {result['created']}, "
                f"už existovalo {result['skipped_exist']}, "
                f"přeskočeno uživatelem {result['skipped_user']}."
            )
        )
        for err in result.get("errors") or []:
            self.stderr.write(self.style.WARNING(err))
