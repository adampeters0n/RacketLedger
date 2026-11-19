"""Admin inlines."""
from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from ..forms import DochazkaFormSet, DochazkaInlineForm
from ..models import Dochazka


class DochazkaInline(admin.TabularInline):
    model = Dochazka
    form = DochazkaInlineForm
    formset = DochazkaFormSet
    extra = 0
    verbose_name = "Docházka"
    verbose_name_plural = "Hráči"
    autocomplete_fields = ("hrac",)
    
    # Jen hráči (bez ceny / naúčtováno) – stejně jako Přidat trénink
    fields = ("hrac",)
    readonly_fields = ()
    exclude = ("prisel",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "hrac":
            # Na stránce Přidat trénink (add_form) obyčejný Select, aby JS mohl nastavit hodnotu a odeslat ji
            if request.path.rstrip("/").endswith("/add"):
                field.widget = forms.Select(attrs={"class": "add-day-hrac-select"})
            else:
                w = field.widget
                for attr in ("can_add_related", "can_change_related", "can_view_related", "can_delete_related"):
                    if hasattr(w, attr): setattr(w, attr, False)
        return field

    def get_extra(self, request, obj=None, **kwargs):
        """Při přidávání tréninku jeden řádek; při úpravě žádný – nový až po kliknutí na Přidat."""
        if obj is None:
            return 1
        return 0

    def get_formset(self, request, obj=None, **kwargs):
        self.parent_obj = obj
        formset = super().get_formset(request, obj, **kwargs)
        form = formset.form
        if "hrac" in form.base_fields:
            form.base_fields["hrac"].label = _("Hráč")
        return formset
