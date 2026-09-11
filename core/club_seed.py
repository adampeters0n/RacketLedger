"""Seed hodnoty pro konkrétní kluby – nepatří do kódu jako defaulty modelů.

Volitelný katalog pro `bootstrap_instance --seed <slug>` /
`seed_club_defaults <slug>`.

Citlivé klubové profily (účty, osobní kontakty) patří do
``core/club_seeds_local.py`` (gitignored) — viz ``club_seeds_local.example.py``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

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

_SYSTEM_KEYS = {
    "nazev_klubu",
    "kontakt_email",
    "kontakt_telefon",
    "kontakt_adresa",
    "slogan",
    "email_odesilatel",
    "email_predmet_prefix",
    "email_podpis",
}

_VYUCTOVANI_KEYS = {
    "ucet_nazev_1",
    "ucet_nazev_2",
    "ucet_varianta_1",
    "ucet_varianta_2",
    "auto_limit",
    "auto_castka_k_uhrade",
}

# Veřejný ukázkový seed (bez citlivých údajů) — pro docs/testy.
DEMO_SEED = {
    "slug": "demo",
    "system": {
        "nazev_klubu": "Demo tenisový klub",
        "kontakt_email": "info@example.com",
        "email_odesilatel": "Demo klub <info@example.com>",
        "email_predmet_prefix": "[Demo klub] ",
        "email_podpis": "S pozdravem,\n\nDemo tenisový klub",
    },
    "vyuctovani": {
        "ucet_nazev_1": "Účet 1",
        "ucet_nazev_2": "Účet 2",
        "ucet_varianta_1": "",
        "ucet_varianta_2": "",
        "auto_limit": Decimal("5000.00"),
        "auto_castka_k_uhrade": Decimal("5000.00"),
    },
}


def _load_local_club_seeds() -> dict[str, Any]:
    """Načte CLUB_SEEDS z gitignored core/club_seeds_local.py, pokud existuje."""
    try:
        from core import club_seeds_local  # type: ignore
    except ImportError:
        return {}
    seeds = getattr(club_seeds_local, "CLUB_SEEDS", None)
    return dict(seeds) if isinstance(seeds, dict) else {}


CLUB_SEEDS: dict[str, Any] = {
    "demo": DEMO_SEED,
    **_load_local_club_seeds(),
}


def product_defaults_as_seed() -> dict[str, Any]:
    """Rozdělí PRODUCT_DEFAULTS na system / vyuctovani payload."""
    system = {k: v for k, v in PRODUCT_DEFAULTS.items() if k in _SYSTEM_KEYS}
    vyuctovani = {k: v for k, v in PRODUCT_DEFAULTS.items() if k in _VYUCTOVANI_KEYS}
    return {"slug": "product", "system": system, "vyuctovani": vyuctovani}


def resolve_seed(slug: str | None = None) -> dict[str, Any]:
    """Vrátí seed dict pro známý slug, nebo generické PRODUCT_DEFAULTS."""
    if not slug:
        return product_defaults_as_seed()
    # Obnovit katalog (local file mohl přibýt za běhu v testech).
    seeds = {"demo": DEMO_SEED, **_load_local_club_seeds()}
    seed = seeds.get(slug) or CLUB_SEEDS.get(slug)
    if not seed:
        known = ", ".join(sorted(seeds)) or "(žádné)"
        raise KeyError(f"Neznámý klub {slug!r}. Dostupné: {known}")
    return seed


def apply_club_seed(
    seed: dict[str, Any],
    *,
    dry_run: bool = False,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aplikuje seed na singleton SystemNastaveni / VyuctovaniNastaveni.

    ``overrides`` může obsahovat klíče z _SYSTEM_KEYS / _VYUCTOVANI_KEYS
    (typicky z CLI bootstrapu). Vrací finální payload (pro dry-run / log).
    """
    from core.models import SystemNastaveni, VyuctovaniNastaveni

    system_data = dict(seed.get("system") or {})
    vyuct_data = dict(seed.get("vyuctovani") or {})

    if overrides:
        for key, value in overrides.items():
            if value is None or value == "":
                continue
            if key in _SYSTEM_KEYS:
                system_data[key] = value
            elif key in _VYUCTOVANI_KEYS:
                vyuct_data[key] = value

    payload = {"system": system_data, "vyuctovani": vyuct_data}
    if dry_run:
        return payload

    system = SystemNastaveni.load()
    for key, value in system_data.items():
        setattr(system, key, value)
    system.save(sync_colors=False)

    vyuct = VyuctovaniNastaveni.load()
    for key, value in vyuct_data.items():
        setattr(vyuct, key, value)
    vyuct.save()

    return payload
