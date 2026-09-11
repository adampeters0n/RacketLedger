"""Barvy typů tréninku v rozvrhu – odvozené z ceníku."""

from __future__ import annotations

import re
import zlib

from .models import Cenik

# Stabilní paleta (bg, border, text) + dark varianty
_PALETTE: list[dict[str, str]] = [
    {"bg": "#ffedd5", "border": "#f59e0b", "text": "#7c2d12",
     "bg_dark": "rgba(180, 83, 9, 0.32)", "border_dark": "#d97706", "text_dark": "#fcd34d"},
    {"bg": "#dbeafe", "border": "#3b82f6", "text": "#1e3a8a",
     "bg_dark": "rgba(30, 64, 175, 0.35)", "border_dark": "#3b82f6", "text_dark": "#93c5fd"},
    {"bg": "#ede9fe", "border": "#8b5cf6", "text": "#4c1d95",
     "bg_dark": "rgba(76, 29, 149, 0.35)", "border_dark": "#8b5cf6", "text_dark": "#c4b5fd"},
    {"bg": "#dcfce7", "border": "#22c55e", "text": "#14532d",
     "bg_dark": "rgba(20, 83, 45, 0.35)", "border_dark": "#22c55e", "text_dark": "#86efac"},
    {"bg": "#ccfbf1", "border": "#14b8a6", "text": "#115e59",
     "bg_dark": "rgba(17, 94, 89, 0.35)", "border_dark": "#14b8a6", "text_dark": "#5eead4"},
    {"bg": "#ffe4e6", "border": "#e11d48", "text": "#9f1239",
     "bg_dark": "rgba(159, 18, 57, 0.35)", "border_dark": "#e11d48", "text_dark": "#fda4af"},
    {"bg": "#fef3c7", "border": "#eab308", "text": "#713f12",
     "bg_dark": "rgba(161, 98, 7, 0.35)", "border_dark": "#eab308", "text_dark": "#fde68a"},
    {"bg": "#e0e7ff", "border": "#6366f1", "text": "#312e81",
     "bg_dark": "rgba(55, 48, 163, 0.35)", "border_dark": "#818cf8", "text_dark": "#c7d2fe"},
    {"bg": "#fce7f3", "border": "#ec4899", "text": "#9d174d",
     "bg_dark": "rgba(157, 23, 77, 0.35)", "border_dark": "#ec4899", "text_dark": "#f9a8d4"},
    {"bg": "#e2e8f0", "border": "#64748b", "text": "#1e293b",
     "bg_dark": "rgba(51, 65, 85, 0.45)", "border_dark": "#94a3b8", "text_dark": "#cbd5e1"},
    {"bg": "#ffedd5", "border": "#ea580c", "text": "#9a3412",
     "bg_dark": "rgba(154, 52, 18, 0.35)", "border_dark": "#fb923c", "text_dark": "#fdba74"},
    {"bg": "#cffafe", "border": "#06b6d4", "text": "#155e75",
     "bg_dark": "rgba(21, 94, 117, 0.4)", "border_dark": "#22d3ee", "text_dark": "#a5f3fc"},
]

_FALLBACK = {
    "bg": "#f3f4f6", "border": "#9ca3af", "text": "#374151",
    "bg_dark": "rgba(75, 85, 99, 0.4)", "border_dark": "#9ca3af", "text_dark": "#e5e7eb",
}


def format_slug(name: str) -> str:
    s = (name or "").strip().lower()
    repl = (
        ("á", "a"), ("č", "c"), ("ď", "d"), ("é", "e"), ("ě", "e"), ("í", "i"),
        ("ň", "n"), ("ó", "o"), ("ř", "r"), ("š", "s"), ("ť", "t"), ("ú", "u"),
        ("ů", "u"), ("ý", "y"), ("ž", "z"),
    )
    for a, b in repl:
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if not s or not s[0].isalpha():
        s = f"f-{s or 'neznamy'}"
    return s


def _color_for_key(key: str) -> dict[str, str]:
    key = (key or "").strip()
    if not key:
        return dict(_FALLBACK)
    idx = zlib.adler32(key.encode("utf-8")) % len(_PALETTE)
    return dict(_PALETTE[idx])


def cenik_format_names() -> list[str]:
    """Unikátní typy tréninku z ceníku označené pro kalendář."""
    return list(
        Cenik.objects.filter(v_kalendari=True)
        .exclude(format="")
        .order_by("format")
        .values_list("format", flat=True)
        .distinct()
    )


def schedule_legend_items() -> list[dict]:
    """Položky legendy: jen typy z ceníku s „Přidat do kalendáře“."""
    items = []
    for name in cenik_format_names():
        color = _color_for_key(name)
        items.append({
            "label": name,
            "slug": format_slug(name),
            **color,
        })
    return items


def color_for_format(name: str) -> dict[str, str]:
    """Barva pro konkrétní typ (stejná jako v legendě)."""
    return _color_for_key((name or "").strip())
