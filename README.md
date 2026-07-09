# Tenis systém Čimice

Django aplikace pro správu tenisového klubu — hráči, tréninky, platby, vyúčtování a trenéři.

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
python manage.py createsuperuser
python manage.py runserver
```

- Landing page: http://127.0.0.1:8000/
- Admin: http://127.0.0.1:8000/admin/

## Struktura projektu

```
tennis_system/     # Django settings, urls
core/              # Hlavní appka (modely, admin, testy)
  admin/           # ModelAdmin moduly (hrac, trening, transakce…)
  forms.py         # Admin formuláře
  admin_views.py   # Dashboard, analytika
  admin_urls.py    # Custom admin URL
templates/         # Django šablony
static/            # CSS, JS, obrázky
```

## Produkční deploy

Projekt používá Gunicorn + WhiteNoise. V produkci nastav:

| Proměnná | Popis |
|---|---|
| `DJANGO_SECRET_KEY` | Tajný klíč Django |
| `DEBUG` | `False` |
| `DATABASE_URL` | Postgres connection string |
| `ALLOWED_HOSTS` | Povolené domény (čárkami) |
| `CSRF_TRUSTED_ORIGINS` | `https://tvoje-domena.cz` |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | SMTP pro vyúčtovací e-maily |

```bash
python manage.py collectstatic --noinput
python manage.py migrate
gunicorn tennis_system.wsgi:application
```

## Testy

```bash
python manage.py test core
```
