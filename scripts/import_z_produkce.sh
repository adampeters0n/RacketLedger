#!/bin/bash
# Import dat z produkce do lokální SQLite databáze.
# Podrobný návod: viz komentáře níže a odpověď v chatu.

set -euo pipefail
cd "$(dirname "$0")/.."

DUMP="data/production_dump.json"

if [[ ! -f "$DUMP" ]]; then
  echo "Chybí soubor $DUMP"
  echo ""
  echo "Nejdřív exportuj data z produkce (krok 1 v návodu)."
  exit 1
fi

# Ujisti se, že nepoužíváš produkční DATABASE_URL
if [[ -n "${DATABASE_URL:-}" ]]; then
  echo "VAROVÁNÍ: DATABASE_URL je nastavená – import by šel do produkce!"
  echo "Spusť: unset DATABASE_URL"
  exit 1
fi

python3 manage.py import_produkce "$DUMP"
