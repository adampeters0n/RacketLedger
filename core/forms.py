"""Admin forms, widgets and formsets."""
from decimal import Decimal

from django import forms
from django.contrib.admin.widgets import AdminSplitDateTime
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms import formset_factory
from django.forms.models import BaseInlineFormSet
from django.utils import timezone as dj_tz
from django.utils.translation import gettext_lazy as _

from .admin_utils import get_month_choices, trener_label
from .models import Cenik, CenikFormat, Dochazka, Hrac, SystemNastaveni, TrenerPlatba, VyuctovaniNastaveni


def hrac_rok_narozeni_choices():
    year = dj_tz.localdate().year
    return [("", "---------")] + [(y, str(y)) for y in range(year, year - 101, -1)]

HROMADNE_SURPLUS_CHOICES = [
    (Decimal("3000.00"), "3 000 Kč"),
    (Decimal("5000.00"), "5 000 Kč"),
]

User = get_user_model()


class HracInfoForm(forms.ModelForm):
    rok_narozeni = forms.TypedChoiceField(
        label=_("Rok narození"),
        choices=hrac_rok_narozeni_choices,
        coerce=lambda v: int(v) if v not in (None, "") else None,
        empty_value=None,
        required=False,
        widget=forms.Select(attrs={"class": "vSelectField"}),
    )
    pohlavi = forms.ChoiceField(
        label=_("Pohlaví"),
        choices=[("", "---------")] + list(Hrac.Pohlavi.choices),
        required=False,
        widget=forms.Select(attrs={"class": "vSelectField"}),
    )

    class Meta:
        model = Hrac
        fields = [
            "jmeno",
            "prijmeni",
            "email",
            "telefon",
            "rok_narozeni",
            "uroven",
            "pohlavi",
            "aktivni",
            "rodina",
        ]
        widgets = {
            "jmeno": forms.TextInput(attrs={"class": "vTextField"}),
            "prijmeni": forms.TextInput(attrs={"class": "vTextField"}),
            "email": forms.EmailInput(attrs={"class": "vTextField"}),
            "telefon": forms.TextInput(attrs={"class": "vTextField", "inputmode": "tel"}),
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
                # Na /admin/core/trening/add/ ponechat textové pole (volné zadání),
                # globální TsTimePicker se tu neaplikuje.
                "data-ts-time-skip": "1",
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
        choices=[("", "------")],
        required=False,
        widget=forms.Select(attrs={"class": "vTextField"}),
    )
    kurt = forms.ChoiceField(
        label=_("Kurt"),
        choices=[("", "------")] + list(Cenik.Kurt.choices),
        required=False,
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
        queryset=Hrac.objects.filter(aktivni=True).order_by("prijmeni", "jmeno"),
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
        self.fields["format"].choices = [("", "------")] + CenikFormat.choices()
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
                self.fields["kurt"].initial = defaults["kurt"]
            except Exception:
                pass


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
    class Meta:
        model = VyuctovaniNastaveni
        fields = [
            "auto_rezim",
            "auto_limit",
            "auto_castka_k_uhrade",
            "hromadne_surplus",
            "auto_pocet_treninku",
            "mesicni_den",
            "auto_posilat_email",
            "email_variant",
            "ucet_nazev_1",
            "ucet_nazev_2",
            "ucet_nazev_3",
            "ucet_varianta_1",
            "ucet_varianta_2",
            "ucet_varianta_3",
            "variabilni_symbol_popis",
        ]
        widgets = {
            "auto_rezim": forms.RadioSelect(attrs={"class": "nast-excel-input"}),
            "auto_limit": forms.NumberInput(attrs={"class": "vTextField nast-row-input", "step": "1", "min": "0"}),
            "auto_castka_k_uhrade": forms.NumberInput(attrs={"class": "vTextField nast-row-input", "step": "1", "min": "0"}),
            "hromadne_surplus": forms.Select(
                choices=HROMADNE_SURPLUS_CHOICES,
                attrs={"class": "vTextField nast-row-input"},
            ),
            "auto_pocet_treninku": forms.NumberInput(attrs={"class": "vTextField nast-row-input", "min": "1"}),
            "mesicni_den": forms.NumberInput(attrs={"class": "vTextField nast-row-input", "min": "1", "max": "28"}),
            "auto_posilat_email": forms.CheckboxInput(attrs={"class": "nast-switch-input"}),
            "email_variant": forms.Select(attrs={"class": "vTextField nast-row-input"}),
            "ucet_nazev_1": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
            "ucet_nazev_2": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
            "ucet_nazev_3": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
            "ucet_varianta_1": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
            "ucet_varianta_2": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
            "ucet_varianta_3": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
            "variabilni_symbol_popis": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["auto_rezim"].label = _("Způsob vyúčtování")
        for name in ("auto_limit", "auto_castka_k_uhrade", "auto_pocet_treninku", "mesicni_den", "hromadne_surplus"):
            self.fields[name].required = False
        self.fields["hromadne_surplus"].choices = HROMADNE_SURPLUS_CHOICES
        if self.instance and self.instance.pk:
            self.fields["email_variant"].choices = self.instance.email_variant_choices()

    def _preserve_hidden_fields(self, cleaned):
        """Skrytá pole nejsou v POST – ponechat stávající hodnoty z DB."""
        if not self.instance.pk:
            return cleaned
        for name in ("auto_limit", "auto_castka_k_uhrade", "hromadne_surplus", "auto_pocet_treninku", "mesicni_den"):
            if name not in self.data:
                cleaned[name] = getattr(self.instance, name)
        return cleaned

    def clean_hromadne_surplus(self):
        val = self.cleaned_data.get("hromadne_surplus")
        if val is None:
            return Decimal("5000.00")
        allowed = {Decimal("3000.00"), Decimal("5000.00")}
        if val not in allowed:
            raise ValidationError(_("Zvolte surplus 3 000 Kč nebo 5 000 Kč."))
        return val

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
    sezona_venek_od_den = forms.TypedChoiceField(
        label=_("Den od"),
        coerce=int,
        choices=[(d, str(d)) for d in range(1, 32)],
        widget=forms.Select(attrs={"class": "vTextField nast-sezona-den"}),
    )
    sezona_venek_od = forms.TypedChoiceField(
        label=_("Měsíc od"),
        coerce=int,
        choices=[],
        widget=forms.Select(attrs={"class": "vTextField nast-sezona-mesic"}),
    )
    sezona_venek_do_den = forms.TypedChoiceField(
        label=_("Den do"),
        coerce=int,
        choices=[(d, str(d)) for d in range(1, 32)],
        widget=forms.Select(attrs={"class": "vTextField nast-sezona-den"}),
    )
    sezona_venek_do = forms.TypedChoiceField(
        label=_("Měsíc do"),
        coerce=int,
        choices=[],
        widget=forms.Select(attrs={"class": "vTextField nast-sezona-mesic"}),
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
            "email_podpis",
            "tmavy_rezim",
            "barevna_varianta",
            "vychozi_delka_minut",
            "vychozi_kurt",
            "pronajem_ceny",
            "pronajem_ceny_venek",
            "staly_pronajem_od",
            "staly_pronajem_do",
            "sezona_automaticky_kurt",
            "sezona_venek_od_den",
            "sezona_venek_od",
            "sezona_venek_do_den",
            "sezona_venek_do",
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
            "logo": forms.ClearableFileInput(attrs={"class": "nast-file-native", "accept": "image/png,image/jpeg,image/webp"}),
            "favicon": forms.ClearableFileInput(attrs={"class": "nast-file-native", "accept": "image/png,image/jpeg,image/webp,.ico"}),
            "kontakt_email": forms.EmailInput(attrs={"class": "vTextField nast-row-input"}),
            "kontakt_telefon": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
            "kontakt_adresa": forms.TextInput(attrs={"class": "vTextField nast-row-input"}),
            "vychozi_jazyk": forms.Select(attrs={"class": "vTextField nast-row-input"}),
            "email_podpis": forms.Textarea(attrs={"class": "vTextField nast-row-input", "rows": 4}),
            "tmavy_rezim": forms.CheckboxInput(attrs={"class": "nast-switch-input"}),
            "barevna_varianta": forms.RadioSelect,
            "vychozi_delka_minut": forms.Select(attrs={"class": "vTextField nast-row-input"}),
            "vychozi_kurt": forms.Select(attrs={"class": "vTextField nast-row-input"}),
            "pronajem_ceny": forms.TextInput(
                attrs={
                    "class": "vTextField nast-row-input",
                    "placeholder": "420,440,530,580",
                }
            ),
            "pronajem_ceny_venek": forms.TextInput(
                attrs={
                    "class": "vTextField nast-row-input",
                    "placeholder": "220,250",
                }
            ),
            "staly_pronajem_od": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": "vTextField nast-row-input", "type": "date"},
            ),
            "staly_pronajem_do": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": "vTextField nast-row-input", "type": "date"},
            ),
            "sezona_automaticky_kurt": forms.CheckboxInput(attrs={"class": "nast-switch-input"}),
            "rozvrh_od_hodina": forms.NumberInput(attrs={"class": "vTextField nast-row-input", "min": 0, "max": 23}),
            "rozvrh_do_hodina": forms.NumberInput(attrs={"class": "vTextField nast-row-input", "min": 1, "max": 23}),
            "vychozi_zobrazeni_rozvrhu": forms.Select(attrs={"class": "vTextField nast-row-input"}),
            "prah_dluhu_dashboard": forms.NumberInput(attrs={"class": "vTextField nast-row-input", "step": "1"}),
            "zvyraznit_zaporny_kredit": forms.CheckboxInput(attrs={"class": "nast-switch-input"}),
            "radku_na_stranku": forms.Select(attrs={"class": "vTextField nast-row-input"}),
        }

    def __init__(self, *args, **kwargs):
        kwargs.pop("vyuct_rezim_initial", None)
        appearance = kwargs.pop("appearance_initial", None)
        super().__init__(*args, **kwargs)
        month_choices = get_month_choices()
        self.fields["sezona_venek_od"].choices = month_choices
        self.fields["sezona_venek_do"].choices = month_choices
        self.fields["vychozi_kurt"].choices = [
            (Cenik.Kurt.VENEK, _("Venku")),
            (Cenik.Kurt.HALA, _("Hala")),
        ]
        for date_key in ("staly_pronajem_od", "staly_pronajem_do"):
            self.fields[date_key].input_formats = ["%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"]
        if self.instance and self.instance.pk and not self.is_bound:
            self.fields["sezona_venek_od"].initial = self.instance.sezona_venek_od or 4
            self.fields["sezona_venek_do"].initial = self.instance.sezona_venek_do or 10
            self.fields["sezona_venek_od_den"].initial = self.instance.sezona_venek_od_den or 1
            self.fields["sezona_venek_do_den"].initial = self.instance.sezona_venek_do_den or 31
        if appearance and not self.is_bound:
            if "barevna_varianta" in appearance:
                self.initial["barevna_varianta"] = appearance["barevna_varianta"]
                self.fields["barevna_varianta"].initial = appearance["barevna_varianta"]
            if "tmavy_rezim" in appearance:
                self.initial["tmavy_rezim"] = appearance["tmavy_rezim"]
                self.fields["tmavy_rezim"].initial = appearance["tmavy_rezim"]
        if self.instance and self.instance.pk and not self.is_bound:
            jmeno, adresa = self.instance.from_email_parts()
            self.fields["email_jmeno"].initial = jmeno
            self.fields["email_adresa"].initial = adresa
            self.fields["email_oznaceni"].initial = self.instance.subject_tag_display()

    def _clamp_sezona_den(self, cleaned, mesic_key, den_key):
        import calendar

        mesic = cleaned.get(mesic_key)
        den = cleaned.get(den_key)
        if mesic is None or den is None:
            return
        max_day = calendar.monthrange(2001, int(mesic))[1]  # non-leap for Feb=28
        if int(den) > max_day:
            cleaned[den_key] = max_day

    def clean_pronajem_ceny(self):
        from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

        raw = (self.cleaned_data.get("pronajem_ceny") or "").strip()
        if not raw:
            return "420,440,530,580"
        parsed = []
        for part in raw.replace(";", ",").split(","):
            part = part.strip().replace(" ", "").replace("Kč", "").replace("kc", "")
            if not part:
                continue
            try:
                val = Decimal(part.replace(",", ".")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            except (InvalidOperation, ValueError):
                raise forms.ValidationError(
                    _("Neplatná cena „%(val)s“. Zadejte čísla oddělená čárkou.")
                    % {"val": part}
                )
            if val <= 0:
                raise forms.ValidationError(_("Ceny musí být kladné."))
            # Celá čísla bez desetinné části
            if val == val.to_integral_value():
                parsed.append(str(int(val)))
            else:
                parsed.append(str(val))
        if not parsed:
            raise forms.ValidationError(_("Zadejte alespoň jednu cenu."))
        return ",".join(parsed)

    def clean_pronajem_ceny_venek(self):
        from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

        raw = (self.cleaned_data.get("pronajem_ceny_venek") or "").strip()
        if not raw:
            return "220,250"
        parsed = []
        for part in raw.replace(";", ",").split(","):
            part = part.strip().replace(" ", "").replace("Kč", "").replace("kc", "")
            if not part:
                continue
            try:
                val = Decimal(part.replace(",", ".")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            except (InvalidOperation, ValueError):
                raise forms.ValidationError(
                    _("Neplatná cena „%(val)s“. Zadejte čísla oddělená čárkou.")
                    % {"val": part}
                )
            if val <= 0:
                raise forms.ValidationError(_("Ceny musí být kladné."))
            if val == val.to_integral_value():
                parsed.append(str(int(val)))
            else:
                parsed.append(str(val))
        if not parsed:
            raise forms.ValidationError(_("Zadejte alespoň jednu cenu."))
        return ",".join(parsed)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("rozvrh_od_hodina")
        end = cleaned.get("rozvrh_do_hodina")
        if start is not None and end is not None and end <= start:
            self.add_error("rozvrh_do_hodina", "Konec rozvrhu musí být po začátku.")
        self._clamp_sezona_den(cleaned, "sezona_venek_od", "sezona_venek_od_den")
        self._clamp_sezona_den(cleaned, "sezona_venek_do", "sezona_venek_do_den")
        staly_od = cleaned.get("staly_pronajem_od")
        staly_do = cleaned.get("staly_pronajem_do")
        if staly_od and staly_do and staly_do < staly_od:
            self.add_error(
                "staly_pronajem_do",
                _("Konec platnosti musí být stejný den nebo po začátku."),
            )
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
        # Vzhled je per-user – klubové výchozí barvy na SystemNastaveni neměnit.
        if self.instance.pk:
            preserved = SystemNastaveni.objects.filter(pk=self.instance.pk).values(
                "barevna_varianta", "tmavy_rezim"
            ).first()
            if preserved:
                obj.barevna_varianta = preserved["barevna_varianta"]
                obj.tmavy_rezim = preserved["tmavy_rezim"]
        if commit:
            obj.save(sync_colors=True)
        return obj
