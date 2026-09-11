"""Formátování částek a měnový symbol z nastavení klubu."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.utils.translation import gettext_lazy as _

DEFAULT_MENA = "CZK"

# Optgroupy pro přehledný výběr v nastavení
MENA_CHOICES = (
    (
        _("Evropa"),
        (
            ("CZK", _("Kč – Česká koruna")),
            ("EUR", _("€ – Euro")),
            ("GBP", _("£ – Britská libra")),
            ("CHF", _("CHF – Švýcarský frank")),
            ("PLN", _("zł – Polský zlotý")),
            ("HUF", _("Ft – Maďarský forint")),
            ("RON", _("lei – Rumunský leu")),
            ("BGN", _("лв – Bulharský lev")),
            ("RSD", _("дин – Srbský dinár")),
            ("UAH", _("₴ – Ukrajinská hřivna")),
            ("TRY", _("₺ – Turecká lira")),
            ("SEK", _("kr – Švédská koruna")),
            ("NOK", _("kr – Norská koruna")),
            ("DKK", _("kr – Dánská koruna")),
            ("ISK", _("kr – Islandská koruna")),
        ),
    ),
    (
        _("Severní Amerika"),
        (
            ("USD", _("$ – Americký dolar")),
            ("CAD", _("C$ – Kanadský dolar")),
            ("MXN", _("$ – Mexické peso")),
        ),
    ),
    (
        _("Jižní Amerika"),
        (
            ("BRL", _("R$ – Brazilský real")),
            ("ARS", _("$ – Argentinské peso")),
            ("CLP", _("$ – Chilské peso")),
            ("COP", _("$ – Kolumbijské peso")),
            ("PEN", _("S/ – Peruánský sol")),
            ("UYU", _("$U – Uruguayské peso")),
        ),
    ),
    (
        _("Asie"),
        (
            ("JPY", _("¥ – Japonský jen")),
            ("CNY", _("¥ – Čínský jüan")),
            ("KRW", _("₩ – Jihokorejský won")),
            ("INR", _("₹ – Indická rupie")),
            ("IDR", _("Rp – Indonéská rupie")),
            ("THB", _("฿ – Thajský baht")),
            ("VND", _("₫ – Vietnamský dong")),
            ("MYR", _("RM – Malajsijský ringgit")),
            ("SGD", _("S$ – Singapurský dolar")),
            ("HKD", _("HK$ – Hongkongský dolar")),
            ("TWD", _("NT$ – Tchajwanský dolar")),
            ("PHP", _("₱ – Filipínské peso")),
            ("AED", _("د.إ – SAE dirham")),
            ("SAR", _("﷼ – Saúdský rijál")),
            ("ILS", _("₪ – Izraelský šekel")),
        ),
    ),
)

MENA_SYMBOLS: dict[str, str] = {
    # Evropa
    "CZK": "Kč",
    "EUR": "€",
    "GBP": "£",
    "CHF": "CHF",
    "PLN": "zł",
    "HUF": "Ft",
    "RON": "lei",
    "BGN": "лв",
    "RSD": "дин",
    "UAH": "₴",
    "TRY": "₺",
    "SEK": "kr",
    "NOK": "kr",
    "DKK": "kr",
    "ISK": "kr",
    # Severní Amerika
    "USD": "$",
    "CAD": "C$",
    "MXN": "MX$",
    # Jižní Amerika
    "BRL": "R$",
    "ARS": "AR$",
    "CLP": "CLP$",
    "COP": "COL$",
    "PEN": "S/",
    "UYU": "$U",
    # Asie
    "JPY": "¥",
    "CNY": "CN¥",
    "KRW": "₩",
    "INR": "₹",
    "IDR": "Rp",
    "THB": "฿",
    "VND": "₫",
    "MYR": "RM",
    "SGD": "S$",
    "HKD": "HK$",
    "TWD": "NT$",
    "PHP": "₱",
    "AED": "AED",
    "SAR": "SAR",
    "ILS": "₪",
}


def get_mena_code() -> str:
    try:
        from .models import SystemNastaveni

        code = getattr(SystemNastaveni.load(), "mena", None) or DEFAULT_MENA
        if code in MENA_SYMBOLS:
            return code
    except Exception:
        pass
    return DEFAULT_MENA


def get_mena_symbol(code: str | None = None) -> str:
    return MENA_SYMBOLS.get(code or get_mena_code(), MENA_SYMBOLS[DEFAULT_MENA])


def format_castka(
    value: Any,
    *,
    per_hour: bool = False,
    thousands: bool = False,
    nbsp: bool = False,
    symbol: str | None = None,
) -> str:
    """Zaokrouhlí částku a připojí měnový symbol (např. „1 250 Kč“)."""
    if value is None:
        return "—"
    try:
        amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return "—"

    if thousands:
        sep = "\u00a0" if nbsp else " "
        number = f"{amount:,.0f}".replace(",", sep)
    else:
        number = f"{amount:.0f}"

    unit = symbol if symbol is not None else get_mena_symbol()
    if per_hour:
        return f"{number} {unit}/h"
    return f"{number} {unit}"
