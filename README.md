# TenisSystém

Django aplikace pro správu tenisového klubu — hráči, tréninky, platby, vyúčtování a trenéři.

White-label model: **1 deploy = 1 klub** (vlastní DB, doména a branding).

## Požadavky

- Python 3.12+
- PostgreSQL (produkce) nebo SQLite (lokální vývoj)

## Lokální spuštění

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # volitelné – uprav proměnné
python manage.py migrate
python manage.py bootstrap_instance --nazev "Můj klub" --email "info@mujklub.cz" \
  --create-admin admin admin@mujklub.cz
# heslo: export BOOTSTRAP_ADMIN_PASSWORD=... nebo interaktivní prompt
python manage.py runserver
```

- Landing page: http://127.0.0.1:8000/
- Admin: http://127.0.0.1:8000/admin/

### Seed známého klubu

Veřejný ukázkový seed:

```bash
python manage.py bootstrap_instance --seed demo
```

Citlivé klubové profily (účty, osobní e-maily) dej do gitignored souboru:

```bash
cp core/club_seeds_local.example.py core/club_seeds_local.py
# doplň údaje, pak:
python manage.py bootstrap_instance --seed cimice
```

## Nová instance klubu (produkce)

1. Nový deploy + Postgres + DNS
2. Nastav `.env` (secret, hosts, SMTP) — viz checklist níže
3. Spusť:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
BOOTSTRAP_ADMIN_PASSWORD='…' python manage.py bootstrap_instance \
  --nazev "Tenis XY" \
  --email "info@xy.cz" \
  --email-odesilatel 'Tenis XY <info@xy.cz>' \
  --ucet1 "123456789/0100" \
  --create-admin admin admin@xy.cz
gunicorn tennis_system.wsgi:application
```

Jen aktualizace admina bez přepisu brandingu:

```bash
BOOTSTRAP_ADMIN_PASSWORD='…' python manage.py bootstrap_instance \
  --skip-branding --create-admin admin admin@xy.cz
```

Branding (logo, barvy, podpisy) lze kdykoli upravit v adminu → Nastavení.

### Checklist produkčních hostů

Domény **nejsou** baked-in v kódu. Bez správných hostů dostaneš `DisallowedHost`.

- [ ] `ALLOWED_HOSTS` obsahuje doménu instance (např. `klub.example.com`)
- [ ] `CSRF_TRUSTED_ORIGINS` s `https://` prefixem
- [ ] Volitelně `EXTRA_ALLOWED_HOSTS` / `EXTRA_CSRF_TRUSTED_ORIGINS` pro aliasy (`www.`)
- [ ] Příklad:  
  `EXTRA_ALLOWED_HOSTS=klub.example.com,www.klub.example.com`  
  `EXTRA_CSRF_TRUSTED_ORIGINS=https://klub.example.com,https://www.klub.example.com`

Ověření po deployi:

```bash
python manage.py check                # v produkci hlídá prázdné ALLOWED_HOSTS
python manage.py check_instance       # branding + hosty (při DEBUG=True: --strict-hosts)
```

## Struktura projektu

```
tennis_system/     # Django settings, urls
core/              # Hlavní appka (modely, admin, testy)
  admin/           # ModelAdmin moduly (hrac, trening, transakce…)
  club_seed.py     # Seed katalog + PRODUCT_DEFAULTS
  forms.py         # Admin formuláře
  admin_views.py   # Dashboard, analytika
  admin_urls.py    # Custom admin URL
templates/         # Django šablony
static/            # CSS, JS, obrázky
```

## Produkční env

| Proměnná | Popis |
|---|---|
| `DJANGO_SECRET_KEY` | Tajný klíč Django |
| `DEBUG` | `False` |
| `DATABASE_URL` | Postgres connection string |
| `ALLOWED_HOSTS` | Povolené domény (čárkami) |
| `CSRF_TRUSTED_ORIGINS` | `https://tvoje-domena.cz` |
| `EXTRA_ALLOWED_HOSTS` / `EXTRA_CSRF_TRUSTED_ORIGINS` | Volitelné doplnění hostů |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | SMTP pro vyúčtovací e-maily |
| `PRODUCT_NAME` | Fallback název produktu (default TenisSystém) |
| `BOOTSTRAP_ADMIN_PASSWORD` | Heslo pro `--create-admin` (non-interactive) |

## Testy

```bash
python manage.py test core
python manage.py check_instance
```

## Docker

```bash
docker compose up --build
```

- App: http://127.0.0.1:8000/
- Default admin (compose): `admin` / `admin123`

CI běží přes GitHub Actions (`.github/workflows/ci.yml`) na každém PR / push do main.
