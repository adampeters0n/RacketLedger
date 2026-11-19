"""Mixin: oprávnění ModelAdmin podle aplikační role (ne Django perms)."""


class RoleGateMixin:
    """has_*_permission řídí callable `role_check(user) -> bool`."""

    role_check = None

    def _role_ok(self, request) -> bool:
        check = self.role_check
        user = getattr(request, "user", None)
        return bool(check and user and check(user))

    def has_module_permission(self, request):
        return self._role_ok(request)

    def has_view_permission(self, request, obj=None):
        return self._role_ok(request)

    def has_add_permission(self, request):
        return self._role_ok(request)

    def has_change_permission(self, request, obj=None):
        return self._role_ok(request)

    def has_delete_permission(self, request, obj=None):
        return self._role_ok(request)
