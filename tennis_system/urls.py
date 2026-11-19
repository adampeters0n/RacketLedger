# tennis_system/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from django.views.i18n import JavaScriptCatalog, set_language

from core import views as core_views
from core.auth_forms import ClubPasswordResetForm
from core.stripe_views import stripe_webhook

urlpatterns = [
    path("i18n/setlang/", set_language, name="set_language"),
    path("jsi18n/", JavaScriptCatalog.as_view(packages=["django.contrib.admin", "core"]), name="javascript-catalog"),
    path("", core_views.home, name="home"),
    path("health/", core_views.health, name="health"),
    path("privacy/", core_views.privacy, name="privacy"),
    path("terms/", core_views.terms, name="terms"),
    path("platba/uspech/", core_views.payment_success, name="payment_success"),
    path("platba/zruseno/", core_views.payment_cancelled, name="payment_cancelled"),
    path("logout/", core_views.logout_to_home, name="logout_to_home"),
    path("stripe/webhook/", stripe_webhook, name="stripe_webhook"),
    # Password reset — name admin_password_reset zapne odkaz v default admin login.html
    path(
        "admin/password_reset/",
        auth_views.PasswordResetView.as_view(
            form_class=ClubPasswordResetForm,
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.html",
            subject_template_name="registration/password_reset_subject.txt",
            success_url=reverse_lazy("password_reset_done"),
        ),
        name="admin_password_reset",
    ),
    path(
        "admin/password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "admin/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "admin/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
