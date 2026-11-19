"""Shared helpers for admin modules."""
import re
from dataclasses import dataclass
from datetime import date, datetime

from django.utils import formats
from django.utils import timezone as dj_tz
from django.utils.translation import gettext_lazy as _


CZECH_MONTHS_GENITIVE = (
    "",
    "ledna",
    "února",
    "března",
    "dubna",
    "května",
    "června",
    "července",
    "srpna",
    "září",
    "října",
    "listopadu",
    "prosince",
)

CZECH_MONTHS_NOMINATIVE = (
    "",
    "leden",
    "únor",
    "březen",
    "duben",
    "květen",
    "červen",
    "červenec",
    "srpen",
    "září",
    "říjen",
    "listopad",
    "prosinec",
)

_CZECH_MONTH_ALIASES = {
    "leden": 1, "ledna": 1, "led": 1,
    "unor": 2, "únor": 2, "unora": 2, "února": 2, "uno": 2,
    "brezen": 3, "březen": 3, "brezna": 3, "března": 3, "bre": 3, "bře": 3,
    "duben": 4, "dubna": 4, "dub": 4,
    "kveten": 5, "květen": 5, "kvetna": 5, "května": 5, "kve": 5, "kvě": 5,
    "cerven": 6, "červen": 6, "cervna": 6, "června": 6,
    "cervenec": 7, "červenec": 7, "cervence": 7, "července": 7,
    "srpen": 8, "srpna": 8, "srp": 8,
    "zari": 9, "září": 9,
    "rijen": 10, "říjen": 10, "rijna": 10, "října": 10,
    "listopad": 11, "listopadu": 11, "lis": 11,
    "prosinec": 12, "prosince": 12, "pro": 12,
}


def _ascii_fold(value: str) -> str:
    folded = (value or "").lower().strip().rstrip(".")
    for src, dst in (
        ("á", "a"), ("č", "c"), ("ď", "d"), ("é", "e"), ("ě", "e"),
        ("í", "i"), ("ň", "n"), ("ó", "o"), ("ř", "r"), ("š", "s"),
        ("ť", "t"), ("ú", "u"), ("ů", "u"), ("ý", "y"), ("ž", "z"),
    ):
        folded = folded.replace(src, dst)
    return folded


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


@dataclass(frozen=True)
class ParsedDateParts:
    day: int
    month: int
    year: int | None = None


def parse_czech_date_parts(value: str) -> ParsedDateParts | None:
    """
    Rozparsuje dotaz jako datum, např. '1.7.', '13. srpna', '01.07.2026', '2026-07-01'.
    Bez roku vrátí year=None (filtrovat den + měsíc napříč roky).
    """
    raw = (value or "").strip()
    if not raw:
        return None

    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})\s*$", raw)
    if iso:
        year = int(iso.group(1))
        month = int(iso.group(2))
        day = int(iso.group(3))
        d = _safe_date(year, month, day)
        return ParsedDateParts(day=d.day, month=d.month, year=d.year) if d else None

    numeric = re.match(
        r"^(\d{1,2})\.\s*(\d{1,2})\.?(?:\s*(\d{4}))?\s*$",
        raw,
    )
    if numeric:
        day = int(numeric.group(1))
        month = int(numeric.group(2))
        year = int(numeric.group(3)) if numeric.group(3) else None
        if year is not None:
            d = _safe_date(year, month, day)
            return ParsedDateParts(day=d.day, month=d.month, year=d.year) if d else None
        if 1 <= month <= 12 and 1 <= day <= 31:
            return ParsedDateParts(day=day, month=month, year=None)
        return None

    named = re.match(
        r"^(\d{1,2})\.?\s*([A-Za-zÁČĎÉĚÍŇÓŘŠŤÚŮÝŽáčďéěíňóřšťúůýž]+)\.?(?:\s+(\d{4}))?\s*$",
        raw,
    )
    if named:
        day = int(named.group(1))
        month_key = _ascii_fold(named.group(2))
        year = int(named.group(3)) if named.group(3) else None
        month = _CZECH_MONTH_ALIASES.get(month_key)
        if month is None:
            for alias, num in _CZECH_MONTH_ALIASES.items():
                if alias.startswith(month_key) or month_key.startswith(alias):
                    month = num
                    break
        if not month:
            return None
        if year is not None:
            d = _safe_date(year, month, day)
            return ParsedDateParts(day=d.day, month=d.month, year=d.year) if d else None
        return ParsedDateParts(day=day, month=month, year=None)

    return None


def filter_queryset_by_parsed_date(queryset, parts: ParsedDateParts, *fields: str):
    """Omezí queryset na záznamy, kde některé z datetime polí spadá na daný den."""
    from django.db.models import Q

    q = Q()
    for field in fields:
        if parts.year is not None:
            q |= Q(
                **{
                    f"{field}__year": parts.year,
                    f"{field}__month": parts.month,
                    f"{field}__day": parts.day,
                }
            )
        else:
            q |= Q(**{f"{field}__month": parts.month, f"{field}__day": parts.day})
    return queryset.filter(q)


def parse_czech_date_query(value: str, *, default_year: int | None = None) -> date | None:
    """Zpětná kompatibilita – vrátí konkrétní datum (bez roku = aktuální rok)."""
    parts = parse_czech_date_parts(value)
    if not parts:
        return None
    year = parts.year if parts.year is not None else (default_year or dj_tz.localdate().year)
    return _safe_date(year, parts.month, parts.day)


def format_month_year(year: int, month: int) -> str:
    """Název měsíce a rok dle aktivního jazyka (např. červenec 2026 / July 2026)."""
    return formats.date_format(date(year, month, 1), "F Y")


def format_czech_date(value, *, include_year: bool = True) -> str:
    if isinstance(value, datetime):
        value = dj_tz.localtime(value) if dj_tz.is_aware(value) else value
        value = value.date()
    if not isinstance(value, date):
        return str(value)
    if include_year:
        return formats.date_format(value, "j. F Y")
    return formats.date_format(value, "j. F")


def get_month_choices():
    """Seznam měsíců dle aktivního jazyka."""
    return [(month, formats.date_format(date(2000, month, 1), "F")) for month in range(1, 13)]


def format_czech_datetime(value) -> tuple[str, str]:
    if isinstance(value, datetime):
        dt = dj_tz.localtime(value) if dj_tz.is_aware(value) else value
    else:
        dt = value
    return format_czech_date(dt), dt.strftime("%H:%M")


def pretty_username(username: str) -> str:
    """
    Vloží mezery před velká písmena v uživatelském jménu pro hezčí zobrazení.
    Příklad: 'AdamPeterka' -> 'Adam Peterka'.
    """
    if not username:
        return ""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", username)


def trener_label(user):
    """Jméno trenéra s mezerou mezi jménem a příjmením (get_full_name nebo rozdělení username)."""
    full = (getattr(user, "get_full_name", lambda: "")() or "").strip()
    if full:
        return full
    username = getattr(user, "username", "") or ""
    if not username:
        return username
    # Username bez mezery (např. AdamPeterka) → vložit mezeru před velká písmena
    parts = []
    for i, c in enumerate(username):
        if i and c.isupper() and c.isalpha():
            parts.append(" ")
        parts.append(c)
    return "".join(parts)


def month_range(today):
    start = today.replace(day=1)
    end = today
    return start, end
