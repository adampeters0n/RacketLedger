"""Sdílené mixiny pro Django admin."""


def system_list_per_page(default: int = 50) -> int:
    from core.models import SystemNastaveni

    try:
        return int(SystemNastaveni.load().radku_na_stranku or default)
    except Exception:
        return default


class ConfigurableListPerPageMixin:
    """Dynamický list_per_page podle SystemNastaveni."""

    list_per_page_default = 50

    def changelist_view(self, request, extra_context=None):
        original = self.list_per_page
        self.list_per_page = system_list_per_page(self.list_per_page_default)
        try:
            return super().changelist_view(request, extra_context)
        finally:
            self.list_per_page = original
