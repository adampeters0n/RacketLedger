"""Cenik admin."""
from django.contrib import admin

from ..models import Cenik


@admin.register(Cenik)
class CenikAdmin(admin.ModelAdmin):
    list_display = ("format", "kurt", "cena_za_hodinu", "platnost_od", "platnost_do")
    search_fields = ("format", "kurt")
