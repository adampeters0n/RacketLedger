# Onboarding klubu (Fáze 3.5)

## Co děláme

**Sales + manuální / poloautomatický provision** white-label instance.

```text
Deal → Stripe Customer → inventář → DNS + DB + .env → bootstrap_instance → go-live
```

Podrobnosti:

- [ops-new-instance.md](ops-new-instance.md)
- [ops-stripe.md](ops-stripe.md)
- [ops-upgrade.md](ops-upgrade.md)
- [ops-monitoring.md](ops-monitoring.md)

## Co záměrně neděláme

- **Self-serve signup** vytvářející tenant ve sdílené DB  
- Shared multi-tenant middleware / `tenant_id` na všech modelech  
- Automatické custom CNAME bez ručního DNS  

To je cesta B (odložená), až flotila / poptávka po self-serve opravdu bolí.

## Role při handoffu

| Kdo | Co |
|---|---|
| Sales / ty | smlouva, Stripe Customer, kontakt ownera |
| Ops | DNS, Postgres, `.env`, deploy, `bootstrap_instance` |
| Club admin | branding v Nastavení, uživatelé, provoz klubu |

## Po go-live

1. Owner umí login (e-mail/username) + password reset  
2. Test e-mail z Nastavení OK  
3. Uptime na `/health/`  
4. Předplatné: Nastavení → Předplatné (Checkout / portal) — viz [ops-stripe.md](ops-stripe.md)
