"""Úpravy Django auth admin – správa uživatelů jen pro platform admin."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User

from core.roles import can_manage_users

admin.site.unregister(User)


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
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
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
