"""Sdílená logika exportu dat (management command + admin)."""
from __future__ import annotations

import io
import json

from django.conf import settings
from django.core.management import call_command
from django.db import connections

EXPORT_EXCLUDE = (
    "contenttypes",
    "auth.permission",
    "sessions",
    "admin.logentry",
)


def _prepare_postgres_export() -> None:
    engine = settings.DATABASES["default"]["ENGINE"]
    if "postgresql" not in engine:
        return
    settings.DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
    connections.close_all()


def build_production_dump_json() -> str:
    """Vrátí JSON dump auth.user + core modelů."""
    _prepare_postgres_export()
    buf = io.StringIO()
    call_command(
        "dumpdata",
        "auth.user",
        "core",
        natural_foreign=True,
        natural_primary=True,
        indent=2,
        stdout=buf,
        exclude=list(EXPORT_EXCLUDE),
    )
    raw = buf.getvalue()
    json.loads(raw)
    return raw
