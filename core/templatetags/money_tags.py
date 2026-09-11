from django import template

from core.money import format_castka, get_mena_symbol

register = template.Library()


@register.simple_tag
def mena_symbol():
    return get_mena_symbol()


@register.filter(name="castka")
def castka_filter(value, arg=None):
    """{{ value|castka }} nebo {{ value|castka:"h" }} pro /h."""
    return format_castka(value, per_hour=(arg == "h"))
