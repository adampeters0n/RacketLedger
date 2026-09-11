"""Admin forms, widgets and formsets."""
from django import forms
from django.contrib.admin.widgets import AdminSplitDateTime
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms import formset_factory
from django.forms.models import BaseInlineFormSet
from django.utils.translation import gettext_lazy as _

from .admin_utils import trener_label
from .models import Cenik, Dochazka, Hrac, SystemNastaveni, TrenerPlatba, VyuctovaniNastaveni

User = get_user_model()


def cenik_select_choices(*extra_values, blank_label="------"):
    """Distinct hodnoty z Ceníku + případné extra (pro edit/copy)."""
    values = []
    seen = set()
    for v in extra_values:
        v = (v or "").strip()
        if v and v not in seen:
            seen.add(v)
            values.append(v)
    return [("", blank_label)] + [(v, v) for v in values]


def cenik_format_choices(*extra):
    qs = (
        Cenik.objects.exclude(format="")
        .order_by("format")
        .values_list("format", flat=True)
        .distinct()
    )
    return cenik_select_choices(*extra, *qs)


def cenik_sezona_choices(*extra):
    qs = (
        Cenik.objects.exclude(sezona="")
        .order_by("sezona")
        .values_list("sezona", flat=True)
        .distinct()
    )
    return cenik_select_choices(*extra, *qs, blank_label="---------")


def cenik_kurt_choices(*extra):
    qs = (
        Cenik.objects.exclude(kurt="")
        .order_by("kurt")
        .values_list("kurt", flat=True)
        .distinct()
    )
    return cenik_select_choices(*extra, *qs)


class NastaveniClearableFileInput(forms.ClearableFileInput):
    """File input bez Django „Currently / Clear“ – mazání řeší UI nastavení."""

    template_name = "admin/widgets/nastaveni_clearable_file.html"


class HracInfoForm(forms.ModelForm):
    class Meta:
        model = Hrac
        fields = ["jmeno", "prijmeni", "email", "rodina"]
        widgets = {
            "jmeno": forms.TextInput(attrs={"class": "vTextField"}),
            "prijmeni": forms.TextInput(attrs={"class": "vTextField"}),
            "email": forms.EmailInput(attrs={"class": "vTextField"}),
        }


class DochazkaInlineForm(forms.ModelForm):
    class Meta:
        model = Dochazka
        fields = ["hrac"]

    def validate_unique(self):
        pass

    def _post_clean(self):
        super()._post_clean()
        
        if 'id' in self._errors:
            del self._errors['id']
            
        if '__all__' in self._errors:
            new_errors = []
            for error in self._errors['__all__']:
                error_str = str(error)
                if "existuje" in error_str or "exists" in error_str:
                    continue
                new_errors.append(error)
            
            if not new_errors:
                del self._errors['__all__']
            else:
                self._errors['__all__'] = new_errors

class DochazkaFormSet(BaseInlineFormSet):
    def validate_unique(self):
        pass

    def clean(self):
        if hasattr(self, '_non_form_errors'):
            self._non_form_errors = self.error_class()
        
        hraci_v_tomto_okne = []
        for form in self.forms:
            if self._should_delete_form(form) or not form.cleaned_data:
                continue
            
            hrac = form.cleaned_data.get('hrac')
            if not hrac:
                continue

            if hrac in hraci_v_tomto_okne:
                raise ValidationError(f"Hráč {hrac.cele_jmeno} je v tomto seznamu vybrán dvakrát.")
            hraci_v_tomto_okne.append(hrac)
class TimeDatalistTextInput(forms.TextInput):
    input_type = "text"

    def __init__(self, *args, **kwargs):
        attrs = kwargs.setdefault("attrs", {})
        attrs.setdefault("placeholder", "např. 13:00")
        attrs.setdefault("autocomplete", "off")
        attrs.setdefault("inputmode", "text")
        attrs.setdefault("pattern", r"^([01]\d|2[0-3]):[0-5]\d$")
        attrs.setdefault("title", "Zadej čas ve tvaru HH:MM (např. 13:00)")
        super().__init__(*args, **kwargs)

    def render(self, name, value, attrs=None, renderer=None):
        attrs = {} if attrs is None else attrs.copy()
        base_id = attrs.get("id", name)
        list_id = f"{base_id}-time-suggest"
        attrs["list"] = list_id
        existing_class = (attrs.get("class") or "").strip()
        if "vTimeField" not in existing_class.split():
            attrs["class"] = f"{existing_class} vTimeField".strip()
        html = super().render(name, value, attrs, renderer)
        options = [f"<option value='{h:02d}:00'></option><option value='{h:02d}:30'></option>" for h in range(6, 24)]
        datalist = f"<datalist id='{list_id}'>" + "".join(options) + "</datalist>"
        return html + datalist

