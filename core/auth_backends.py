"""Authentication backends for TenisSystém."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameModelBackend(ModelBackend):
    """Přihlášení přes username nebo e-mail (case-insensitive u e-mailu)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or password is None:
            return None

        login = str(username).strip()
        if not login:
            return None

        user = (
            UserModel._default_manager.filter(Q(username__iexact=login) | Q(email__iexact=login))
            .order_by("id")
            .first()
        )
        if user is None:
            # Spustí password hasher i při neexistujícím uživateli (timing).
            UserModel().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
