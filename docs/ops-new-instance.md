# Ops: nová instance klubu

White-label: **1 deploy = 1 klub** (vlastní DB, doména, branding).

## Před startem

- [ ] Smlouva / deal hotový
- [ ] Doména připravená (např. `klub.example.com`)
- [ ] Záznam v inventáři — zkopíruj řádek ze [instances.example.csv](instances.example.csv) do svého sheetu (mimo git)

## 1. Infrastruktura

1. Vytvoř **Postgres** (managed nebo Docker) — jedna DB jen pro tento klub.
2. Nastav **DNS** A/CNAME na hostitele appky.
3. TLS (Let’s Encrypt / proxy) — HTTPS povinné v produkci.
4. Připrav runtime (VM / PaaS / Docker) s Python 3.12+, gunicorn, přístupem k DB.

## 2. Environment

```bash
cp .env.example .env
# vyplň produkční hodnoty — viz checklist níže
```

Povinné v produkci (`DEBUG=False`):

| Proměnná | Příklad |
|---|---|
| `DJANGO_SECRET_KEY` | dlouhý náhodný řetězec (ne default) |
| `DEBUG` | `False` |
| `DATABASE_URL` | `postgres://…` |
| `ALLOWED_HOSTS` | `klub.example.com,www.klub.example.com` |
| `CSRF_TRUSTED_ORIGINS` | `https://klub.example.com,https://www.klub.example.com` |
| `EMAIL_HOST` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | SMTP klubu |
| `DEFAULT_FROM_EMAIL` | `Klub XY <noreply@klub.example.com>` |

Doporučené:

- `USE_S3=1` + `AWS_*` (logo/favicon)
- `SENTRY_DSN`
- `DATABASE_SSL_REQUIRE=True` u managed Postgres

## 3. Deploy + bootstrap

```bash
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py collectstatic --noinput

BOOTSTRAP_ADMIN_PASSWORD='…' python manage.py bootstrap_instance \
  --nazev "Tenis XY" \
  --email "info@xy.cz" \
  --email-odesilatel 'Tenis XY <info@xy.cz>' \
  --ucet1 "123456789/0100" \
  --create-admin admin admin@xy.cz

gunicorn tennis_system.wsgi:application --bind 0.0.0.0:8000
```

Docker: viz `docker compose` / `scripts/docker-entrypoint.sh` (migrate + collectstatic + volitelný bootstrap).

Jen admin bez přepisu brandingu:

```bash
BOOTSTRAP_ADMIN_PASSWORD='…' python manage.py bootstrap_instance \
  --skip-branding --create-admin admin admin@xy.cz
```

## 4. Ověření (go-live checklist)

```bash
python manage.py check
python manage.py check_instance
curl -fsS https://klub.example.com/health/
```

V UI:

- [ ] Landing ukazuje správný název klubu
- [ ] Admin login funguje (e-mail nebo username)
- [ ] Nastavení → **testovací e-mail** dorazí
- [ ] Upload loga (pokud S3) se zobrazí
- [ ] `/privacy/` a `/terms/` jsou dostupné
- [ ] Password reset odkaz na login stránce

## 5. Monitoring & zálohy

- [ ] Uptime monitor na `https://…/health/`
- [ ] Sentry DSN nastavené (pokud používáš)
- [ ] Postgres backup zapnutý — viz README sekce záloh
- [ ] Inventář doplněný (URL, DB, owner, později Stripe customer ID)
- [ ] Stripe předplatné — viz [ops-stripe.md](ops-stripe.md) (Fáze 2)

## Rychlé troubleshooting

| Symptom | Kontrola |
|---|---|
| `DisallowedHost` | `ALLOWED_HOSTS` / `EXTRA_ALLOWED_HOSTS` |
| CSRF 403 | `CSRF_TRUSTED_ORIGINS` s `https://` |
| Logo mizí po redeploy | `USE_S3` nebo persistent `MEDIA_ROOT` |
| E-maily nechodí | SMTP + test v Nastavení; `manage.py check` → W002 |
| `check` hlásí E004 | nastav silný `DJANGO_SECRET_KEY` |