class AdminSplitDateTimeWithDatalist(AdminSplitDateTime):
    def __init__(self, attrs=None):
        super().__init__(attrs=attrs)
        self.widgets[1] = TimeDatalistTextInput()
class TrenerModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return trener_label(obj)


class AddDayForm(forms.Form):
    """Společný trenér + datum dne pro všechny tréninky."""

    trener = TrenerModelChoiceField(
        queryset=User.objects.order_by("username"),
        label=_("Trenér"),
        required=True,
        empty_label="------",
    )

    datum = forms.DateField(
        label=_("Datum dne"),
        widget=forms.DateInput(attrs={"type": "date", "class": "add-day-datum-input"}),
    )


class CopyTrainingsForm(forms.Form):
    """Výběr zdrojového a cílového dne/týdne pro kopírování tréninků."""

    SCOPE_DAY = "day"
    SCOPE_WEEK = "week"
    SCOPE_CHOICES = [
        (SCOPE_DAY, _("Jeden den")),
        (SCOPE_WEEK, _("Celý týden")),
    ]

    source_date = forms.DateField(
        label=_("Kopírovat z"),
        widget=forms.DateInput(attrs={"type": "date", "class": "add-day-datum-input"}),
    )
    target_date = forms.DateField(
        label=_("Přidat do"),
        widget=forms.DateInput(attrs={"type": "date", "class": "add-day-datum-input"}),
    )
    scope = forms.ChoiceField(
        label=_("Rozsah"),
        choices=SCOPE_CHOICES,
        initial=SCOPE_DAY,
        widget=forms.Select(attrs={"class": "add-day-copy-scope"}),
    )
    trener = TrenerModelChoiceField(
        queryset=User.objects.order_by("username"),
        label=_("Trenér"),
        required=False,
        empty_label=_("Všichni trenéři"),
    )


