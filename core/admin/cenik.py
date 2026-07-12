"""Cenik admin."""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from ..models import Cenik, CenikFormat

NEW_TYP_VALUE = "__new_typ__"


class CenikAdminForm(forms.ModelForm):
    class Meta:
        model = Cenik
        fields = ("format", "kurt", "cena_za_hodinu", "platnost_od", "platnost_do")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["format"] = forms.ChoiceField(
            label="Typ tréninku",
            choices=[("", "---------")] + CenikFormat.choices() + [
                (NEW_TYP_VALUE, "— Nový typ tréninku —"),
            ],
            widget=forms.Select(attrs={"class": "vTextField cenik-typ-select"}),
        )
        self.fields["format"].help_text = ""

    def clean_format(self):
        value = self.cleaned_data.get("format")
        if value == NEW_TYP_VALUE:
            raise ValidationError("Nejdříve zadejte název nového typu tréninku, nebo vyberte existující.")
        return value


@admin.register(Cenik)
class CenikAdmin(admin.ModelAdmin):
    form = CenikAdminForm
    change_form_template = "admin/core/cenik/change_form.html"
    list_display = ("format_nazev", "kurt", "cena_za_hodinu", "platnost_od", "platnost_do")
    search_fields = ("format",)

    @admin.display(description="Typ tréninku", ordering="format")
    def format_nazev(self, obj):
        return obj.get_format_display()

    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path(
                "formaty/",
                self.admin_site.admin_view(self.formaty_view),
                name="core_cenik_formaty",
            ),
            path(
                "formaty/pridat/",
                self.admin_site.admin_view(self.formaty_pridat_view),
                name="core_cenik_formaty_pridat",
            ),
        ]
        return extra + urls

    def _formaty_redirect(self, request, edit_id=None):
        url = reverse("admin:core_cenik_formaty")
        next_url = request.GET.get("next") or request.POST.get("next")
        params = []
        if next_url:
            params.append(f"next={next_url}")
        if edit_id:
            params.append(f"edit_format={edit_id}")
        if params:
            url = f"{url}?{'&'.join(params)}"
        return url

    def _apply_format_action(self, request):
        action = request.POST.get("fmt_action")
        if action == "add":
            nazev = (request.POST.get("fmt_new_nazev") or "").strip()
            if not nazev:
                messages.error(request, "Zadejte název nového typu tréninku.")
            elif CenikFormat.objects.filter(nazev=nazev).exists():
                messages.warning(request, f"Typ „{nazev}“ už existuje.")
            else:
                fmt = CenikFormat.pridej(nazev)
                messages.success(request, f"Typ „{fmt.nazev}“ byl přidán.")
        elif action == "edit":
            fmt = CenikFormat.objects.filter(pk=request.POST.get("fmt_id")).first()
            nazev = (request.POST.get("fmt_nazev") or "").strip()
            if not fmt:
                messages.error(request, "Typ tréninku nebyl nalezen.")
            elif not nazev:
                messages.error(request, "Zadejte název typu tréninku.")
            elif CenikFormat.objects.exclude(pk=fmt.pk).filter(nazev=nazev).exists():
                messages.error(request, f"Typ „{nazev}“ už existuje.")
            else:
                fmt.nazev = nazev
                fmt.save(update_fields=["nazev"])
                messages.success(request, "Název typu tréninku byl upraven.")
        elif action == "delete":
            fmt = CenikFormat.objects.filter(pk=request.POST.get("fmt_id")).first()
            if not fmt:
                messages.error(request, "Typ tréninku nebyl nalezen.")
            elif fmt.je_pouzity():
                messages.error(
                    request,
                    f"Typ „{fmt.nazev}“ nelze smazat – je použit v ceníku nebo trénincích.",
                )
            else:
                nazev = fmt.nazev
                fmt.delete()
                messages.success(request, f"Typ „{nazev}“ byl odstraněn.")

    def formaty_view(self, request):
        if request.method == "POST" and request.POST.get("fmt_manage"):
            self._apply_format_action(request)
            return redirect(self._formaty_redirect(request))

        edit_id = request.GET.get("edit_format")
        try:
            edit_id = int(edit_id) if edit_id else None
        except (TypeError, ValueError):
            edit_id = None

        next_url = request.GET.get("next") or reverse("admin:core_cenik_changelist")
        context = {
            **self.admin_site.each_context(request),
            "title": "Ceník Menu",
            "format_registry": CenikFormat.objects.all(),
            "edit_format_id": edit_id,
            "next_url": next_url,
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/core/cenik/formaty.html", context)

    def formaty_pridat_view(self, request):
        if request.method != "POST":
            return JsonResponse({"error": "Metoda není povolena."}, status=405)
        nazev = (request.POST.get("nazev") or "").strip()
        if not nazev:
            return JsonResponse({"error": "Zadejte název typu tréninku."}, status=400)
        if CenikFormat.objects.filter(nazev=nazev).exists():
            return JsonResponse({"error": f"Typ „{nazev}“ už existuje."}, status=400)
        fmt = CenikFormat.pridej(nazev)
        return JsonResponse({"kod": fmt.kod, "nazev": fmt.nazev})

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = {
            **(extra_context or {}),
            "formaty_url": reverse("admin:core_cenik_formaty"),
            "formaty_pridat_url": reverse("admin:core_cenik_formaty_pridat"),
        }
        return super().changeform_view(request, object_id, form_url, extra_context)
