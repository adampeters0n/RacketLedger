# core/templatetags/trening_tags.py
from django import template
from django.forms.renderers import get_default_renderer
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def render_datetime_subwidget(bound_field, index):
    """
    Vyrenderuje jeden subwidget (0=datum, 1=čas) pole datum (SplitDateTime).
    Použití: {% render_datetime_subwidget adminform.form.datum 0 %} pro datum,
             {% render_datetime_subwidget adminform.form.datum 1 %} pro čas.
    """
    widget = bound_field.field.widget
    if not hasattr(widget, "widgets") or index not in range(len(widget.widgets)):
        return ""
    id_ = widget.attrs.get("id") or bound_field.auto_id
    attrs = {"id": id_} if id_ else {}
    attrs = bound_field.build_widget_attrs(attrs)
    context = widget.get_context(
        bound_field.html_name, bound_field.value(), attrs
    )
    subwidgets = context.get("widget", {}).get("subwidgets", [])
    if index >= len(subwidgets):
        return ""
    subwidget = subwidgets[index]
    renderer = get_default_renderer()
    return mark_safe(
        renderer.render(subwidget["template_name"], {"widget": subwidget})
    )
