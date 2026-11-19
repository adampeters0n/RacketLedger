"""Role uživatelů před / při multi-tenancy.

system_admin   – Admin (jen AdamPeterka). Vidí a smí vše; volba role jen u něj.
platform_admin – Provozovatel. Celý systém, uživatelé, export/import.
club_admin     – Správce klubu. Vše co trenér + ceník (bez plateb, vyúčtování, analytiky;
                 v nastavení jen Obecné + Vzhled + Uživatelé).
club_coach     – Trenér klubu. Tréninky, hráči, trenéři, rozvrh a nastavení
                 (v nastavení jen Obecné + Vzhled + Uživatelé; bez plateb / vyúčtování / analytiky).

Do zavedení tenantů izolace dat neexistuje – role připravují hranice oprávnění.
"""

from __future__ import annotations

from django.contrib.auth.models import Group

PLATFORM_ADMIN_GROUP = "platform_admin"
CLUB_ADMIN_GROUP = "club_admin"
CLUB_COACH_GROUP = "club_coach"

# Jediný účet s rolí Admin (zobrazí se jen u něj).
SYSTEM_ADMIN_USERNAME = "AdamPeterka"

ROLE_ADMIN = "admin"
ROLE_PLATFORM = "platform"
ROLE_CLUB = "club"
ROLE_COACH = "coach"


def ensure_role_groups() -> tuple[Group, Group, Group]:
    """Vytvoří skupiny rolí, pokud ještě neexistují."""
    platform, _ = Group.objects.get_or_create(name=PLATFORM_ADMIN_GROUP)
    club, _ = Group.objects.get_or_create(name=CLUB_ADMIN_GROUP)
    coach, _ = Group.objects.get_or_create(name=CLUB_COACH_GROUP)
    return platform, club, coach


def _active_user(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and user.is_active)


def is_system_admin(user) -> bool:
    """Admin – pevně vázaný na účet AdamPeterka."""
    if not _active_user(user):
        return False
    return getattr(user, "username", None) == SYSTEM_ADMIN_USERNAME


def is_platform_admin(user) -> bool:
    if not _active_user(user):
        return False
    if is_system_admin(user):
        return True
    if user.is_superuser:
        return True
    return user.groups.filter(name=PLATFORM_ADMIN_GROUP).exists()


def is_club_admin(user) -> bool:
    """Správce klubu nebo vyšší. Trenér klubu sem nepatří."""
    if not _active_user(user):
        return False
    if is_platform_admin(user):
        return True
    if user.groups.filter(name=CLUB_ADMIN_GROUP).exists():
        return True
    # Legacy staff bez explicitní role trenéra
    if user.is_staff and not user.groups.filter(name=CLUB_COACH_GROUP).exists():
        return True
    return False


def is_club_coach(user) -> bool:
    """Trenér klubu nebo vyšší (správce / provozovatel / admin)."""
    if not _active_user(user):
        return False
    if is_club_admin(user):
        return True
    return user.groups.filter(name=CLUB_COACH_GROUP).exists()


def can_import_data(user) -> bool:
    """Destruktivní import celé DB – jen provozovatel / admin."""
    return is_platform_admin(user)


def can_export_data(user) -> bool:
    """Plný JSON dump – jen provozovatel / admin."""
    return is_platform_admin(user)


def can_manage_users(user) -> bool:
    """Správa účtů a oprávnění – provozovatel / admin."""
    return is_platform_admin(user)


def _has_club_scoped_role(user) -> bool:
    """Jen čistý správce / trenér klubu — Admin a Provozovatel nikdy.

    `_apply_role` přidává Adminovi/Provozovateli i skupinu club_admin kvůli
    Django perms; to nesmí omezit navigaci ani finance.
    """
    if not _active_user(user):
        return False
    if is_system_admin(user) or is_platform_admin(user):
        return False
    return user.groups.filter(
        name__in=(CLUB_ADMIN_GROUP, CLUB_COACH_GROUP)
    ).exists()


def can_view_all_treneri(user) -> bool:
    """Admin / provozovatel → všichni; správce a trenér → jen sebe."""
    if not _active_user(user):
        return False
    if is_platform_admin(user):
        return True
    return False


def can_view_all_users(user) -> bool:
    """Admin / provozovatel → všichni; správce a trenér → jen sebe."""
    if not _active_user(user):
        return False
    if is_platform_admin(user):
        return True
    return False


def can_access_user_admin(user) -> bool:
    """Stránka Uživatelé: provozovatel vše, ostatní role jen vlastní účet."""
    return is_club_coach(user)


def can_access_cenik(user) -> bool:
    return is_club_admin(user)


def can_view_finance(user) -> bool:
    """Platby, vyúčtování, kredity, finanční widgety – jen admin / provozovatel."""
    return is_platform_admin(user)


def can_access_platby(user) -> bool:
    return can_view_finance(user)


def can_access_vyuctovani(user) -> bool:
    return can_view_finance(user)


def can_view_hrac_kredit(user) -> bool:
    """Kredit hráče v seznamu / detailu – jen admin / provozovatel."""
    return can_view_finance(user)


def can_access_analytika(user) -> bool:
    """Analytika jen pro provozovatele / admina — ne správce ani trenér klubu."""
    return is_platform_admin(user)


def can_access_hraci(user) -> bool:
    return is_club_coach(user)


def can_access_treningy(user) -> bool:
    return is_club_coach(user)


def can_access_treneri(user) -> bool:
    return is_club_coach(user)


def can_access_rozvrh(user) -> bool:
    return is_club_coach(user)


def can_access_nastaveni(user) -> bool:
    return is_club_coach(user)


def can_access_rodiny(user) -> bool:
    """Rodiny jen pro provozovatele / admina — ne správce ani trenér klubu."""
    return is_platform_admin(user)


def nastaveni_allowed_panels(user) -> frozenset[str]:
    """Sekce v /admin/nastaveni/ podle role.

    Správce / trenér klubu → jen Obecné + Vzhled + Uživatelé.
    Provozovatel / Admin → vše.
    """
    if not can_access_nastaveni(user):
        return frozenset()
    if is_platform_admin(user):
        return frozenset(
            {"obecne", "vzhled", "provoz", "emaily", "upozorneni", "uzivatele", "nastroje"}
        )
    # Správce / trenér klubu
    return frozenset({"obecne", "vzhled", "uzivatele"})


def nav_permissions(user) -> dict[str, bool]:
    """Příznaky pro topnav / drawer / dashboard."""
    return {
        "nav_cenik": can_access_cenik(user),
        "nav_hraci": can_access_hraci(user),
        "nav_platby": can_access_platby(user),
        "nav_treningy": can_access_treningy(user),
        "nav_treneri": can_access_treneri(user),
        "nav_vyuctovani": can_access_vyuctovani(user),
        "nav_nastaveni": can_access_nastaveni(user),
        "nav_rozvrh": can_access_rozvrh(user),
        "nav_analytika": can_access_analytika(user),
        "is_system_admin": is_system_admin(user),
        "is_platform_admin": is_platform_admin(user),
        "is_club_admin": is_club_admin(user),
        "is_club_coach": is_club_coach(user),
    }
