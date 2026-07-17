"""Seed hodnoty pro konkrétní kluby – nepatří do kódu jako defaulty modelů.

Při startu nového tenanta (nebo lokálním vývoji Čimice) aplikuj přes
`python manage.py seed_club_defaults cimice`.
"""

from __future__ import annotations

from decimal import Decimal

# Generic produktové defaulty (bez konkrétního klubu)
PRODUCT_DEFAULTS = {
    "nazev_klubu": "TenisSystém",
    "email_odesilatel": "",
    "email_predmet_prefix": "[TenisSystém] ",
    "email_podpis": "S pozdravem,\n\nTenisSystém",
    "ucet_nazev_1": "Účet 1",
    "ucet_nazev_2": "Účet 2",
    "ucet_varianta_1": "",
    "ucet_varianta_2": "",
}

# První produkční tenant – Tenis Čimice
CIMICE_SEED = {
    "slug": "cimice",
    "system": {
        "nazev_klubu": "Tenis systém Čimice",
        "kontakt_email": "kptenis@volny.cz",
        "email_odesilatel": "Tenis Čimice <kptenis@volny.cz>",
        "email_predmet_prefix": "[Tenis Čimice] ",
        "email_podpis": "S pozdravem,\n\nKateřina Peterková\nTenis Čimice",
    },
    "vyuctovani": {
        "ucet_nazev_1": "Účet 1 AJ Sport",
        "ucet_nazev_2": "Účet 2 Káťa",
        "ucet_varianta_1": "2102303853/2700",
        "ucet_varianta_2": "2108539314/2700",
        "auto_limit": Decimal("5000.00"),
        "auto_castka_k_uhrade": Decimal("5000.00"),
    },
}

CLUB_SEEDS = {
    "cimice": CIMICE_SEED,
}
