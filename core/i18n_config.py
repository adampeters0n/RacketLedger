"""Konfigurace jazyků systému."""

# Podporované jazyky (kód, název v daném jazyce)
SYSTEM_LANGUAGES = [
    ("cs", "Čeština"),
    ("en", "English"),
    ("de", "Deutsch"),
    ("sk", "Slovenčina"),
    ("pl", "Polski"),
    ("es", "Español"),
    ("fr", "Français"),
    ("it", "Italiano"),
    ("nl", "Nederlands"),
    ("pt", "Português"),
    ("ru", "Русский"),
    ("uk", "Українська"),
]

SYSTEM_LANGUAGE_CODES = [code for code, _ in SYSTEM_LANGUAGES]

DEFAULT_LANGUAGE = "cs"
