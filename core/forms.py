"""Admin forms, widgets and formsets."""
from django import forms
from django.contrib.admin.widgets import AdminSplitDateTime
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms import formset_factory
from django.forms.models import BaseInlineFormSet

from .admin_utils import trener_label
from .models import Cenik, CenikFormat, Dochazka, Hrac, TrenerPlatba, VyuctovaniNastaveni

User = get_user_model()


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
        label="Trenér",
        required=True,
        empty_label="------",
    )

    datum = forms.DateField(
        label="Datum dne",
        widget=forms.DateInput(attrs={"type": "date", "class": "add-day-datum-input"}),
    )


class CopyTrainingsForm(forms.Form):
    """Výběr zdrojového a cílového dne/týdne pro kopírování tréninků."""

    SCOPE_DAY = "day"
    SCOPE_WEEK = "week"
    SCOPE_CHOICES = [
        (SCOPE_DAY, "Jeden den"),
        (SCOPE_WEEK, "Celý týden"),
    ]

    source_date = forms.DateField(
        label="Kopírovat z",
        widget=forms.DateInput(attrs={"type": "date", "class": "add-day-datum-input"}),
    )
    target_date = forms.DateField(
        label="Přidat do",
        widget=forms.DateInput(attrs={"type": "date", "class": "add-day-datum-input"}),
    )
    scope = forms.ChoiceField(
        label="Rozsah",
        choices=SCOPE_CHOICES,
        initial=SCOPE_DAY,
        widget=forms.Select(attrs={"class": "add-day-copy-scope"}),
    )
    trener = TrenerModelChoiceField(
        queryset=User.objects.order_by("username"),
        label="Trenér",
        required=False,
        empty_label="Všichni trenéři",
    )


class TrainingSlotForm(forms.Form):
    """Jeden „slot“ tréninku: čas, délka, formát, kurt, hráči."""
    cas = forms.TimeField(
        label="Čas",
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
        label="Délka (hodiny)",
        coerce=int,
        # 1 h jako výchozí – proto je první v seznamu
        choices=[
            (60, "1 h"),
            (30, "30 min"),
            (45, "45 min"),
            (90, "1,5 h"),
            (120, "2 h"),
            (150, "2,5 h"),
            (180, "3 h"),
        ],
        initial=60,
    )
    format = forms.ChoiceField(
        label="Typ tréninku",
        choices=[("", "------")],
        required=False,
        widget=forms.Select(attrs={"class": "vTextField"}),
    )
    kurt = forms.ChoiceField(
        label="Kurt",
        choices=[("", "------")] + list(Cenik.Kurt.choices),
        required=False,
    )
    poznamka = forms.CharField(
        label="Poznámka",
        required=False,
        widget=forms.TextInput(attrs={"class": "vTextField", "placeholder": "", "maxlength": 240}),
    )
    slot_datum = forms.DateField(
        label="Datum",
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(
            attrs={"type": "date", "class": "add-day-slot-datum-input"},
            format="%Y-%m-%d",
        ),
    )
    trener = TrenerModelChoiceField(
        queryset=User.objects.order_by("username"),
        label="Trenér",
        required=False,
        empty_label="—— stejný jako nahoře ——",
    )
    hraci = forms.ModelMultipleChoiceField(
        queryset=Hrac.objects.order_by("prijmeni", "jmeno"),
        label="Hráči",
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
        label="Trenér",
        empty_label="------",
    )

    class Meta:
        model = TrenerPlatba
        fields = ("user", "castka", "poznamka", "vytvoreno")
        labels = {
            "castka": "Částka",
            "poznamka": "Poznámka",
            "vytvoreno": "Datum",
        }
        widgets = {
            "castka": forms.NumberInput(attrs={"class": "vTextField", "step": "0.01"}),
            "poznamka": forms.TextInput(attrs={"class": "vTextField"}),
        }


class VyuctovaniNastaveniForm(forms.ModelForm):
    aplikovat_na_vsechny = forms.BooleanField(
        required=False,
        label="Synchronizovat režim u všech stávajících hráčů",
        help_text="Přepíše u všech hráčů režim, počet tréninků a limit kreditu podle nastavení výše.",
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
            "ucet_varianta_1",
            "ucet_varianta_2",
        ]
        widgets = {
            "auto_rezim": forms.RadioSelect,
            "auto_limit": forms.NumberInput(attrs={"class": "vTextField", "step": "1", "min": "0"}),
            "auto_castka_k_uhrade": forms.NumberInput(attrs={"class": "vTextField", "step": "1", "min": "0"}),
            "auto_pocet_treninku": forms.NumberInput(attrs={"class": "vTextField", "min": "1"}),
            "mesicni_den": forms.NumberInput(attrs={"class": "vTextField", "min": "1", "max": "28"}),
            "email_variant": forms.Select(attrs={"class": "vTextField"}),
            "ucet_varianta_1": forms.TextInput(attrs={"class": "vTextField"}),
            "ucet_varianta_2": forms.TextInput(attrs={"class": "vTextField"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["auto_rezim"].label = "Způsob vyúčtování"
        for name in ("auto_limit", "auto_castka_k_uhrade", "auto_pocet_treninku", "mesicni_den"):
            self.fields[name].required = False

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
