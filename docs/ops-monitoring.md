# Ops: monitoring a uptime (Fáze 3.3)

## Health check

Každá instance má veřejný endpoint:

```bash
curl -fsS https://klub.example.com/health/
# {"status":"ok"}
```

- **200** + `status=ok` → DB živá  
- **503** → problém s DB / appkou  

Bez auth, bez secretů — vhodné pro UptimeRobot, Better Stack, Pingdom, Cloudflare Health Checks, …

## Doporučené nastavení monitoru

| Položka | Hodnota |
|---|---|
| URL | `https://<domena>/health/` |
| Interval | 1–5 min |
| Alert | e-mail / Slack při 2+ selháních |
| Timeout | 10–15 s |

Do inventáře si poznamenej, který monitor hlídá kterou instanci.

## Sentry

V `.env`:

```bash
SENTRY_DSN=…
INSTANCE_NAME=klub-xy          # tag v logách i Sentry
SENTRY_ENVIRONMENT=production
SENTRY_RELEASE=1.2.3           # nebo GIT_COMMIT / RENDER_GIT_COMMIT
```

Release se bere z `SENTRY_RELEASE` → `GIT_COMMIT` → `RENDER_GIT_COMMIT` → `SOURCE_VERSION`.

## Logy

Stdout formát:

```text
2026-09-11 12:00:00,000 INFO instance=klub-xy django.request …
```

Filtr `core.logging_filters.InstanceContextFilter` přidává `instance=`.

## Checklist flotily

- [ ] Každá produkční instance má uptime na `/health/`
- [ ] Alert dorazí (ověř testovacím výpadkem / false URL)
- [ ] Sentry DSN nastavené (pokud používáš)
- [ ] `INSTANCE_NAME` unikátní per klub
- [ ] Deploy nastavuje `SENTRY_RELEASE` (git sha)
