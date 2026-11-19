from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _register_czech_collation(sender, connection, **kwargs):
    """SQLite: COLLATE CZECH pro správné řazení jmen (Č, Ř, Š…)."""
    if connection.vendor != "sqlite":
        return
    raw = getattr(connection, "connection", None)
    if raw is None:
        return
    from .admin_utils import czech_collate

    try:
        raw.create_collation("CZECH", czech_collate)
    except Exception:
        # Už registrováno na stejném spojení / nepodporováno
        pass


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self) -> None:
        from django.db.models.signals import post_migrate

        from core.signals import ensure_roles_on_migrate

        # Registrace system checks (produkční hosty).
        from core import checks  # noqa: F401

        post_migrate.connect(ensure_roles_on_migrate, sender=self)
        connection_created.connect(_register_czech_collation)
