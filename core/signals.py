"""Signal handlers for the core app."""

from __future__ import annotations


def ensure_roles_on_migrate(sender, app_config, **kwargs) -> None:
    """Po migrate synchronizuj role groups + Django permissions.

    Bez bootstrapu by jinak staff bez přiřazených perms dostával 403 v adminu.
    """
    if app_config.name != "core":
        return
    try:
        from core.roles import ensure_role_groups

        ensure_role_groups()
    except Exception:
        # Během raných migrací (před auth tabulkami) tiše přeskočit.
        pass
