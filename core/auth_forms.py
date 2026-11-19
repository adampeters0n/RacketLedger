"""Admin authentication forms."""

from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm
from django.utils.translation import gettext_lazy as _


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    """Login form s labely pro username nebo e-mail."""

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = _("Uživatelské jméno nebo e-mail")
        self.fields["username"].widget.attrs.setdefault(
            "placeholder",
            str(_("uživatel@email.cz nebo username")),
        )


class ClubPasswordResetForm(PasswordResetForm):
    """Password reset s From z brandingu klubu (SystemNastaveni)."""

    def save(self, **kwargs):
        if kwargs.get("from_email") is None:
            try:
                from core.models import SystemNastaveni

                kwargs["from_email"] = SystemNastaveni.load().effective_from_email() or None
            except Exception:
                pass
        return super().save(**kwargs)
