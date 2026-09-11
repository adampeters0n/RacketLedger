"""Cenik admin – volný text pro typ, sezónu i kurt."""
from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from core.money import format_castka, get_mena_symbol

from ..models import Cenik


class CenikAdminForm(forms.ModelForm):
    class Meta:
        model = Cenik
        fields = (
            "format",
            "sezona",
            "kurt",
            "cena_za_hodinu",
            "platnost_od",
            "platnost_do",
            "v_kalendari",
        )
        labels = {
            "format": _("Typ tréninku"),
            "sezona": _("Sezóna"),
            "kurt": _("Kurt"),
            "v_kalendari": _("Přidat do kalendáře"),
        }
        widgets = {
            "format": forms.TextInput(
                attrs={
                    "class": "vTextField",
                    "placeholder": _("např. Solo, Dvojice, Výplet…"),
                    "autocomplete": "off",
                }
            ),
            "sezona": forms.TextInput(
                attrs={
                    "class": "vTextField",
                    "placeholder": _("např. Léto, Zima…"),
                    "autocomplete": "off",
                }
            ),
            "kurt": forms.TextInput(
                attrs={
                    "class": "vTextField",
                    "placeholder": _("např. Venku, Hala, Kurt 1…"),
                    "autocomplete": "off",
                }
            ),
            "cena_za_hodinu": forms.NumberInput(
                attrs={
                    "class": "vTextField",
                    "step": "0.01",
                    "inputmode": "decimal",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        symbol = get_mena_symbol()
        self.fields["cena_za_hodinu"].label = _("Cena za hodinu (%(mena)s/h)") % {"mena": symbol}
        self.fields["cena_za_hodinu"].widget.attrs["data-mena-suffix"] = f"{symbol}/h"

    def clean_format(self):
        return (self.cleaned_data.get("format") or "").strip()

    def clean_sezona(self):
        return (self.cleaned_data.get("sezona") or "").strip()

    def clean_kurt(self):
        return (self.cleaned_data.get("kurt") or "").strip()


@admin.register(Cenik)
class CenikAdmin(admin.ModelAdmin):
    form = CenikAdminForm
    change_form_template = "admin/core/cenik/change_form.html"
    list_display = (
        "format",
        "sezona",
        "kurt",
        "cena_za_hodinu_display",
        "platnost_od",
        "platnost_do",
    )
    search_fields = ("format", "sezona", "kurt")
    ordering = ("format", "sezona", "kurt", "-platnost_od")

    @admin.display(description=_("Cena za hodinu"), ordering="cena_za_hodinu")
    def cena_za_hodinu_display(self, obj):
        return format_castka(obj.cena_za_hodinu, per_hour=True)
