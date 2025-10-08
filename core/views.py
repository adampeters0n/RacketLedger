# core/views.py
from django.shortcuts import render
from django.urls import reverse, NoReverseMatch
from django.utils import timezone


def _admin_url(name: str) -> str:
    """Bezpečný reverse do adminu s fallbackem na /admin/."""
    try:
        return reverse(f"admin:{name}")
    except NoReverseMatch:
        return "/admin/"


def _first_existing_admin_url(*names: str) -> str:
    """Vrať první existující admin URL z předaných jmen, jinak /admin/."""
    for n in names:
        try:
            return reverse(f"admin:{n}")
        except NoReverseMatch:
            continue
    return "/admin/"


def home(request):
    ctx = {
        "pricing_url":     _admin_url("core_cenik_changelist"),
        "players_url":     _admin_url("core_hrac_changelist"),
        "payments_url":    _admin_url("core_transakce_changelist"),
        "trainings_url":   _admin_url("core_trening_changelist"),
        "admin_index_url": _admin_url("index"),
        "new_training_url": _admin_url("core_trening_add"),
        "coaches_url": _first_existing_admin_url(
            # nové jméno (top-level /admin/core/treneri/)
            "core_treneri_summary",
            # starší jméno (pokud by někde ještě bylo)
            "core_trening_treneri_summary",
        ),
        "now": timezone.now(),
    }
    return render(request, "home/landing.html", ctx)
