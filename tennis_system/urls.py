# tennis_system/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from django.views.i18n import JavaScriptCatalog, set_language
from core import views as core_views

urlpatterns = [
    path("i18n/setlang/", set_language, name="set_language"),
    path("jsi18n/", JavaScriptCatalog.as_view(packages=["django.contrib.admin", "core"]), name="javascript-catalog"),
    path("", core_views.home, name="home"),
    path("logout/", core_views.logout_to_home, name="logout_to_home"),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
