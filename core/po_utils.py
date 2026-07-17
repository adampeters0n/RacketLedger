"""Nástroje pro práci s gettext .po soubory."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PoEntry:
    msgid: str
    msgstr: str
    prefix: str = ""


def _unescape_po(s: str) -> str:
    return s.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")


def _escape_po(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def _read_quoted_block(lines: list[str], start: int) -> tuple[str, int]:
    if start >= len(lines):
        return "", start
    first = lines[start]
    if first in ("msgid \"\"", "msgstr \"\""):
        parts: list[str] = []
        i = start + 1
        while i < len(lines) and lines[i].startswith('"'):
            parts.append(lines[i][1:-1])
            i += 1
        return _unescape_po("".join(parts)), i
    m = re.match(r'^msg(id|str) "(.*)"$', first)
    if m:
        return _unescape_po(m.group(2)), start + 1
    return "", start + 1


def parse_po(text: str) -> list[PoEntry]:
    lines = text.splitlines()
    entries: list[PoEntry] = []
    i = 0
    prefix_lines: list[str] = []
    while i < len(lines):
        line = lines[i]
        if line.startswith("msgid "):
            prefix = "\n".join(prefix_lines)
            prefix_lines = []
            msgid, i = _read_quoted_block(lines, i)
            msgstr = ""
            if i < len(lines) and lines[i].startswith("msgstr "):
                msgstr, i = _read_quoted_block(lines, i)
            if msgid:
                entries.append(PoEntry(msgid=msgid, msgstr=msgstr, prefix=prefix))
            continue
        if line.startswith("#") or not line.strip():
            prefix_lines.append(line)
        else:
            prefix_lines.append(line)
        i += 1
    return entries


def _format_quoted(key: str, value: str) -> list[str]:
    escaped = _escape_po(value)
    if "\n" in value or len(escaped) > 70:
        out = [f'{key} ""']
        chunk = escaped
        while chunk:
            out.append(f'"{chunk[:70]}"')
            chunk = chunk[70:]
        return out
    return [f'{key} "{escaped}"']


def remove_obsolete_po_entries(text: str) -> str:
    """Odstraní zastaralé (#~) záznamy – jinak kolidují s novými msgid."""
    lines = text.splitlines()
    return "\n".join(line for line in lines if not line.startswith("#~")) + "\n"


def inject_missing_po_entries(text: str, catalog: dict[str, str]) -> tuple[str, int]:
    """Přidá do .po souboru msgid z katalogu, které makemessages neextrahoval."""
    entries = parse_po(text)
    existing = {e.msgid for e in entries}
    missing = [(msgid, msgstr) for msgid, msgstr in catalog.items() if msgid and msgid not in existing and msgstr]
    if not missing:
        return text, 0
    extra: list[str] = ["", "# Doplněno z katalogu překladů"]
    for msgid, msgstr in sorted(missing, key=lambda x: x[0]):
        extra.append("")
        extra.extend(_format_quoted("msgid", msgid))
        extra.extend(_format_quoted("msgstr", msgstr))
    return text.rstrip() + "\n" + "\n".join(extra) + "\n", len(missing)


def update_po_translations(text: str, catalog: dict[str, str]) -> tuple[str, int]:
    """Doplní nebo opraví msgstr v .po souboru bez přerenderování celého souboru."""
    lines = text.splitlines()
    result: list[str] = []
    count = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("msgid "):
            msgid, next_i = _read_quoted_block(lines, i)
            while result and (result[-1].startswith("#, fuzzy") or result[-1].startswith("#|")):
                result.pop()
            result.extend(lines[i:next_i])
            if msgid and next_i < len(lines) and lines[next_i].startswith("msgstr "):
                msgstr, after = _read_quoted_block(lines, next_i)
                translation = catalog.get(msgid)
                if translation:
                    if not msgstr.strip() or msgstr != translation:
                        result.extend(_format_quoted("msgstr", translation))
                        count += 1
                    else:
                        result.extend(lines[next_i:after])
                    i = after
                    continue
            i = next_i
            continue
        result.append(line)
        i += 1
    return "\n".join(result) + "\n", count
