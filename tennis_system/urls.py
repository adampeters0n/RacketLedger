# tennis_system/urls.py
from django.contrib import admin
from django.urls import path
from core import views as core_views

urlpatterns = [
    path("", core_views.home, name="home"),
    path("logout/", core_views.logout_to_home, name="logout_to_home"),
    path("admin/", admin.site.urls),
]
