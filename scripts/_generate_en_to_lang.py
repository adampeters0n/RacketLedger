#!/usr/bin/env python3
"""Generate scripts/en_to_lang.py – batch translate with post-processing."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from deep_translator import GoogleTranslator

ROOT = Path(__file__).resolve().parent
EN_VALS: list[str] = json.loads((ROOT / "_en_vals.json").read_text(encoding="utf-8"))
LANGS = ("de", "pl", "es", "fr", "it", "nl", "pt", "ru", "uk")
CACHE = ROOT / "_master_translations.json"

PLACEHOLDERS = [
    "%(var)s", "%(count)s", "%(email)s", "%(error)s", "%(date)s",
    "%(label)s", "%(rezim)s", "%(popis)s", "%(total)s", "%(num)s",
    "%(name)s", "%(staff)s",
]
KEEP_AS_IS = {
    "-", "CZK", "Kč", "Solo", "Doubles", "Home", "Delete", "Close",
    "Documentation", "Save as new", "Save and continue editing", "Save and view",
    "Dashboard", "PDF", "Excel", "JSON", "SQLite", "Earned", "Cash Flow", "PLAYERS",
    "Home › Analytics", "Nobody owes anything 🎉",
}

MONTHS = {
    "de": {"January":"Januar","February":"Februar","March":"März","April":"April","May":"Mai","June":"Juni","July":"Juli","August":"August","September":"September","October":"Oktober","November":"November","December":"Dezember"},
    "pl": {"January":"Styczeń","February":"Luty","March":"Marzec","April":"Kwiecień","May":"Maj","June":"Czerwiec","July":"Lipiec","August":"Sierpień","September":"Wrzesień","October":"Październik","November":"Listopad","December":"Grudzień"},
    "es": {"January":"Enero","February":"Febrero","March":"Marzo","April":"Abril","May":"Mayo","June":"Junio","July":"Julio","August":"Agosto","September":"Septiembre","October":"Octubre","November":"Noviembre","December":"Diciembre"},
    "fr": {"January":"Janvier","February":"Février","March":"Mars","April":"Avril","May":"Mai","June":"Juin","July":"Juillet","August":"Août","September":"Septembre","October":"Octobre","November":"Novembre","December":"Décembre"},
    "it": {"January":"Gennaio","February":"Febbraio","March":"Marzo","April":"Aprile","May":"Maggio","June":"Giugno","July":"Luglio","August":"Agosto","September":"Settembre","October":"Ottobre","November":"Novembre","December":"Dicembre"},
    "nl": {"January":"Januari","February":"Februari","March":"Maart","April":"April","May":"Mei","June":"Juni","July":"Juli","August":"Augustus","September":"September","October":"Oktober","November":"November","December":"December"},
    "pt": {"January":"Janeiro","February":"Fevereiro","March":"Março","April":"Abril","May":"Maio","June":"Junho","July":"Julho","August":"Agosto","September":"Setembro","October":"Outubro","November":"Novembro","December":"Dezembro"},
    "ru": {"January":"Январь","February":"Февраль","March":"Март","April":"Апрель","May":"Май","June":"Июнь","July":"Июль","August":"Август","September":"Сентябрь","October":"Октябрь","November":"Ноябрь","December":"Декабрь"},
    "uk": {"January":"Січень","February":"Лютий","March":"Березень","April":"Квітень","May":"Травень","June":"Червень","July":"Липень","August":"Серпень","September":"Вересень","October":"Жовтень","November":"Листопад","December":"Грудень"},
}
DAYS = {
    "de": {"Mon":"Mo","Tue":"Di","Wed":"Mi","Thu":"Do","Fri":"Fr","Sat":"Sa","Sun":"So"},
    "pl": {"Mon":"Pn","Tue":"Wt","Wed":"Śr","Thu":"Cz","Fri":"Pt","Sat":"So","Sun":"Nd"},
    "es": {"Mon":"Lun","Tue":"Mar","Wed":"Mié","Thu":"Jue","Fri":"Vie","Sat":"Sáb","Sun":"Dom"},
    "fr": {"Mon":"Lun","Tue":"Mar","Wed":"Mer","Thu":"Jeu","Fri":"Ven","Sat":"Sam","Sun":"Dim"},
    "it": {"Mon":"Lun","Tue":"Mar","Wed":"Mer","Thu":"Gio","Fri":"Ven","Sat":"Sab","Sun":"Dom"},
    "nl": {"Mon":"Ma","Tue":"Di","Wed":"Wo","Thu":"Do","Fri":"Vr","Sat":"Za","Sun":"Zo"},
    "pt": {"Mon":"Seg","Tue":"Ter","Wed":"Qua","Thu":"Qui","Fri":"Sex","Sat":"Sáb","Sun":"Dom"},
    "ru": {"Mon":"Пн","Tue":"Вт","Wed":"Ср","Thu":"Чт","Fri":"Пт","Sat":"Сб","Sun":"Вс"},
    "uk": {"Mon":"Пн","Tue":"Вт","Wed":"Ср","Thu":"Чт","Fri":"Пт","Sat":"Сб","Sun":"Нд"},
}

# Tennis-admin terminology fixes per language (English -> target)
FIXES: dict[str, dict[str, str]] = {
    "de": {
        "Overview": "Übersicht", "Analytics": "Analytik", "Coaches": "Trainer",
        "Players": "Spieler", "Trainings": "Trainings", "Billing": "Abrechnung",
        "court": "Platz", "Charged": "Berechnet", "To bill": "Abzurechnen",
        "Doubles": "Doppel", "Quads": "Vierer", "Triples": "Dreier",
        "Indoor": "Halle", "Outdoor": "Outdoor", "Coach": "Trainer",
        "Tennis school management – trainings, payments, coach billing.":
            "Tennis-Schulverwaltung – Trainings, Zahlungen, Trainerabrechnung.",
    },
    "pl": {
        "Overview": "Przegląd", "Analytics": "Analityka", "Coaches": "Trenerzy",
        "Players": "Zawodnicy", "Trainings": "Treningi", "Billing": "Rozliczenia",
        "court": "kort", "Charged": "Naliczono", "To bill": "Do rozliczenia",
        "Doubles": "Debel", "Quads": "Czwórka", "Triples": "Trójka",
        "Indoor": "Hala", "Outdoor": "Otwarty", "Coach": "Trener",
    },
    "es": {
        "Overview": "Resumen", "Analytics": "Analítica", "Coaches": "Entrenadores",
        "Players": "Jugadores", "Trainings": "Entrenamientos", "Billing": "Facturación",
        "court": "pista", "Charged": "Facturado", "To bill": "Por facturar",
        "Doubles": "Dobles", "Coach": "Entrenador",
    },
    "fr": {
        "Overview": "Aperçu", "Analytics": "Analytique", "Coaches": "Entraîneurs",
        "Players": "Joueurs", "Trainings": "Entraînements", "Billing": "Facturation",
        "court": "court", "Charged": "Facturé", "To bill": "À facturer",
        "Doubles": "Double", "Coach": "Entraîneur",
    },
    "it": {
        "Overview": "Panoramica", "Analytics": "Analitica", "Coaches": "Allenatori",
        "Players": "Giocatori", "Trainings": "Allenamenti", "Billing": "Fatturazione",
        "court": "campo", "Charged": "Addebitato", "To bill": "Da fatturare",
        "Doubles": "Doppio", "Coach": "Allenatore",
    },
    "nl": {
        "Overview": "Overzicht", "Analytics": "Analyse", "Coaches": "Trainers",
        "Players": "Spelers", "Trainings": "Trainingen", "Billing": "Facturatie",
        "court": "baan", "Charged": "Gefactureerd", "To bill": "Te factureren",
        "Doubles": "Dubbel", "Coach": "Trainer",
    },
    "pt": {
        "Overview": "Visão geral", "Analytics": "Análise", "Coaches": "Treinadores",
        "Players": "Jogadores", "Trainings": "Treinos", "Billing": "Faturação",
        "court": "campo", "Charged": "Faturado", "To bill": "A faturar",
        "Doubles": "Pares", "Coach": "Treinador",
    },
    "ru": {
        "Overview": "Обзор", "Analytics": "Аналитика", "Coaches": "Тренеры",
        "Players": "Игроки", "Trainings": "Тренировки", "Billing": "Биллинг",
        "court": "корт", "Charged": "Начислено", "To bill": "К выставлению",
        "Doubles": "Пары", "Coach": "Тренер",
    },
    "uk": {
        "Overview": "Огляд", "Analytics": "Аналітика", "Coaches": "Тренери",
        "Players": "Гравці", "Trainings": "Тренування", "Billing": "Білінг",
        "court": "корт", "Charged": "Нараховано", "To bill": "До виставлення",
        "Doubles": "Пари", "Coach": "Тренер",
    },
}


def protect(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    result = text
    for i, ph in enumerate(PLACEHOLDERS):
        if ph in result:
            tok = f"__PH{i:02d}__"
            mapping[tok] = ph
            result = result.replace(ph, tok)
    for token, orig in [
        ("__CF2__", "Cash Flow"),
        ("__CF__", "Cash Flow"), ("__ER__", "Earned"),
    ]:
        if orig in result:
            mapping[token] = orig
            result = result.replace(orig, token)
    return result, mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    for tok, orig in mapping.items():
        text = text.replace(tok, orig)
    return text


def translate_lang(lang: str, cached: dict[str, dict[str, str]]) -> dict[str, str]:
    if lang in cached and len(cached[lang]) == len(EN_VALS):
        print(f"  {lang}: using cache ({len(cached[lang])})", flush=True)
        return cached[lang]

    fixes = FIXES.get(lang, {})
    months = MONTHS[lang]
    days = DAYS[lang]
    result: dict[str, str] = {}
    to_tr: list[str] = []
    to_tr_en: list[str] = []

    for en in EN_VALS:
        if en in KEEP_AS_IS:
            result[en] = en
        elif en in fixes:
            result[en] = fixes[en]
        elif en in months:
            result[en] = months[en]
        elif en in days:
            result[en] = days[en]
        else:
            to_tr_en.append(en)
            protected, _ = protect(en)
            to_tr.append(protected)

    print(f"  {lang}: translating {len(to_tr)} strings...", flush=True)
    translator = GoogleTranslator(source="en", target=lang)
    translated: list[str] = []
    batch_size = 25
    for i in range(0, len(to_tr), batch_size):
        batch = to_tr[i : i + batch_size]
        for attempt in range(4):
            try:
                out = translator.translate_batch(batch)
                translated.extend(out)
                break
            except Exception as exc:
                print(f"    batch {i//batch_size} attempt {attempt+1} failed: {exc}", flush=True)
                time.sleep(2 ** attempt)
        else:
            for item in batch:
                try:
                    translated.append(translator.translate(item))
                except Exception:
                    translated.append(item)
                time.sleep(0.15)
        if (i // batch_size) % 5 == 0:
            print(f"    {lang}: {min(i+batch_size, len(to_tr))}/{len(to_tr)}", flush=True)
        time.sleep(0.2)

    for en, prot, tr in zip(to_tr_en, to_tr, translated):
        text = restore(tr, dict(zip([f"__PH{i:02d}__" for i in range(len(PLACEHOLDERS))], PLACEHOLDERS)))
        # restore placeholders from original
        pmap = {}
        protected, pmap = protect(en)
        text = restore(tr, pmap)
        for ph in PLACEHOLDERS:
            if ph in en and ph not in text:
                text = en
                break
        # restore proper nouns
        for noun in ("CZK", "Kč", "Earned", "Cash Flow"):
            if noun in en and noun not in text:
                if noun in ("CZK", "Kč"):
                    pass  # keep machine translation number format
                else:
                    text = text  # accept MT
        result[en] = text

    return result


def escape_py(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def write_en_to_lang(tables: dict[str, dict[str, str]]) -> None:
    lines = [
        '"""English string → translations for 9 target languages."""',
        "",
        "EN_TO_LANG: dict[str, dict[str, str]] = {",
    ]
    for lang in LANGS:
        lines.append(f'    "{lang}": {{')
        for en in EN_VALS:
            lines.append(f'        "{escape_py(en)}": "{escape_py(tables[lang][en])}",')
        lines.append("    },")
    lines.append("}")
    lines.append("")
    (ROOT / "en_to_lang.py").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    cached: dict[str, dict[str, str]] = {}
    if CACHE.exists():
        cached = json.loads(CACHE.read_text(encoding="utf-8"))

    tables: dict[str, dict[str, str]] = dict(cached)
    for lang in LANGS:
        print(f"Building {lang}...", flush=True)
        tables[lang] = translate_lang(lang, cached)
        CACHE.write_text(json.dumps(tables, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {lang}: done, saved cache", flush=True)

    write_en_to_lang(tables)
    print(f"Wrote {ROOT / 'en_to_lang.py'}", flush=True)
    for lang in LANGS:
        print(f"  {lang}: {len(tables[lang])} strings", flush=True)


if __name__ == "__main__":
    main()
