"""Barevné varianty (Excel-style) a CSS proměnné pro admin."""

from __future__ import annotations

import re
from typing import Any

from django.utils.translation import gettext_lazy as _

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

DEFAULT_THEME = "oranzova"

COLOR_KEYS = (
    "brand",
    "brand_600",
    "brand_100",
    "bg",
    "surface",
    "text",
    "text_strong",
    "table_head",
    "table_row_alt",
    "table_row_hover",
    "line",
)

MODEL_FIELD_MAP = {
    "brand": "barva_brand",
    "brand_600": "barva_brand_600",
    "brand_100": "barva_brand_100",
    "bg": "barva_pozadi",
    "surface": "barva_plochy",
    "text": "barva_text",
    "text_strong": "barva_text_silny",
    "table_head": "barva_tabulka_hlava",
    "table_row_alt": "barva_tabulka_radek",
    "table_row_hover": "barva_tabulka_hover",
    "line": "barva_ohraniceni",
}

# 6 palet ve stylu Microsoft Excel – pruh 6 barev + odvozené UI barvy
THEME_VARIANTS: dict[str, dict[str, Any]] = {
    "oranzova": {
        "label": _("Tenis"),
        "description": _("Výchozí vzhled systému"),
        "brand": "#E67817",
        "brand_600": "#D1640C",
        "brand_100": "#FFF1DE",
        "stripe": ("#D1640C", "#E67817", "#F59E0B", "#FFF1DE", "#14833B", "#64748B"),
    },
    "modra": {
        "label": _("Modrá"),
        "description": _("Profesionální modrá paleta"),
        "brand": "#2563EB",
        "brand_600": "#1D4ED8",
        "brand_100": "#EFF6FF",
        "stripe": ("#1D4ED8", "#2563EB", "#3B82F6", "#BFDBFE", "#0891B2", "#64748B"),
    },
    "zelena": {
        "label": _("Zelená"),
        "description": _("Klubová sportovní zelená"),
        "brand": "#14833B",
        "brand_600": "#0F6B2E",
        "brand_100": "#E9F7EE",
        "stripe": ("#0F6B2E", "#14833B", "#22C55E", "#BBF7D0", "#2563EB", "#64748B"),
    },
    "cervena": {
        "label": _("Teplá"),
        "description": _("Energetická červeno-oranžová"),
        "brand": "#DC2626",
        "brand_600": "#B91C1C",
        "brand_100": "#FEF2F2",
        "stripe": ("#B91C1C", "#DC2626", "#F97316", "#FED7AA", "#E67817", "#64748B"),
    },
    "fialova": {
        "label": _("Fialová"),
        "description": _("Výrazná fialová paleta"),
        "brand": "#7C3AED",
        "brand_600": "#6D28D9",
        "brand_100": "#F5F3FF",
        "stripe": ("#6D28D9", "#7C3AED", "#A78BFA", "#DDD6FE", "#EC4899", "#64748B"),
    },
    "seda": {
        "label": _("Neutrální"),
        "description": _("Stupně šedé – klidný vzhled"),
        "brand": "#475569",
        "brand_600": "#334155",
        "brand_100": "#F1F5F9",
        "stripe": ("#1E293B", "#475569", "#94A3B8", "#CBD5E1", "#64748B", "#F8FAFC"),
    },
}

THEME_CHOICES = [(key, meta["label"]) for key, meta in THEME_VARIANTS.items()]


def _mix(hex_a: str, hex_b: str, ratio: float) -> str:
    a = _hex_to_rgb(hex_a)
    b = _hex_to_rgb(hex_b)
    r = round(a[0] * (1 - ratio) + b[0] * ratio)
    g = round(a[1] * (1 - ratio) + b[1] * ratio)
    bl = round(a[2] * (1 - ratio) + b[2] * ratio)
    return f"#{r:02X}{g:02X}{bl:02X}"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def normalize_hex(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value.startswith("#"):
        value = f"#{value}"
    if not HEX_RE.match(value):
        return None
    return value.upper()


def _palette(brand: str, brand_600: str, brand_100: str, *, light: bool) -> dict[str, str]:
    if light:
        return {
            "brand": brand,
            "brand_600": brand_600,
            "brand_100": brand_100,
            "bg": "#F7F7F4",
            "surface": "#FFFFFF",
            "text": "#1F2937",
            "text_strong": "#111111",
            "table_head": _mix(brand_100, brand, 0.35) if brand_100 != "#FFF1DE" else "#FFE9A6",
            "table_row_alt": _mix(brand_100, "#FFFFFF", 0.55),
            "table_row_hover": _mix(brand_100, "#FFFFFF", 0.25),
            "line": "#E2E5EA",
            "muted": "#64748B",
        }
    return {
        "brand": brand,
        "brand_600": brand_600,
        "brand_100": _mix(brand, "#111827", 0.82),
        "bg": "#111827",
        "surface": "#1F2937",
        "text": "#E5E7EB",
        "text_strong": "#F9FAFB",
        "table_head": _mix(brand, "#1F2937", 0.68),
        "table_row_alt": "#1A2332",
        "table_row_hover": _mix(brand, "#1F2937", 0.86),
        "line": "#374151",
        "muted": "#9CA3AF",
    }


def preset_colors(variant: str, *, dark: bool) -> dict[str, str]:
    meta = THEME_VARIANTS.get(variant, THEME_VARIANTS[DEFAULT_THEME])
    return _palette(meta["brand"], meta["brand_600"], meta["brand_100"], light=not dark)


def resolve_theme_colors(nastaveni) -> dict[str, str]:
    variant = getattr(nastaveni, "barevna_varianta", None) or DEFAULT_THEME
    if variant not in THEME_VARIANTS:
        variant = DEFAULT_THEME
    dark = bool(getattr(nastaveni, "tmavy_rezim", False))
    colors = preset_colors(variant, dark=dark)

    # Vlastní barvy z DB jen když je explicitně zapnutý režim vlastních barev.
    if getattr(nastaveni, "vlastni_barvy", False):
        for key, field in MODEL_FIELD_MAP.items():
            override = normalize_hex(getattr(nastaveni, field, None))
            if override:
                colors[key] = override

    return colors


def css_vars_dict(colors: dict[str, str]) -> dict[str, str]:
    return {
        "--brand": colors["brand"],
        "--brand-600": colors["brand_600"],
        "--brand-100": colors["brand_100"],
        "--bg": colors["bg"],
        "--surface": colors["surface"],
        "--text": colors["text"],
        "--text-strong": colors["text_strong"],
        "--line": colors["line"],
        "--amber-100": colors["brand_100"],
        "--amber-200": colors["table_head"],
        "--table-head": colors["table_head"],
        "--table-row-alt": colors["table_row_alt"],
        "--table-row-hover": colors["table_row_hover"],
        "--muted": colors.get("muted", "#64748B"),
    }


def css_vars_style_block(colors: dict[str, str], *, dark: bool) -> str:
    vars_map = css_vars_dict(colors)
    lines = "\n".join(f"  {k}: {v};" for k, v in vars_map.items())
    scheme = "dark" if dark else "light"
    return f"html {{\n{lines}\n  color-scheme: {scheme};\n}}"


def presets_for_js() -> dict[str, dict[str, dict[str, str]]]:
    return {
        key: {
            "light": preset_colors(key, dark=False),
            "dark": preset_colors(key, dark=True),
        }
        for key in THEME_VARIANTS
    }


def theme_options_for_template() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "label": meta["label"],
            "description": meta["description"],
            "stripe": meta["stripe"],
        }
        for key, meta in THEME_VARIANTS.items()
    ]
