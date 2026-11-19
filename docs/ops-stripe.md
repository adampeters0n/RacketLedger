# Ops: Stripe — předplatné TenisSystém + online platby hráčů

**Model:** 1 white-label instance = 1 deploy.  
**Ne:** shared Tenant, veřejný signup vytvářející nový deploy.

Dvě oddělené peněžní cesty na stejném platformním Stripe účtu:

| Účel | Model | Checkout |
|------|--------|----------|
| Předplatné za software | `SoftwareBilling` | `mode=subscription` |
| Platby hráčů klubu | `ClubStripeConnect` + `Transakce(PLATBA)` | `mode=payment` + Connect destination |

## A) Předplatné TenisSystém

1. **Checkout** — Nastavení → Předplatné → *Aktivovat předplatné*.
2. **Webhook** → `SoftwareBilling` (customer, subscription, status).
3. **Gate** — neaktivní předplatné = club staff read-only.  
   `BILLING_ACTIVE=0` = ruční zámek (ops).
4. **Customer Portal** — správa karty / zrušení.

## B) Online platby hráčů (Stripe Connect)

1. Klub v Nastavení → **Platby hráčů** jednou propojí **Express** účet.
2. Při vyúčtování (ruční i auto) appka vytvoří Checkout Session s metadata `hrac_id` / `vyuctovani_id`.
3. E-mail obsahuje tlačítko **Zaplatit online** (+ bankovní převod jako fallback).
4. Webhook `checkout.session.completed` (`purpose=player_payment`) → `Transakce(PLATBA)` v adminu Platby (idempotentně).

## 1) Jednou ve Stripe Dashboard

1. Product + recurring **Price** (měsíční/roční) — SaaS.
2. Zapni **Connect** (Settings → Connect). Appka používá **Accounts v2** (Express dashboard).
3. Zapni **Customer portal**.
4. Developers → Webhooks → Add endpoint:
   - URL: `https://<instance>/stripe/webhook/`
   - Events:  
     `checkout.session.completed`  
     `customer.subscription.created`  
     `customer.subscription.updated`  
     `customer.subscription.deleted`  
     `invoice.paid`  
     `invoice.payment_failed`  
     `account.updated`
5. Zkopíruj **Signing secret** (`whsec_…`).

## 2) `.env` instance

```bash
STRIPE_SECRET_KEY=sk_live_…          # nebo sk_test_…
STRIPE_PRICE_ID=price_…              # SaaS Price
STRIPE_WEBHOOK_SECRET=whsec_…

# Volitelné SaaS:
# STRIPE_CUSTOMER_ID=cus_…           # seed staršího customera
# STRIPE_REQUIRE_SUBSCRIPTION=1
# BILLING_ACTIVE=1

# Platby hráčů:
# STRIPE_PLAYER_CURRENCY=czk
# STRIPE_CONNECT_COUNTRY=CZ
# Lokálně bez Connect KYC (jen test keys): STRIPE_CONNECT_TEST_BYPASS=1
# PUBLIC_BASE_URL=https://klub.example.com   # return URL + odkazy v e-mailech
```

Restart appky. Migrace: `SoftwareBilling`, `ClubStripeConnect` (`migrate`).

## 3) Tok pro klub

### Předplatné
1. Nastavení → **Předplatné** → Aktivovat → Checkout
2. Webhook → `active` / `trialing`
3. Správa předplatného → Customer Portal

### Platby hráčů
1. Nastavení → **Platby hráčů** → *Propojit Stripe* (KYC)
2. Po `charges_enabled` + `details_submitted` = Připraveno
3. Vygenerovat vyúčtování / auto e-mail → rodič Zaplatí → řádek v **Platby**

## 4) Lokální vývoj webhooku

```bash
stripe listen --forward-to localhost:8000/stripe/webhook/
# do .env dej whsec_ z výstupu stripe listen
```

## 5) Rychlý lokální sandbox (macOS)

```bash
# 1) Do .env: STRIPE_SECRET_KEY=sk_test_…  (Dashboard → API keys)
# 2) Product + Price
python manage.py setup_stripe_sandbox --write-env

# 3) Webhook do localhost
stripe login
stripe listen --forward-to localhost:8000/stripe/webhook/
# whsec_… → STRIPE_WEBHOOK_SECRET v .env

# 4) Restart runserver → Nastavení → Předplatné / Platby hráčů
```

`PUBLIC_BASE_URL=http://127.0.0.1:8000` už má být v `.env`.

## Checklist

- [ ] Product/Price + Customer portal
- [ ] Connect Express zapnutý
- [ ] Webhook + events (včetně `account.updated`) + `STRIPE_WEBHOOK_SECRET`
- [ ] `.env`: `STRIPE_SECRET_KEY` (+ `STRIPE_PRICE_ID` pro SaaS)
- [ ] `PUBLIC_BASE_URL` v produkci
- [ ] Test SaaS Checkout → stav v Předplatné
- [ ] Test Connect onboarding → Připraveno v Platby hráčů
- [ ] Test vyúčtování e-mail → Zaplatit → `PLATBA` v Platbách
- [ ] Produkce SaaS: `STRIPE_REQUIRE_SUBSCRIPTION=1`
