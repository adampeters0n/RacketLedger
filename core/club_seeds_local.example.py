"""Příklad lokálních klubových seedů — zkopíruj jako club_seeds_local.py.

Soubor ``club_seeds_local.py`` je v .gitignore (účty, osobní kontakty).

  cp core/club_seeds_local.example.py core/club_seeds_local.py

Pak doplň reálné údaje a spusť:

  python manage.py bootstrap_instance --seed cimice
"""

from __future__ import annotations

from decimal import Decimal

# Příklad profilu — nahraď placeholdery skutečnými údaji (necommituj).
CIMICE_SEED = {
    "slug": "cimice",
    "system": {
        "nazev_klubu": "Tenis systém Čimice",
        "kontakt_email": "REPLACE_ME@example.com",
        "email_odesilatel": "Tenis Čimice <REPLACE_ME@example.com>",
        "email_predmet_prefix": "[Tenis Čimice] ",
        "email_podpis": "S pozdravem,\n\nTenis Čimice",
    },
    "vyuctovani": {
        "ucet_nazev_1": "Účet 1",
        "ucet_nazev_2": "Účet 2",
        "ucet_varianta_1": "XXXXXX/XXXX",
        "ucet_varianta_2": "XXXXXX/XXXX",
        "auto_limit": Decimal("5000.00"),
        "auto_castka_k_uhrade": Decimal("5000.00"),
    },
}

CLUB_SEEDS = {
    "cimice": CIMICE_SEED,
}
