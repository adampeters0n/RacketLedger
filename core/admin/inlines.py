"""Admin inlines."""
from decimal import Decimal

from django import forms
from django.contrib import admin
from django.utils import timezone as dj_tz

from ..forms import DochazkaFormSet, DochazkaInlineForm
from ..models import Dochazka


class DochazkaInline(admin.TabularInline):
    model = Dochazka
    form = DochazkaInlineForm
    formset = DochazkaFormSet
    extra = 1
    autocomplete_fields = ("hrac",)
    
    fields = ("hrac", "cena_preview", "castka_nauc_display", "nauceno_kdy_display")
    readonly_fields = ("cena_preview", "castka_nauc_display", "nauceno_kdy_display")
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
        """Při přidávání tréninku (add_form) jeden řádek – další přidá uživatel tlačítkem jako v add_day."""
        if obj is None:
            return 1
        return self.extra

    def get_formset(self, request, obj=None, **kwargs):
        self.parent_obj = obj
        formset = super().get_formset(request, obj, **kwargs)
        form = formset.form
        if "hrac" in form.base_fields:
            form.base_fields["hrac"].label = "Hráči"
        return formset

    def cena_preview(self, obj):
        tr = obj.trening if getattr(obj, "trening_id", None) else getattr(self, "parent_obj", None)
        return f"{tr.cena_na_hrace():.0f} Kč" if tr else "—"

    def castka_nauc_display(self, obj):
        val = getattr(obj, "castka_nauc", None)
        return f"{Decimal(val):.0f} Kč" if val is not None else "—"

    def nauceno_kdy_display(self, obj):
        dt = getattr(obj, "nauceno_kdy", None)
        if not dt: return "—"
        if dj_tz.is_aware(dt): dt = dj_tz.localtime(dt)
        return dt.strftime("%d.%m.%Y %H:%M")
