# tennis_system/urls.py
from django.contrib import admin
from django.urls import path
from core import views as core_views
from web import views as web_views  # pokud ten modul používáš

urlpatterns = [
    # Landing page (na logu/domů)
    path("", core_views.home, name="home"),

    # Admin (včetně tvých custom /admin/core/treneri/ URL,
    # které injektuješ v admin.py přes admin.site.get_urls)
    path("admin/", admin.site.urls),

    # Volitelné „frontend“ stránky z appky web – hlavní dashboard
    # dej pod jinou cestu, aby se nebilo s "/" (home)
    path("app/", web_views.dashboard, name="dashboard"),
    path("platby/", web_views.payments_table, name="payments_table"),
]
