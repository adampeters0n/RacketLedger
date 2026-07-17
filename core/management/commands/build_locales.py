"""Vygeneruje a zkompiluje překlady pro všechny jazyky systému."""

import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core.i18n_config import SYSTEM_LANGUAGE_CODES
from core.i18n_supplement import supplement_for
from core.po_utils import inject_missing_po_entries, remove_obsolete_po_entries, update_po_translations
from core.translation_catalog import TRANSLATIONS


def merged_catalog(lang: str) -> dict[str, str]:
    catalog = dict(TRANSLATIONS.get(lang, {}))
    catalog.update(supplement_for(lang))
    return catalog


class Command(BaseCommand):
    help = "Extrahuje řetězce (makemessages), doplní překlady z katalogu a zkompiluje .mo soubory."

    def handle(self, *args, **options):
        base_dir = Path(settings.BASE_DIR)
        locale_dir = base_dir / "locale"
        locale_dir.mkdir(exist_ok=True)

        langs = [code for code in SYSTEM_LANGUAGE_CODES if code != settings.LANGUAGE_CODE]
        lang_args = []
        for code in langs:
            lang_args.extend(["-l", code])

        self.stdout.write("Spouštím makemessages…")
        subprocess.run(
            [
                "python3",
                "manage.py",
                "makemessages",
                "--no-location",
                *lang_args,
                "--ignore=venv/*",
                "--ignore=staticfiles/*",
                "--ignore=data/*",
            ],
            cwd=base_dir,
            check=True,
        )

        filled = 0
        for lang in langs:
            po_path = locale_dir / lang / "LC_MESSAGES" / "django.po"
            if not po_path.exists():
                self.stderr.write(f"Chybí {po_path}")
                continue
            catalog = merged_catalog(lang)
            text = po_path.read_text(encoding="utf-8")
            text = remove_obsolete_po_entries(text)
            text, injected = inject_missing_po_entries(text, catalog)
            updated, count = update_po_translations(text, catalog)
            po_path.write_text(updated, encoding="utf-8")
            filled += count + injected

        self.stdout.write(f"Doplněno {filled} překladů z katalogu.")

        empty_total = 0
        for lang in langs:
            po_path = locale_dir / lang / "LC_MESSAGES" / "django.po"
            if not po_path.exists():
                continue
            from core.po_utils import parse_po

            entries = parse_po(po_path.read_text(encoding="utf-8"))
            empty = [e.msgid for e in entries if e.msgid and not e.msgstr.strip()]
            if empty:
                empty_total += len(empty)
                self.stderr.write(f"  {lang}: {len(empty)} prázdných překladů")
        if empty_total:
            self.stderr.write(self.style.WARNING(f"Celkem {empty_total} prázdných msgstr – doplňte do katalogu."))

        self.stdout.write("Spouštím compilemessages…")
        compile_args = ["python3", "manage.py", "compilemessages", "--ignore=venv/*"]
        for code in langs:
            compile_args.extend(["-l", code])
        subprocess.run(compile_args, cwd=base_dir, check=True)
        self.stdout.write(self.style.SUCCESS("Překlady připraveny."))
