from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self) -> None:
        from django.db.models.signals import post_migrate

        from core.signals import ensure_roles_on_migrate

        # Registrace system checks (produkční hosty).
        from core import checks  # noqa: F401

        post_migrate.connect(ensure_roles_on_migrate, sender=self)
