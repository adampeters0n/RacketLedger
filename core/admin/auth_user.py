"""Úpravy Django auth admin – správa uživatelů jen pro platform admin."""
from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group, User
from django.utils.translation import gettext_lazy as _

from core.roles import (
    CLUB_ADMIN_GROUP,
    CLUB_COACH_GROUP,
    ROLE_ADMIN,
    ROLE_CLUB,
    ROLE_COACH,
    ROLE_PLATFORM,
    SYSTEM_ADMIN_USERNAME,
    can_access_user_admin,
    can_manage_users,
    can_view_all_users,
    ensure_role_groups,
    is_platform_admin,
    is_system_admin,
)

admin.site.unregister(User)
try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass

ROLE_CHOICES_BASE = (
    (ROLE_COACH, _("Trenér klubu")),
    (ROLE_CLUB, _("Správce klubu")),
    (ROLE_PLATFORM, _("Provozovatel")),
)

ROLE_ADMIN_CHOICE = (ROLE_ADMIN, _("Admin"))

ROLE_LABELS = {
    ROLE_ADMIN: _("Admin"),
    ROLE_PLATFORM: _("Provozovatel"),
    ROLE_CLUB: _("Správce klubu"),
    ROLE_COACH: _("Trenér klubu"),
}

ROLE_DETAILS = {
    ROLE_ADMIN: _("Všechny části systému. Jen pro účet AdamPeterka."),
    ROLE_PLATFORM: _("Celý systém včetně plateb, vyúčtování, analytiky, uživatelů a exportu/importu."),
    ROLE_CLUB: _("Tréninky, hráči, trenéři, rozvrh, ceník a omezené nastavení (bez plateb, vyúčtování a analytiky)."),
    ROLE_COACH: _("Tréninky, hráči, trenéři, rozvrh a nastavení (Obecné, Vzhled, Uživatelé)."),
}


def _is_admin_account(user) -> bool:
    return bool(user and getattr(user, "username", None) == SYSTEM_ADMIN_USERNAME)


def role_choices_for(user=None, *, include_admin: bool | None = None):
    """Volby rolí ve formuláři. Admin jen u účtu AdamPeterka."""
    if include_admin is None:
        include_admin = _is_admin_account(user)
    if include_admin:
        return (ROLE_ADMIN_CHOICE,) + ROLE_CHOICES_BASE
    return ROLE_CHOICES_BASE


def _role_for_user(user) -> str:
    if not user or not user.pk:
        return ROLE_CLUB
    if is_system_admin(user) or _is_admin_account(user):
        return ROLE_ADMIN
    if user.is_superuser or is_platform_admin(user):
        return ROLE_PLATFORM
    if user.groups.filter(name=CLUB_COACH_GROUP).exists() and not user.groups.filter(
        name=CLUB_ADMIN_GROUP
    ).exists():
        return ROLE_COACH
    return ROLE_CLUB


def _apply_role(user: User, role: str) -> None:
    platform_g, club_g, coach_g = ensure_role_groups()
    if role == ROLE_ADMIN and not _is_admin_account(user):
        role = ROLE_PLATFORM

    user.is_staff = True
    user.is_superuser = role in (ROLE_ADMIN, ROLE_PLATFORM)
    user.save()
    user.groups.remove(platform_g, club_g, coach_g)
    if role == ROLE_ADMIN:
        user.groups.add(platform_g, club_g)
    elif role == ROLE_PLATFORM:
        user.groups.add(platform_g, club_g)
    elif role == ROLE_COACH:
        user.groups.add(coach_g)
    else:
        user.groups.add(club_g)


class SimpleUserChangeForm(UserChangeForm):
    role = forms.ChoiceField(
        label=_("Role"),
        choices=ROLE_CHOICES_BASE,
        widget=forms.RadioSelect(attrs={"class": "user-role-input"}),
        help_text=_("Stačí zvolit jednu roli — oprávnění se nastaví automaticky."),
    )

    class Meta:
        model = User
        fields = (
            "username",
            "password",
            "first_name",
            "last_name",
            "email",
            "is_active",
        )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        self.fields["username"].label = _("Přihlašovací jméno")
        self.fields["username"].widget.attrs["class"] = "vTextField nast-row-input"
        self.fields["first_name"].label = _("Jméno")
        self.fields["first_name"].widget.attrs["class"] = "vTextField nast-row-input"
        self.fields["last_name"].label = _("Příjmení")
        self.fields["last_name"].widget.attrs["class"] = "vTextField nast-row-input"
        self.fields["email"].label = _("E-mail")
        self.fields["email"].widget.attrs["class"] = "vTextField nast-row-input"
        self.fields["is_active"].label = _("Účet aktivní")
        self.fields["is_active"].help_text = _(
            "Vypnutý účet se nepřihlásí. Data a historie zůstanou."
        )
        self.fields["is_active"].widget = forms.CheckboxInput(
            attrs={"class": "nast-switch-input"}
        )
        choices = role_choices_for(self.instance)
        self.fields["role"].choices = choices
        self.fields["role"].initial = _role_for_user(self.instance)

    def clean_role(self):
        role = self.cleaned_data.get("role") or ROLE_CLUB
        request = self.request
        user = self.instance
        allowed = {value for value, _label in role_choices_for(user)}
        if role not in allowed:
            raise forms.ValidationError(_("Tuto roli nelze tomuto účtu přiřadit."))
        if role == ROLE_ADMIN and not _is_admin_account(user):
            raise forms.ValidationError(_("Roli Admin lze nastavit jen účtu AdamPeterka."))
        # Nesnížit sám sobě provozovatelskou / admin roli
        if request and user and user.pk and request.user.pk == user.pk:
            current = _role_for_user(user)
            if current in (ROLE_ADMIN, ROLE_PLATFORM) and role not in (
                ROLE_ADMIN,
                ROLE_PLATFORM,
            ):
                raise forms.ValidationError(
                    _("Nemůžete si sami odebrat roli provozovatele / admina.")
                )
        return role

    def save(self, commit=True):
        user = super().save(commit=commit)
        role = self.cleaned_data.get("role") or ROLE_CLUB
        if commit:
            _apply_role(user, role)
        else:
            # ModelForm.save(commit=False) přepíše save_m2m na _save_m2m —
            # musíme roli dořetězit, jinak se při admin uložení neaplikuje.
            old_save_m2m = self.save_m2m

            def save_m2m():
                old_save_m2m()
                _apply_role(self.instance, role)

            self.save_m2m = save_m2m
        return user


