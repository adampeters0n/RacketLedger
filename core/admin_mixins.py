"""Sdílené mixiny pro Django admin."""


def system_list_per_page(default: int = 50, user=None) -> int:
    from core.models import SystemNastaveni

    if user is not None and getattr(user, "is_authenticated", False):
        try:
            prefs = user.vzhled
            if prefs.radku_na_stranku:
                return int(prefs.radku_na_stranku)
        except Exception:
            pass
    try:
        return int(SystemNastaveni.load().radku_na_stranku or default)
    except Exception:
        return default


class ConfigurableListPerPageMixin:
    """Dynamický list_per_page podle osobní preference / SystemNastaveni."""

    list_per_page_default = 50

    def changelist_view(self, request, extra_context=None):
        original = self.list_per_page
        self.list_per_page = system_list_per_page(
            self.list_per_page_default,
            user=getattr(request, "user", None),
        )
        try:
            return super().changelist_view(request, extra_context)
        finally:
            self.list_per_page = original
