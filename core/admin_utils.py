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

# České řazení: C < Č < D < Ď < … < H < Ch < … < R < Ř < S < Š < … < Z < Ž
# (samohláskové diakritiky Á/É/… se berou stejně jako bez háčku)
_CZECH_CHAR_MAP = {
    "a": "a0", "á": "a0", "ä": "a0",
    "b": "b0",
    "c": "c0", "č": "c1",
    "d": "d0", "ď": "d1",
    "e": "e0", "é": "e0", "ě": "e0", "ë": "e0",
    "f": "f0",
    "g": "g0",
    "h": "h0",
    "i": "i0", "í": "i0",
    "j": "j0",
    "k": "k0",
    "l": "l0",
    "m": "m0",
    "n": "n0", "ň": "n1",
    "o": "o0", "ó": "o0", "ö": "o0",
    "p": "p0",
    "q": "q0",
    "r": "r0", "ř": "r1",
    "s": "s0", "š": "s1",
    "t": "t0", "ť": "t1",
    "u": "u0", "ú": "u0", "ů": "u0", "ü": "u0",
    "v": "v0",
    "w": "w0",
    "x": "x0",
    "y": "y0", "ý": "y0",
    "z": "z0", "ž": "z1",
}


def czech_sort_key(value: str | None) -> str:
    """Klíč pro řazení podle české abecedy (včetně Ch, Č, Ř, Š, Ž…)."""
    text = (value or "").casefold()
    parts: list[str] = []
    i = 0
    length = len(text)
    while i < length:
        if text[i] == "c" and i + 1 < length and text[i + 1] == "h":
            parts.append("h1")
            i += 2
            continue
        parts.append(_CZECH_CHAR_MAP.get(text[i], f"z9{text[i]}"))
        i += 1
    return "".join(parts)


def czech_collate(a: str | None, b: str | None) -> int:
    """Komparátor pro SQLite create_collation('CZECH', …)."""
    ka = czech_sort_key(a)
    kb = czech_sort_key(b)
    return (ka > kb) - (ka < kb)


# Numerické kódy jen z číslic → Safe nested Replace (bez rekurze jako u „a“→„a0“).
_CZECH_SQL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("ch", "12"),
    ("a", "01"),
    ("á", "01"),
    ("ä", "01"),
    ("b", "02"),
    ("c", "03"),
    ("č", "04"),
    ("d", "05"),
    ("ď", "06"),
    ("e", "07"),
    ("é", "07"),
    ("ě", "07"),
    ("ë", "07"),
    ("f", "08"),
    ("g", "09"),
    ("h", "11"),
    ("i", "14"),
    ("í", "14"),
    ("j", "15"),
    ("k", "16"),
    ("l", "17"),
    ("m", "18"),
    ("n", "19"),
    ("ň", "20"),
    ("o", "21"),
    ("ó", "21"),
    ("ö", "21"),
    ("p", "22"),
    ("q", "23"),
    ("r", "24"),
    ("ř", "25"),
    ("s", "26"),
    ("š", "27"),
    ("t", "28"),
    ("ť", "29"),
    ("u", "30"),
    ("ú", "30"),
    ("ů", "30"),
    ("ü", "30"),
    ("v", "31"),
    ("w", "32"),
    ("x", "33"),
    ("y", "34"),
    ("ý", "34"),
    ("z", "35"),
    ("ž", "36"),
)

_PG_CZECH_COLLATIONS = ("cs-x-icu", "cs_CZ", "cs-CZ-x-icu")
_pg_czech_collation_name: str | None | bool = False  # False = unknown, None = unavailable


def postgres_czech_collation() -> str | None:
    """Vrátí název dostupné české ICU/libc kolace na Postgresu, jinak None."""
    global _pg_czech_collation_name
    if _pg_czech_collation_name is not False:
        return _pg_czech_collation_name  # type: ignore[return-value]

    from django.db import connection

    if connection.vendor != "postgresql":
        _pg_czech_collation_name = None
        return None

    for name in _PG_CZECH_COLLATIONS:
        if not name.replace("-", "").replace("_", "").isalnum():
            continue
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT %s COLLATE "{name}"', ["č"])
            _pg_czech_collation_name = name
            return name
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
    _pg_czech_collation_name = None
    return None


def czech_sort_key_expr(field_name: str):
    """SQL výraz ekvivalentní czech_sort_key() – záloha, když DB nemá českou kolaci."""
    from django.db.models import F, Value
    from django.db.models.functions import Coalesce, Lower, Replace

    expr = Lower(Coalesce(F(field_name), Value("")))
    for src, dst in _CZECH_SQL_REPLACEMENTS:
        expr = Replace(expr, Value(src), Value(dst))
    return expr


def czech_order_expr(field_name: str, *, descending: bool = False):
    """Výraz pro ORDER BY podle české abecedy (SQLite CZECH / Postgres ICU / fallback klíč)."""
    from django.db import connection
    from django.db.models.functions import Collate

    if connection.vendor == "sqlite":
        expr = Collate(field_name, "CZECH")
        return expr.desc() if descending else expr

