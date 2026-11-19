# Ops: upgrade instance (a flotily)

Postup pro **jednu** white-label instanci. U N klubů stejné kroky opakuj podle inventáře.

## Před upgrade

- [ ] Přečti changelog / PR poznámky
- [ ] Ověř, že máš aktuální backup DB (managed snapshot nebo `pg_dump`)
- [ ] Staging / jedna nejdůležitější instance jako canary (pokud máš víc než 1)
- [ ] Domluvené krátké okno údržby (volitelné)

## Jedna instance

### A) Git / VM

```bash
cd /path/to/app
git fetch && git checkout <tag-or-main>
# nebo: git pull

source venv/bin/activate   # nebo .venv
pip install -r requirements.txt

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# restart procesu (příklad)
sudo systemctl restart tenissystem
# nebo: sudo kill -HUP <gunicorn-master-pid>
# nebo: docker compose up -d --build
```

### B) Docker Compose

```bash
docker compose pull   # pokud používáš registry image
# nebo:
docker compose build
docker compose up -d

# entrypoint už dělá migrate + collectstatic
```

### C) PaaS (Render / Railway / …)

1. Deploy nové revision z `main` / tagu  
2. Release command: `python manage.py migrate --noinput`  
3. Build: `collectstatic` dle platformy  

## Po upgrade (smoke)

```bash
python manage.py check
python manage.py check_instance
curl -fsS https://klub.example.com/health/
```

V UI rychle:

- [ ] Admin login
- [ ] Dashboard / jeden changelist
- [ ] Logo a branding OK

Při Sentry: nastav `SENTRY_RELEASE` na git sha / tag deploye.

## Flotila (N klubů)

1. Seřaď instance podle rizika (canary → ostatní).
2. Pro každý řádek inventáře:
   - [ ] Upgrade podle postupu výše
   - [ ] `/health/` = ok
   - [ ] Poznamenej čas a verzi do inventáře
3. Pokud canary selže → **stop**, rollback canary, nepokračuj na zbytek.

### Rollback (základ)

1. Obnov předchozí image / git tag  
2. Pokud migrace nejsou zpětně kompatibilní: restore DB ze snapshotu **před** migrate  
3. `curl /health/` + login  

Migrace piš dopředně kompatibilní (expand/contract), ať rollback appky bez restore DB je častěji možný.

## Co upgrade nedělá

- Nepřepisuje branding (to dělá jen `bootstrap_instance` bez `--skip-branding`)
- Nemění DNS ani Stripe zákazníka
- Nenahrazuje DR zálohy — ty běží odděleně (README)