class TrainingSlotForm(forms.Form):
    """Jeden „slot“ tréninku: čas, délka, formát, kurt, hráči."""
    cas = forms.TimeField(
        label=_("Čas"),
        required=False,
        # Textové pole kvůli volnému zadávání (např. "13" → 13:00).
        # Normalizaci na HH:MM řeší JavaScript v add_form šabloně.
        widget=forms.TimeInput(
            attrs={
                "type": "text",
                "class": "vTimeField add-day-time-input",
                "placeholder": "např. 13 nebo 13:30",
                "autocomplete": "off",
            }
        ),
    )
    delka_minut = forms.TypedChoiceField(
        label=_("Délka (hodiny)"),
        coerce=int,
        choices=list(SystemNastaveni.DELKA_MINUT_CHOICES),
        initial=60,
    )
    format = forms.ChoiceField(
        label=_("Typ tréninku"),
        required=False,
        choices=[("", "------")],
        widget=forms.Select(attrs={"class": "vTextField"}),
    )
    sezona = forms.ChoiceField(
        label=_("Sezóna"),
        required=False,
        choices=[("", "---------")],
        widget=forms.Select(attrs={"class": "vTextField"}),
    )
    kurt = forms.ChoiceField(
        label=_("Kurt"),
        required=False,
        choices=[("", "------")],
        widget=forms.Select(attrs={"class": "vTextField"}),
    )
    poznamka = forms.CharField(
        label=_("Poznámka"),
        required=False,
        widget=forms.TextInput(attrs={"class": "vTextField", "placeholder": "", "maxlength": 240}),
    )
    slot_datum = forms.DateField(
        label=_("Datum"),
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(
            attrs={"type": "date", "class": "add-day-slot-datum-input"},
            format="%Y-%m-%d",
        ),
    )
    trener = TrenerModelChoiceField(
        queryset=User.objects.order_by("username"),
        label=_("Trenér"),
        required=False,
        empty_label=_("—— stejný jako nahoře ——"),
    )
    hraci = forms.ModelMultipleChoiceField(
        queryset=Hrac.objects.order_by("prijmeni", "jmeno"),
        label=_("Hráči"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "size": 6,
                "class": "vMultipleSelect add-day-hraci-hidden-select",
                # Inline skrytí, aby se select nikdy ani na okamžik neukázal
                "style": "position:absolute;left:-9999px;top:auto;width:1px;height:1px;overflow:hidden;opacity:0;",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        init = self.initial or {}
        data = self.data if self.is_bound else None
        fmt_extra = init.get("format") or (data.get(self.add_prefix("format")) if data else "")
        sez_extra = init.get("sezona") or (data.get(self.add_prefix("sezona")) if data else "")
        kurt_extra = init.get("kurt") or (data.get(self.add_prefix("kurt")) if data else "")
        self.fields["format"].choices = cenik_format_choices(fmt_extra)
        self.fields["sezona"].choices = cenik_sezona_choices(sez_extra)
        self.fields["kurt"].choices = cenik_kurt_choices(kurt_extra)
        if not self.is_bound:
            try:
                for_date = None
                if self.initial.get("slot_datum"):
                    for_date = self.initial["slot_datum"]
                elif self.data.get(self.add_prefix("slot_datum")):
                    from datetime import datetime
                    raw = self.data.get(self.add_prefix("slot_datum"))
                    try:
                        for_date = datetime.strptime(raw, "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        pass
                defaults = SystemNastaveni.training_defaults(for_date=for_date)
                self.fields["delka_minut"].initial = defaults["delka_minut"]
                sezona_values = {c[0] for c in self.fields["sezona"].choices if c[0]}
                default_sezona = (defaults.get("sezona") or "").strip()
                if default_sezona in sezona_values:
                    self.fields["sezona"].initial = default_sezona
                kurt_values = {c[0] for c in self.fields["kurt"].choices if c[0]}
                default_kurt = (defaults.get("kurt") or "").strip()
                if default_kurt in kurt_values:
                    self.fields["kurt"].initial = default_kurt
            except Exception:
                pass

    def clean_format(self):
        return (self.cleaned_data.get("format") or "").strip()

    def clean_sezona(self):
        return (self.cleaned_data.get("sezona") or "").strip()

    def clean_kurt(self):
        return (self.cleaned_data.get("kurt") or "").strip()


class TrainingSlotFormSetBase(forms.BaseFormSet):
    """Kontrola: v každém slotu (tréninku) nesmí být stejný hráč vybrán dvakrát."""

    def clean(self):
        super().clean()
        for i, form in enumerate(self.forms):
            if self._should_delete_form(form) or not form.cleaned_data:
                continue
            hraci = form.cleaned_data.get("hraci") or []
            seen = set()
            for hrac in hraci:
                if hrac in seen:
                    raise ValidationError(
                        f"V tréninku {i + 1} je hráč {getattr(hrac, 'cele_jmeno', '')} vybrán více než jednou. "
                        "Každého hráče vyberte pouze jednou."
                    )
                seen.add(hrac)


TrainingSlotFormSet = formset_factory(
    TrainingSlotForm,
    formset=TrainingSlotFormSetBase,
    extra=10,
    max_num=20,
    min_num=1,
    validate_min=True,
)


class TrenerPlatbaForm(forms.ModelForm):
    user = TrenerModelChoiceField(
        queryset=User.objects.order_by("username"),
        label=_("Trenér"),
        empty_label="------",
    )

    class Meta:
        model = TrenerPlatba
        fields = ("user", "castka", "poznamka", "vytvoreno")
        labels = {
            "castka": _("Částka"),
            "poznamka": _("Poznámka"),
            "vytvoreno": _("Datum"),
        }
        widgets = {
            "castka": forms.NumberInput(attrs={"class": "vTextField", "step": "0.01"}),
            "poznamka": forms.TextInput(attrs={"class": "vTextField"}),
        }


class VyuctovaniNastaveniForm(forms.ModelForm):
    aplikovat_na_vsechny = forms.BooleanField(
        required=False,
        label=_("Synchronizovat režim u všech stávajících hráčů"),
        help_text=_("Přepíše u všech hráčů režim, počet tréninků a limit kreditu podle nastavení výše."),
    )

    class Meta:
        model = VyuctovaniNastaveni
        fields = [
            "auto_rezim",
            "auto_limit",
            "auto_castka_k_uhrade",
            "auto_pocet_treninku",
            "mesicni_den",
            "auto_posilat_email",
            "email_variant",
            "ucet_nazev_1",
            "ucet_nazev_2",
            "ucet_varianta_1",
            "ucet_varianta_2",
            "variabilni_symbol_popis",
        ]
        widgets = {
            "auto_rezim": forms.RadioSelect,
            "auto_limit": forms.NumberInput(attrs={"class": "vTextField", "step": "1", "min": "0"}),
            "auto_castka_k_uhrade": forms.NumberInput(attrs={"class": "vTextField", "step": "1", "min": "0"}),
            "auto_pocet_treninku": forms.NumberInput(attrs={"class": "vTextField", "min": "1"}),
            "mesicni_den": forms.NumberInput(attrs={"class": "vTextField", "min": "1", "max": "28"}),
            "email_variant": forms.Select(attrs={"class": "vTextField"}),
            "ucet_nazev_1": forms.TextInput(attrs={"class": "vTextField"}),
            "ucet_nazev_2": forms.TextInput(attrs={"class": "vTextField"}),
            "ucet_varianta_1": forms.TextInput(attrs={"class": "vTextField"}),
            "ucet_varianta_2": forms.TextInput(attrs={"class": "vTextField"}),
            "variabilni_symbol_popis": forms.TextInput(attrs={"class": "vTextField"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["auto_rezim"].label = _("Způsob vyúčtování")
        for name in ("auto_limit", "auto_castka_k_uhrade", "auto_pocet_treninku", "mesicni_den"):
            self.fields[name].required = False
        if self.instance and self.instance.pk:
            self.fields["email_variant"].choices = self.instance.email_variant_choices()

    def _preserve_hidden_fields(self, cleaned):
        """Skrytá pole nejsou v POST – ponechat stávající hodnoty z DB."""
        if not self.instance.pk:
            return cleaned
        for name in ("auto_limit", "auto_castka_k_uhrade", "auto_pocet_treninku", "mesicni_den"):
            if name not in self.data:
                cleaned[name] = getattr(self.instance, name)
        return cleaned

    def clean_mesicni_den(self):
        den = self.cleaned_data.get("mesicni_den")
        if den is not None and not (1 <= den <= 28):
            raise ValidationError("Zadejte den v rozmezí 1–28.")
        return den

    def clean(self):
        cleaned = super().clean()
        cleaned = self._preserve_hidden_fields(cleaned)
        rezim = cleaned.get("auto_rezim")
        if rezim == VyuctovaniNastaveni.AutoRezim.MANUAL:
            return cleaned
        if rezim == VyuctovaniNastaveni.AutoRezim.CASTKA:
            limit = cleaned.get("auto_limit")
            if limit is None or limit <= 0:
                self.add_error("auto_limit", "Zadejte kladný limit kreditu (částka bez mínusu, např. 5000).")
        if rezim == VyuctovaniNastaveni.AutoRezim.N_TRENINGU:
            pocet = cleaned.get("auto_pocet_treninku")
            if not pocet or pocet < 1:
                self.add_error("auto_pocet_treninku", "Zadejte počet tréninků alespoň 1.")
        return cleaned


class SystemNastaveniForm(forms.ModelForm):
    email_jmeno = forms.CharField(
        label=_("Jméno odesílatele"),
        required=False,
        widget=forms.TextInput(
            attrs={"class": "vTextField nast-row-input", "placeholder": "TenisSystém"}
        ),
    )
    email_adresa = forms.EmailField(
        label=_("E-mail odesílatele"),
        required=False,
        widget=forms.EmailInput(
            attrs={"class": "vTextField nast-row-input", "placeholder": "info@tenissystem.cz"}
        ),
    )
    email_oznaceni = forms.CharField(
        label=_("Označení klubu v předmětu"),
        required=False,
        widget=forms.TextInput(
            attrs={"class": "vTextField nast-row-input", "placeholder": "TenisSystém"}
        ),
    )
    vyuctovani_rezim = forms.ChoiceField(
        label=_("Režim vyúčtování"),
        choices=VyuctovaniNastaveni.AutoRezim.choices,
        required=False,
        widget=forms.Select(attrs={"class": "vTextField nast-row-input"}),
    )

    class Meta:
        model = SystemNastaveni
        fields = [
            "nazev_klubu",
            "slogan",
            "logo",
            "favicon",
            "kontakt_email",
            "kontakt_telefon",
            "kontakt_adresa",
            "vychozi_jazyk",
            "mena",
            "email_podpis",
            "tmavy_rezim",
            "barevna_varianta",
            "vychozi_delka_minut",
            "vychozi_sezona",
            "rozvrh_od_hodina",
            "rozvrh_do_hodina",
            "vychozi_zobrazeni_rozvrhu",
            "prah_dluhu_dashboard",
            "zvyraznit_zaporny_kredit",
            "radku_na_stranku",
        ]
        widgets = {
            "nazev_klubu": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
            "slogan": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
            "logo": NastaveniClearableFileInput(attrs={"class": "nast-file-native", "accept": "image/png,image/jpeg,.png,.jpg,.jpeg"}),
            "favicon": NastaveniClearableFileInput(attrs={"class": "nast-file-native", "accept": "image/png,image/jpeg,image/webp,.ico"}),
            "kontakt_email": forms.EmailInput(attrs={"class": "vTextField nast-row-input"}),
            "kontakt_telefon": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
            "kontakt_adresa": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
            "vychozi_jazyk": forms.Select(attrs={"class": "vTextField nast-row-input"}),
            "mena": forms.Select(attrs={"class": "vTextField nast-row-input"}),
            "email_podpis": forms.Textarea(attrs={"class": "vTextField nast-row-input", "rows": 4}),
            "tmavy_rezim": forms.CheckboxInput(attrs={"class": "nast-switch-input"}),
            "barevna_varianta": forms.RadioSelect,
            "vychozi_delka_minut": forms.Select(attrs={"class": "vTextField nast-row-input"}),
            "vychozi_sezona": forms.Select(attrs={"class": "vTextField nast-row-input"}),
            "rozvrh_od_hodina": forms.NumberInput(attrs={"class": "vTextField nast-row-input", "min": 0, "max": 23}),
            "rozvrh_do_hodina": forms.NumberInput(attrs={"class": "vTextField nast-row-input", "min": 1, "max": 23}),
            "vychozi_zobrazeni_rozvrhu": forms.Select(attrs={"class": "vTextField nast-row-input"}),
            "prah_dluhu_dashboard": forms.NumberInput(attrs={"class": "vTextField nast-row-input", "step": "1"}),
            "zvyraznit_zaporny_kredit": forms.CheckboxInput(attrs={"class": "nast-switch-input"}),
            "radku_na_stranku": forms.Select(attrs={"class": "vTextField nast-row-input"}),
        }

    def __init__(self, *args, **kwargs):
        vyuct_rezim = kwargs.pop("vyuct_rezim_initial", None)
        super().__init__(*args, **kwargs)
        current_sezona = ""
        if self.instance and getattr(self.instance, "vychozi_sezona", None):
            current_sezona = self.instance.vychozi_sezona
        self.fields["vychozi_sezona"] = forms.ChoiceField(
            label=_("Výchozí sezóna"),
            required=False,
            choices=cenik_sezona_choices(current_sezona),
            widget=forms.Select(attrs={"class": "vTextField nast-row-input"}),
        )
        if current_sezona:
            self.fields["vychozi_sezona"].initial = current_sezona
        if vyuct_rezim is not None:
            self.fields["vyuctovani_rezim"].initial = vyuct_rezim
        if self.instance and self.instance.pk and not self.is_bound:
            jmeno, adresa = self.instance.from_email_parts()
            self.fields["email_jmeno"].initial = jmeno
            self.fields["email_adresa"].initial = adresa
            self.fields["email_oznaceni"].initial = self.instance.subject_tag_display()

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("rozvrh_od_hodina")
        end = cleaned.get("rozvrh_do_hodina")
        if start is not None and end is not None and end <= start:
            self.add_error("rozvrh_do_hodina", "Konec rozvrhu musí být po začátku.")
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.email_odesilatel = SystemNastaveni.compose_from_email(
            self.cleaned_data.get("email_jmeno", ""),
            self.cleaned_data.get("email_adresa", ""),
        )
        obj.email_predmet_prefix = SystemNastaveni.compose_subject_prefix(
            self.cleaned_data.get("email_oznaceni", ""),
        )
        if commit:
            obj.save(sync_colors=True)
        return obj
