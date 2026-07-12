"""Jednoduché řazení changelist tabulek – jeden sloupec, bez čísel v hlavičce."""
from django.contrib import admin
from django.contrib.admin.views.main import ChangeList, ORDER_VAR
from django.db.models import OrderBy
from django.http import HttpResponseRedirect
from django.utils.http import urlencode


class SingleColumnChangeList(ChangeList):
    def get_ordering(self, request, queryset):
        params = self.params
        ordering = list(
            self.model_admin.get_ordering(request) or self._get_default_ordering()
        )
        raw = params.get(ORDER_VAR)
        if raw:
            ordering = []
            order_param = str(raw).split(".")[0]
            try:
                _none, pfx, idx = order_param.rpartition("-")
                field_name = self.list_display[int(idx)]
                order_field = self.get_ordering_field(field_name)
                if order_field:
                    if isinstance(order_field, OrderBy):
                        if pfx == "-":
                            order_field = order_field.copy()
                            order_field.reverse_ordering()
                        ordering.append(order_field)
                    elif hasattr(order_field, "resolve_expression"):
                        ordering.append(
                            order_field.desc() if pfx == "-" else order_field.asc()
                        )
                    elif pfx == "-" and order_field.startswith(pfx):
                        ordering.append(order_field.removeprefix(pfx))
                    else:
                        ordering.append(pfx + order_field)
            except (IndexError, ValueError):
                pass
        ordering.extend(queryset.query.order_by)
        return self._get_deterministic_ordering(ordering)


def patch_admin_single_column_sorting():
    """Aplikuje jednosloupcové řazení na všechny ModelAdmin tabulky."""
    if getattr(admin.ModelAdmin, "_single_column_sort_patched", False):
        return

    _orig_changelist_view = admin.ModelAdmin.changelist_view

    def get_changelist(self, request, **kwargs):
        return SingleColumnChangeList

    def changelist_view(self, request, extra_context=None):
        order = request.GET.get(ORDER_VAR, "")
        if order and "." in order:
            params = request.GET.copy()
            params[ORDER_VAR] = order.split(".")[0]
            return HttpResponseRedirect(f"{request.path}?{urlencode(params, doseq=True)}")
        return _orig_changelist_view(self, request, extra_context)

    admin.ModelAdmin.get_changelist = get_changelist
    admin.ModelAdmin.changelist_view = changelist_view
    admin.ModelAdmin._single_column_sort_patched = True
