# Plán A — White-label SaaS (1 deploy = 1 klub)

**Rozhodnutí:** produktová cesta = multi-instance white-label.  
Shared multi-tenant (Tenant + řádková izolace) **neděláme**, dokud flotila / self-serve nebolí.

**Model:** každá platící škola = vlastní deploy + DB + doména + branding.  
**Platby za software:** Stripe (mimo appku nebo lehká integrace).  
**Vyúčtování hráčů:** beze změny (oddělený cashflow klubu).

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

| # | Úkol | Hotovo když |
|---|------|-------------|
| 1.1 | Runbook „Nová instance“ | Jeden dokument: DNS, Postgres, `.env`, migrate, `bootstrap_instance`, SMTP test, `check_instance` |
| 1.2 | Šablona `.env` per klub | `.env.example` pokryje všechny produkční klíče; žádné baked-in hosty |
| 1.3 | Upgrade playbook | Postup: migrate + collectstatic + restart na **jedné** instanci; checklist pro N klubů |
| 1.4 | Inventář instancí | Jednoduchá tabulka mimo app (Notion/sheet): klub, URL, DB, Stripe customer, kontakt |
| 1.5 | CI proti Postgres | Volitelně job s Postgres service (dnes SQLite stačí lokálně) |

Reuse: `bootstrap_instance`, `check_instance`, `club_seed`, Docker entrypoint.

---

## Fáze 2 — Peníze za TenisSystém (Stripe)

Cíl: předplatné za software, ne self-serve Tenant v jedné DB.

| # | Úkol | Hotovo když |
|---|------|-------------|
| 2.1 | Stripe produkty / prices | Plán(y) + trial v Stripe Dashboard |
| 2.2 | Manuální napojení | Po zaplacení / smlouvě: záznam customer ID do inventáře + provision instance |
| 2.3 | Customer Portal odkaz | Owner klubu má v Nastavení odkaz „Správa předplatného“ (Stripe Billing Portal) — **bez** CreateTenant webhooků |
| 2.4 | Stavy předplatného | Runbook: unpaid → upozornění / suspend instance (manuálně nebo feature flag v `.env` např. `BILLING_ACTIVE=0`) |

**Záměrně ne:** signup → webhook → CreateTenant v shared DB.

---

## Fáze 3 — Provozní polish

| # | Úkol |
|---|------|
| 3.1 | Rate-limit login (např. django-axes / cache) |
| 3.2 | Strukturované logy + Sentry release per deploy |
| 3.3 | Monitoring: uptime na `/health` + alert při pádu |
| 3.4 | ESP později (Postmark/SendGrid), pokud SMTP nestačí |
| 3.5 | Dokumentace: self-serve **neděláme**; onboarding = sales + provision |

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

- [ ] **0.1** Password reset
- [ ] **0.2** `/health`
- [ ] **0.3** Produkční checky
- [ ] **0.4** Sentry
- [ ] **0.5** S3 média
- [ ] **0.6** Backup runbook
- [ ] **0.7** Privacy + Terms
- [ ] **1.1–1.4** Provisioning runbooky + inventář
- [ ] **2.1–2.4** Stripe předplatné (manuální + portal)
- [ ] **3.x** Polish podle potřeby

**Odhad:** Fáze 0 = dny; Fáze 1 = dny (dokumentace + disciplína); Fáze 2 = dny–týden; Fáze 3 průběžně.

**Přechod na B zvaž až když:** 10–20+ aktivních klubů **a** bolí N× deploy/upgrade, **nebo** musíš mít veřejný self-serve signup.
