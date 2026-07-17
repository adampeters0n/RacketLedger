"""Role uživatelů před / při multi-tenancy.

platform_admin  – provozovatel SaaS (superuser nebo skupina). Vidí vše, smí
                  importovat/exportovat celou DB, spravovat uživatele.
club_admin      – správce klubu (staff). Provozní data klubu; po tenantech
                  bude omezen na svůj tenant.

Do zavedení tenantů jsou všichni staff zároveň club_admin. Isolace dat
zatím neexistuje – role připravují hranice oprávnění.
"""

from __future__ import annotations

from django.contrib.auth.models import Group

PLATFORM_ADMIN_GROUP = "platform_admin"
CLUB_ADMIN_GROUP = "club_admin"


def ensure_role_groups() -> tuple[Group, Group]:
    """Vytvoří skupiny rolí, pokud ještě neexistují."""
    platform, _ = Group.objects.get_or_create(name=PLATFORM_ADMIN_GROUP)
    club, _ = Group.objects.get_or_create(name=CLUB_ADMIN_GROUP)
    return platform, club


def is_platform_admin(user) -> bool:
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=PLATFORM_ADMIN_GROUP).exists()


def is_club_admin(user) -> bool:
    """Správce klubu – dnes každý staff; platform admin má práva také."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if is_platform_admin(user):
        return True
    if user.groups.filter(name=CLUB_ADMIN_GROUP).exists():
        return True
    return bool(user.is_staff)


def can_import_data(user) -> bool:
    """Destruktivní import celé DB – jen platform admin."""
    return is_platform_admin(user)


def can_export_data(user) -> bool:
    """Plný JSON dump – jen platform admin (po tenantech: scoped export)."""
    return is_platform_admin(user)


def can_manage_users(user) -> bool:
    """Správa účtů a oprávnění – platform admin."""
    return is_platform_admin(user)
