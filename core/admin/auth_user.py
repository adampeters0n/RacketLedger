"""Úpravy Django auth admin – správa uživatelů pro club/platform admin."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group, User
from django.utils.translation import gettext_lazy as _

from core.roles import (
    CLUB_ADMIN_GROUP,
    PLATFORM_ADMIN_GROUP,
    can_manage_users,
    ensure_role_groups,
    is_platform_admin,
)

admin.site.unregister(User)

_PRIVILEGED_FIELDS = frozenset({"is_superuser", "groups", "user_permissions"})


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_filter = ()
    change_list_template = "admin/auth/user/change_list.html"
    change_form_template = "admin/auth/user/change_form.html"
    add_form_template = "admin/auth/user/change_form.html"

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Osobní údaje", {"fields": ("first_name", "last_name", "email")}),
        (
            "Oprávnění",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Důležitá data", {"fields": ("last_login", "date_joined")}),
    )
    club_admin_fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Osobní údaje", {"fields": ("first_name", "last_name", "email")}),
        (
            "Oprávnění",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                ),
                "description": _(
                    "Staff status musí být zapnutý, jinak uživatel neuvidí admin."
                ),
            },
        ),
        ("Důležitá data", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2", "email", "is_staff"),
                "description": _(
                    "Nový účet pro správu klubu: zapněte Staff status "
                    "(výchozí zapnuto), jinak se nepřihlásí do adminu."
                ),
            },
        ),
    )
    club_admin_add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2", "email", "is_staff"),
                "description": _(
                    "Nový účet dostane přístup do adminu (Staff) a roli club_admin."
                ),
            },
        ),
    )

    def has_module_permission(self, request):
        return can_manage_users(request.user)

    def has_view_permission(self, request, obj=None):
        return can_manage_users(request.user)

    def has_add_permission(self, request):
        return can_manage_users(request.user)

    def has_change_permission(self, request, obj=None):
        return can_manage_users(request.user)

    def has_delete_permission(self, request, obj=None):
        return can_manage_users(request.user)

    def get_fieldsets(self, request, obj=None):
        if not obj:
            if is_platform_admin(request.user):
                return self.add_fieldsets
            return self.club_admin_add_fieldsets
        if not is_platform_admin(request.user):
            return self.club_admin_fieldsets
        return super().get_fieldsets(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "is_staff" in form.base_fields and obj is None:
            form.base_fields["is_staff"].initial = True
            form.base_fields["is_staff"].help_text = _(
                "Bez Staff statusu se uživatel nedostane do admin rozhraní."
            )
        if is_platform_admin(request.user):
            return form
        for name in _PRIVILEGED_FIELDS:
            form.base_fields.pop(name, None)
        return form

    def save_model(self, request, obj, form, change):
        if not is_platform_admin(request.user):
            if change:
                previous = User.objects.filter(pk=obj.pk).first()
                if previous is not None:
                    obj.is_superuser = previous.is_superuser
            else:
                obj.is_superuser = False
            # Club admin: vždy staff (i když by někdo odškrtl).
            if not change:
                obj.is_staff = True

        super().save_model(request, obj, form, change)

        if not is_platform_admin(request.user):
            if obj.is_superuser or obj.groups.filter(name=PLATFORM_ADMIN_GROUP).exists():
                return
            ensure_role_groups()
            if obj.is_staff and not obj.groups.filter(name=CLUB_ADMIN_GROUP).exists():
                obj.groups.add(Group.objects.get(name=CLUB_ADMIN_GROUP))
            return

        if obj.is_staff and not obj.groups.exists():
            ensure_role_groups()
            obj.groups.add(Group.objects.get(name=CLUB_ADMIN_GROUP))
