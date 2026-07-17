"""Sdílená logika importu JSON dumpu (management command + admin)."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command


class ImportNotAllowed(RuntimeError):
    """Import celé DB není v tomto prostředí povolen."""


def is_sqlite_database() -> bool:
    return settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"


def assert_full_db_import_allowed() -> None:
    """Destruktivní import jen proti lokální SQLite (nikdy Postgres / produkce)."""
    if not is_sqlite_database():
        raise ImportNotAllowed(
            "Import celé databáze je povolen jen proti lokální SQLite. "
            "Na Postgres / produkci je vypnutý."
        )


def validate_dump_json(raw: str) -> list:
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise ValueError("Soubor je prázdný nebo má špatný formát.")
    return data


def validate_dump_file(path: Path) -> int:
    with path.open(encoding="utf-8") as fh:
        return len(validate_dump_json(fh.read()))


def import_dump_file(path: Path, *, backup: bool = True) -> Path | None:
    """Naimportuje JSON do SQLite. Vrátí cestu zálohy DB nebo None."""
    assert_full_db_import_allowed()
    validate_dump_file(path)

    db_path = Path(settings.DATABASES["default"]["NAME"])
    backup_path = None
    if db_path.exists():
        if backup:
            backup_path = db_path.with_suffix(
                f".sqlite3.bak.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            )
            shutil.copy2(db_path, backup_path)
        db_path.unlink()

    journal = db_path.with_suffix(".sqlite3-journal")
    if journal.exists():
        journal.unlink()

    call_command("migrate", verbosity=0, interactive=False)
    call_command("loaddata", str(path), verbosity=0)
    return backup_path
