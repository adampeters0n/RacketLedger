"""Úpravy Django auth admin."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User

admin.site.unregister(User)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_filter = ()
    change_list_template = "admin/auth/user/change_list.html"
