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

Kompletní checklist: **[docs/ops-new-instance.md](docs/ops-new-instance.md)**  
Upgrade flotily: **[docs/ops-upgrade.md](docs/ops-upgrade.md)**  
Stripe předplatné: **[docs/ops-stripe.md](docs/ops-stripe.md)**  
Monitoring: **[docs/ops-monitoring.md](docs/ops-monitoring.md)**  
Onboarding (ne self-serve): **[docs/ops-onboarding.md](docs/ops-onboarding.md)**  
Šablona inventáře: **[docs/instances.example.csv](docs/instances.example.csv)** (reálná data drž mimo git)

Zkrácený postup:

1. Nový deploy + Postgres + DNS
2. Nastav `.env` (secret, hosts, SMTP) — viz [`.env.example`](.env.example) a checklist v ops runbooku
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
python manage.py check                # hosty, SECRET_KEY, SMTP, média
python manage.py check_instance       # branding + hosty (při DEBUG=True: --strict-hosts)
curl -fsS https://klub.example.com/health/   # {"status":"ok"}
```

Health endpoint (`/health/`) je bez auth — vhodný pro uptime monitoring.

### Cron – předpokládaný rozvrh

Každý den ve **22:00** (Europe/Prague) ze stálého rozvrhu založí chybějící tréninky **na dnešek** (sloty, které ten den v Předpokládaném byly):

```bash
python manage.py materializovat_predpokladany
```

Na Renderu přidejte **Cron Job** se stejným image/env jako web. Cron je v UTC (22:00 CET ≈ `0 21 * * *`, v létě CEST ≈ `0 20 * * *`).

### Zálohy Postgres (disaster recovery)

JSON export/import v Nastavení je **ne** náhrada za DB dump — slouží jako platform tool, ne DR.

Pravidelný dump (příklad denně přes cron / managed backup):

```bash
# Dump (z hostitele nebo jobu s přístupem k DB)
pg_dump "$DATABASE_URL" --format=custom --file="tenissystem-$(date +%F).dump"

# Nebo klasicky:
# pg_dump -h HOST -U USER -d DBNAME -Fc -f tenissystem-YYYY-MM-DD.dump
```

Restore drill (na staging, ne na živé produkci napoprvé):

```bash
# 1) Nová prázdná DB / staging instance
# 2) Obnovení:
pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" tenissystem-YYYY-MM-DD.dump
# 3) python manage.py migrate   # kdyby dump byl starší než kód
# 4) python manage.py check_instance
# 5) Ověř login + logo + jeden hráč / trénink
```

Checklist:

- [ ] Dump běží automaticky (managed provider backup **nebo** cron `pg_dump`)
- [ ] Dump je mimo app disk (object storage / jiný server)
- [ ] Alespoň 1× za kvartál restore drill na staging
- [ ] Po restore funguje `/health/` a admin login

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
| `SENTRY_DSN` | Volitelné — crash reporting |
| `USE_S3` + `AWS_*` | Volitelné — média (logo) na S3/R2 |
| `BILLING_ACTIVE` | Nouzový zámek `0` (default `1`) |
| `STRIPE_SECRET_KEY` / `STRIPE_PRICE_ID` / `STRIPE_WEBHOOK_SECRET` | Checkout + webhook |
| `STRIPE_REQUIRE_SUBSCRIPTION` | `1` = bez active předplatného read-only |
| `STRIPE_CUSTOMER_ID` | Volitelný seed customera (jinak z Checkoutu) |
| `INSTANCE_NAME` | Tag v logách / Sentry (default hostname) |
| `AXES_FAILURE_LIMIT` / `AXES_COOLOFF_TIME` | Rate-limit admin loginu |

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

CI běží přes GitHub Actions (`.github/workflows/ci.yml`) na každém PR / push do main — testy a bootstrap smoke proti **Postgres 16**.
