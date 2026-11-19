# Plán A — White-label SaaS (1 deploy = 1 klub)

**Rozhodnutí:** produktová cesta = multi-instance white-label.  
Shared multi-tenant (Tenant + řádková izolace) **neděláme**, dokud flotila / self-serve nebolí.

**Model:** každá platící škola = vlastní deploy + DB + doména + branding.  
**Platby za software:** Stripe (mimo appku nebo lehká integrace).  
**Vyúčtování hráčů:** e-mail s rozpisem + online platba (Stripe Connect) → automatický zápis `PLATBA`; bankovní převod zůstává fallback.

```text
Prodej / smlouva → provision instance → bootstrap_instance → klub běží
                      ↑                    ↑
                 DNS + .env + DB     branding + club_admin
```

---

## Fáze 0 — Spolehlivost instance (první)

Cíl: každá instance je bezpečně provozuschopná. Nezávislé na počtu klubů.

| # | Úkol | Hotovo když | Soubory / poznámka |
|---|------|-------------|-------------------|
| 0.1 | Password reset | Admin/staff dostane e-mail a obnoví heslo | Django `PasswordReset*` + šablony; SMTP z settings / `SystemNastaveni` |
| 0.2 | `/health` | HTTP 200 při živé DB, bez auth | Nový view + URL; pro uptime monitor |
| 0.3 | Produkční checky | `DEBUG=False` + default `SECRET_KEY` = error; chybí SMTP/storage = warning | Rozšířit `core/checks.py` + `check_instance` |
| 0.4 | Sentry | Crash reporty při nastaveném `SENTRY_DSN` | `sentry-sdk`, init v settings z env |
| 0.5 | Média v produkci | Logo/favicon fungují mimo DEBUG | `django-storages` + S3 env; dnes media jen při DEBUG v `tennis_system/urls.py` |
| 0.6 | Zálohy | Runbook `pg_dump` / restore + 1× drill | Sekce v README; ne jen JSON export |
| 0.7 | Legal | Privacy + Terms na landingu | Statické stránky + odkazy ve footeru |

**Pořadí uvnitř Fáze 0:** 0.1 → 0.2 → 0.3 → 0.4 → 0.5 → 0.6 → 0.7.

---

## Fáze 1 — Provisioning & provoz flotily

Cíl: nový klub = opakovatelný checklist, ne ad-hoc.

| # | Úkol | Stav | Soubor |
|---|------|------|--------|
| 1.1 | Runbook „Nová instance“ | hotovo | [docs/ops-new-instance.md](ops-new-instance.md) |
| 1.2 | Šablona `.env` per klub | hotovo | [`.env.example`](../.env.example) |
| 1.3 | Upgrade playbook | hotovo | [docs/ops-upgrade.md](ops-upgrade.md) |
| 1.4 | Inventář instancí | hotovo (šablona) | [docs/instances.example.csv](instances.example.csv) — reálná data mimo git |
| 1.5 | CI proti Postgres | hotovo | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) |

Reuse: `bootstrap_instance`, `check_instance`, `club_seed`, Docker entrypoint.

---

## Fáze 2 — Peníze za TenisSystém (Stripe)

Cíl: předplatné za software na existující white-label instance.

| # | Úkol | Stav |
|---|------|------|
| 2.1 | Stripe produkty / portal / webhook v Dashboard | docs [ops-stripe.md](ops-stripe.md) |
| 2.2 | Env: secret + price + webhook (+ volitelný customer seed) | docs |
| 2.3 | Checkout + Customer Portal v Nastavení | hotovo |
| 2.4 | Webhook → `SoftwareBilling` + gate | hotovo |

**Záměrně ne:** signup landing → webhook → CreateTenant / nový deploy.

---

## Fáze 3 — Provozní polish

| # | Úkol | Stav |
|---|------|------|
| 3.1 | Rate-limit login | hotovo — `django-axes` |
| 3.2 | Strukturované logy + Sentry release | hotovo — `INSTANCE_NAME`, release fallbacky |
| 3.3 | Monitoring `/health` | hotovo — [ops-monitoring.md](ops-monitoring.md) |
| 3.4 | ESP (Postmark/SendGrid) | odloženo — až SMTP nestačí |
| 3.5 | Docs onboarding ≠ self-serve | hotovo — [ops-onboarding.md](ops-onboarding.md) |

---

## Záměrně mimo plán A

- Shared multi-tenant (`Tenant`, middleware, scoped querysets)
- Veřejný signup vytvářející tenant v jedné DB
- Schema/DB orchestration per tenant v jedné app
- Automatické custom CNAME (zatím ruční DNS per klub)
- Přepis klubového vyúčtování hráčů na Stripe
- 2FA, impersonace, Redis/Celery — až bolí

---

## Pořadí implementace (checklist)

- [x] **0.1** Password reset
- [x] **0.2** `/health`
- [x] **0.3** Produkční checky
- [x] **0.4** Sentry
- [x] **0.5** S3 média
- [x] **0.6** Backup runbook
- [x] **0.7** Privacy + Terms
- [x] **1.1–1.5** Provisioning runbooky + inventář + CI Postgres
- [x] **2.1–2.4** Stripe předplatné (manuální + portal)
- [x] **3.1–3.5** Rate-limit, logy/Sentry, monitoring + onboarding docs (ESP odloženo)

**Odhad:** Fáze 0 = dny; Fáze 1 = dny (dokumentace + disciplína); Fáze 2 = dny–týden; Fáze 3 průběžně.

**Přechod na B zvaž až když:** 10–20+ aktivních klubů **a** bolí N× deploy/upgrade, **nebo** musíš mít veřejný self-serve signup.