class SimpleUserCreationForm(UserCreationForm):
    role = forms.ChoiceField(
        label=_("Role"),
        choices=ROLE_CHOICES_BASE,
        initial=ROLE_CLUB,
        widget=forms.RadioSelect(attrs={"class": "user-role-input"}),
        help_text=_("Stačí zvolit jednu roli — oprávnění se nastaví automaticky."),
    )

    class Meta:
        model = User
        fields = ("username",)

    def __init__(self, *args, **kwargs):
        kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        self.fields["username"].label = _("Přihlašovací jméno")
        self.fields["username"].widget.attrs["class"] = "vTextField nast-row-input"
        self.fields["password1"].label = _("Heslo")
        self.fields["password1"].widget.attrs["class"] = "vTextField nast-row-input"
        self.fields["password2"].label = _("Heslo znovu")
        self.fields["password2"].widget.attrs["class"] = "vTextField nast-row-input"
        # Nový účet nikdy nedostane Admin (jen AdamPeterka)
        self.fields["role"].choices = role_choices_for(include_admin=False)

    def clean_role(self):
        role = self.cleaned_data.get("role") or ROLE_CLUB
        if role == ROLE_ADMIN:
            raise forms.ValidationError(_("Roli Admin nelze přiřadit novému účtu."))
        return role

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True
        role = self.cleaned_data.get("role") or ROLE_CLUB
        user.is_superuser = role in (ROLE_ADMIN, ROLE_PLATFORM)
        if commit:
            user.save()
            _apply_role(user, role)
        else:
            old_save_m2m = getattr(self, "save_m2m", None)

            def save_m2m():
                if callable(old_save_m2m):
                    old_save_m2m()
                if self.instance.pk:
                    _apply_role(self.instance, role)

            self.save_m2m = save_m2m
        return user


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_filter = ()
    filter_horizontal = ()
    change_list_template = "admin/auth/user/change_list.html"
    change_form_template = "admin/auth/user/change_form.html"
    add_form_template = "admin/auth/user/change_form.html"
    form = SimpleUserChangeForm
    add_form = SimpleUserCreationForm

    list_display = ("username", "email", "first_name", "last_name", "role_display")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("username",)

    fieldsets = (
        (
            _("Přihlášení"),
            {
                "fields": ("username", "password"),
                "description": _("Jak se uživatel přihlásí do administrace."),
            },
        ),
        (
            _("Osoba"),
            {"fields": ("first_name", "last_name", "email")},
        ),
        (
            _("Přístup"),
            {
                "fields": ("is_active", "role"),
                "description": _(
                    "Stačí zvolit roli. Jemné oprávnění po jednotlivých modulech nejsou potřeba."
                ),
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2", "role"),
                "description": _("Nový účet pro administraci tenisového systému."),
            },
        ),
    )
    readonly_fields = ()

    @admin.display(description=_("Role"))
    def role_display(self, obj):
        return ROLE_LABELS.get(_role_for_user(obj), "—")

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        choices = role_choices_for(obj, include_admin=False if add else None)
        context["role_details"] = ROLE_DETAILS
        context["role_choices"] = choices
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    def get_form(self, request, obj=None, **kwargs):
        Form = super().get_form(request, obj, **kwargs)

        class RequestForm(Form):
            def __init__(self, *args, **kw):
                kw["request"] = request
                super().__init__(*args, **kw)

        return RequestForm

    def get_fieldsets(self, request, obj=None):
        if not obj:
            return self.add_fieldsets
        # Trenér / správce u sebe: bez správy role a is_active
        if not can_view_all_users(request.user):
            return (
                (
                    _("Přihlášení"),
                    {
                        "fields": ("username", "password"),
                        "description": _("Jak se uživatel přihlásí do administrace."),
                    },
                ),
                (
                    _("Osoba"),
                    {"fields": ("first_name", "last_name", "email")},
                ),
            )
        return self.fieldsets

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if can_view_all_users(request.user):
            return qs
        return qs.filter(pk=request.user.pk)

    def has_module_permission(self, request):
        return can_access_user_admin(request.user)

    def has_view_permission(self, request, obj=None):
        if not can_access_user_admin(request.user):
            return False
        if obj is None or can_view_all_users(request.user):
            return True
        return obj.pk == request.user.pk

    def has_add_permission(self, request):
        return can_manage_users(request.user)

    def has_change_permission(self, request, obj=None):
        if not can_access_user_admin(request.user):
            return False
        if can_view_all_users(request.user):
            return True
        if obj is None:
            return True
        return obj.pk == request.user.pk

    def has_delete_permission(self, request, obj=None):
        return can_manage_users(request.user)
