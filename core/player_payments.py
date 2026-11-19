"""Online platby hráčů přes Stripe Connect — oddělené od SaaS předplatného.

Tok:
- klub jednou propojí Express účet (ClubStripeConnect)
- při vyúčtování vznikne Checkout Session s metadata hrac_id / vyuctovani_id
- webhook checkout.session.completed → Transakce(PLATBA) idempotentně
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

PLAYER_PAYMENT_PURPOSE = "player_payment"


def _stripe():
    from core.billing import _stripe as billing_stripe

    return billing_stripe()


def _meta(obj) -> dict:
    if isinstance(obj, dict):
        raw = obj.get("metadata") or {}
    else:
        raw = getattr(obj, "metadata", None) or {}
    if hasattr(raw, "to_dict"):
        return dict(raw.to_dict())
    return dict(raw) if raw else {}


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def get_connect():
    from core.models import ClubStripeConnect

    return ClubStripeConnect.load()


def connect_test_bypass_enabled() -> bool:
    """Lokální test bez dokončeného Connect KYC (jen sk_test_ + env flag)."""
    if not bool(getattr(settings, "STRIPE_CONNECT_TEST_BYPASS", False)):
        return False
    key = (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    return key.startswith("sk_test_")


def player_payments_ready() -> bool:
    from core.billing import stripe_api_configured

    if not stripe_api_configured():
        return False
    connect = get_connect()
    if not connect.player_payments_enabled:
        return False
    if connect_test_bypass_enabled():
        return True
    return connect.is_ready


def public_base_url() -> str:
    """Absolutní báze URL instance pro Checkout return a e-maily."""
    explicit = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    if explicit:
        return explicit
    for origin in getattr(settings, "CSRF_TRUSTED_ORIGINS", None) or []:
        o = (origin or "").strip().rstrip("/")
        if o.startswith("http://") or o.startswith("https://"):
            return o
    hosts = getattr(settings, "ALLOWED_HOSTS", None) or []
    for host in hosts:
        h = (host or "").strip()
        if h and h not in ("*", ".localhost"):
            if h in ("127.0.0.1", "localhost") or h.startswith("localhost:"):
                return f"http://{h}" if "://" not in h else h
            return f"https://{h}"
    return "http://127.0.0.1:8000"


def player_currency() -> str:
    return (getattr(settings, "STRIPE_PLAYER_CURRENCY", "") or "czk").strip().lower()


def connect_country() -> str:
    return (getattr(settings, "STRIPE_CONNECT_COUNTRY", "") or "CZ").strip().upper()


def _stripe_client():
    from stripe import StripeClient
    from core.billing import stripe_api_configured

    if not stripe_api_configured():
        raise RuntimeError("STRIPE_SECRET_KEY is not set.")
    key = (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    return StripeClient(key)


def _cap_status(obj, *path) -> str:
    cur = obj
    for key in path:
        if cur is None:
            return ""
        cur = _get(cur, key)
    return str(_get(cur, "status") or "").strip().lower() if cur is not None else ""


def _requirements_submitted(account) -> bool:
    """True když účet nemá požadavky currently_due / past_due (v2 summary)."""
    req = _get(account, "requirements")
    if req is None:
        # v1
        return bool(_get(account, "details_submitted", False))
    summary = _get(req, "summary")
    deadline = _get(summary, "minimum_deadline") if summary is not None else None
    status = str(_get(deadline, "status") or "").strip().lower() if deadline else ""
    if status in ("currently_due", "past_due"):
        return False
    # Žádný deadline / eventually_due = onboarding dostatečně hotový pro test
    return True


def sync_connect_from_account(account) -> None:
    """Uloží stav Connect účtu z Stripe Account objektu (v1 i v2)."""
    if not account:
        return
    connect = get_connect()
    account_id = str(_get(account, "id") or "")
    if not account_id:
        return

    # v1 fields
    charges_v1 = _get(account, "charges_enabled", None)
    details_v1 = _get(account, "details_submitted", None)
    payouts_v1 = _get(account, "payouts_enabled", None)

    if charges_v1 is not None or details_v1 is not None or payouts_v1 is not None:
        connect.stripe_account_id = account_id
        connect.charges_enabled = bool(charges_v1)
        connect.details_submitted = bool(details_v1)
        connect.payouts_enabled = bool(payouts_v1)
    else:
        # v2: destination charges → recipient transfers; merchant card_payments volitelně
        card_ok = _cap_status(account, "configuration", "merchant", "capabilities", "card_payments") == "active"
        transfers_ok = (
            _cap_status(
                account,
                "configuration",
                "recipient",
                "capabilities",
                "stripe_balance",
                "stripe_transfers",
            )
            == "active"
        )
        connect.stripe_account_id = account_id
        # Destination charges: účet musí umět přijímat převody (nebo card_payments).
        connect.charges_enabled = bool(card_ok or transfers_ok)
        connect.details_submitted = _requirements_submitted(account)
        connect.payouts_enabled = bool(transfers_ok)

    connect.save(
        update_fields=[
            "stripe_account_id",
            "charges_enabled",
            "details_submitted",
            "payouts_enabled",
            "updated_at",
        ]
    )


def clear_connect_account(*, reason: str = "") -> None:
    """Smaže lokální odkaz na Connect účet (např. closed / špatný klíč)."""
    connect = get_connect()
    if not (connect.stripe_account_id or "").strip():
        return
    logger.warning(
        "Clearing ClubStripeConnect account_id=%s reason=%s",
        connect.stripe_account_id,
        reason or "manual",
    )
    connect.stripe_account_id = ""
    connect.charges_enabled = False
    connect.details_submitted = False
    connect.payouts_enabled = False
    connect.save(
        update_fields=[
            "stripe_account_id",
            "charges_enabled",
            "details_submitted",
            "payouts_enabled",
            "updated_at",
        ]
    )


def _account_is_usable(account) -> bool:
    if not account:
        return False
    if bool(_get(account, "closed")):
        return False
    return bool(_get(account, "id"))


def ensure_connect_account() -> str:
    """Vrátí stripe_account_id; vytvoří Express účet (Accounts v2) pokud ještě není.

    Uzavřený / nedostupný účet v DB se zahodí a vytvoří se nový.
    """
    from core.billing import stripe_api_configured
    from core.models import SystemNastaveni

    if not stripe_api_configured():
        raise RuntimeError("STRIPE_SECRET_KEY is not set.")

    connect = get_connect()
    existing = (connect.stripe_account_id or "").strip()
    client = _stripe_client()

    if existing:
        try:
            account = client.v2.core.accounts.retrieve(
                existing,
                {
                    "include": [
                        "configuration.merchant",
                        "configuration.recipient",
                        "identity",
                        "requirements",
                    ]
                },
            )
            if _account_is_usable(account):
                sync_connect_from_account(account)
                return existing
            clear_connect_account(reason="closed_or_unusable")
        except Exception as exc:
            msg = str(exc).lower()
            if any(
                x in msg
                for x in (
                    "permission denied",
                    "does not have access",
                    "account_invalid",
                    "forbidden",
                    "no such account",
                )
            ):
                clear_connect_account(reason=f"retrieve_failed:{exc}")
            else:
                raise

    nast = SystemNastaveni.load()
    display = (nast.nazev_klubu or "Klub").strip() or "Klub"
    contact = (nast.kontakt_email or nast.email_odesilatel or "").strip()
    # email_odesilatel může být "Jméno <mail@…>"
    if "<" in contact and ">" in contact:
        contact = contact.split("<", 1)[1].split(">", 1)[0].strip()
    if not contact or "@" not in contact:
        contact = "connect@example.com"

    country = connect_country()
    currency = player_currency()

    account = client.v2.core.accounts.create(
        {
            "display_name": display[:150],
            "contact_email": contact,
            "dashboard": "express",
            "identity": {"country": country},
            "defaults": {
                "currency": currency,
                # Express dashboard vyžaduje application (ne stripe) pro fees/losses.
                "responsibilities": {
                    "fees_collector": "application",
                    "losses_collector": "application",
                },
            },
            "configuration": {
                # Destination charges bez on_behalf_of → recipient
                "recipient": {
                    "capabilities": {
                        "stripe_balance": {
                            "stripe_transfers": {"requested": True},
                        }
                    }
                },
                # Do budoucna / některé země: merchant card payments
                "merchant": {
                    "capabilities": {
                        "card_payments": {"requested": True},
                    }
                },
            },
            "metadata": {
                "purpose": PLAYER_PAYMENT_PURPOSE,
                "instance": (getattr(settings, "INSTANCE_NAME", "") or "")[:200],
            },
            "include": [
                "configuration.merchant",
                "configuration.recipient",
                "identity",
                "defaults",
                "requirements",
            ],
        }
    )
    sync_connect_from_account(account)
    return str(account.id)


def create_account_onboarding_link(*, refresh_url: str, return_url: str) -> str:
    """Account Link (v2) pro Express onboarding → URL."""
    account_id = ensure_connect_account()
    client = _stripe_client()
    try:
        link = client.v2.core.account_links.create(
            {
                "account": account_id,
                "use_case": {
                    "type": "account_onboarding",
                    "account_onboarding": {
                        "configurations": ["recipient", "merchant"],
                        "refresh_url": refresh_url,
                        "return_url": return_url,
                    },
                },
            }
        )
    except Exception as exc:
        msg = str(exc).lower()
        if any(
            x in msg
            for x in ("permission denied", "does not have access", "forbidden", "closed")
        ):
            clear_connect_account(reason=f"account_link_failed:{exc}")
            account_id = ensure_connect_account()
            link = client.v2.core.account_links.create(
                {
                    "account": account_id,
                    "use_case": {
                        "type": "account_onboarding",
                        "account_onboarding": {
                            "configurations": ["recipient", "merchant"],
                            "refresh_url": refresh_url,
                            "return_url": return_url,
                        },
                    },
                }
            )
        else:
            raise
    url = _get(link, "url") or ""
    if not url:
        raise RuntimeError("Stripe AccountLink did not return a URL.")
    return str(url)


def refresh_connect_account_status() -> None:
    """Stáhne aktuální stav Connect účtu ze Stripe (v2, fallback v1)."""
    connect = get_connect()
    account_id = (connect.stripe_account_id or "").strip()
    if not account_id:
        return
    client = _stripe_client()
    try:
        account = client.v2.core.accounts.retrieve(
            account_id,
            {
                "include": [
                    "configuration.merchant",
                    "configuration.recipient",
                    "identity",
                    "requirements",
                ]
            },
        )
        if not _account_is_usable(account):
            clear_connect_account(reason="refresh_closed")
            return
        sync_connect_from_account(account)
        return
    except Exception as exc:
        msg = str(exc).lower()
        if any(
            x in msg
            for x in ("permission denied", "does not have access", "forbidden", "account_invalid")
        ):
            clear_connect_account(reason=f"refresh_failed:{exc}")
            return
        logger.exception("v2 account retrieve failed, trying v1 for %s", account_id)
    stripe = _stripe()
    account = stripe.Account.retrieve(account_id)
    sync_connect_from_account(account)


def amount_to_stripe_units(amount: Decimal) -> int:
    """Decimal Kč → nejmenší jednotka měny (haléře)."""
    quantized = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int((quantized * 100).to_integral_value(rounding=ROUND_HALF_UP))


def create_player_checkout_session(
    vyuctovani,
    *,
    success_url: str,
    cancel_url: str,
) -> str:
    """One-shot Checkout pro vyúčtování → URL. Uloží session na Vyuctovani."""
    from core.models import Vyuctovani

    if not isinstance(vyuctovani, Vyuctovani):
        raise TypeError("vyuctovani must be a Vyuctovani instance")

    amount = Decimal(vyuctovani.amount_due or 0)
    if amount <= 0:
        raise RuntimeError("Cannot create checkout for zero amount_due.")
    if not player_payments_ready():
        raise RuntimeError("Club Stripe Connect is not ready for player payments.")
    if vyuctovani.payment_status == Vyuctovani.PaymentStatus.PAID:
        raise RuntimeError("Vyúčtování is already paid.")

    connect = get_connect()
    stripe = _stripe()
    currency = player_currency()
    unit_amount = amount_to_stripe_units(amount)
    hrac = vyuctovani.hrac
    product_name = f"Vyúčtování – {hrac.cele_jmeno}"

    meta = {
        "purpose": PLAYER_PAYMENT_PURPOSE,
        "hrac_id": str(hrac.pk),
        "vyuctovani_id": str(vyuctovani.pk),
        "instance": (getattr(settings, "INSTANCE_NAME", "") or "")[:200],
    }
    payment_intent_data = {
        "metadata": {
            "purpose": PLAYER_PAYMENT_PURPOSE,
            "hrac_id": str(hrac.pk),
            "vyuctovani_id": str(vyuctovani.pk),
        },
    }
    # Bypass: platba na platformní test účet (bez Connect destination).
    if connect.is_ready and (connect.stripe_account_id or "").strip() and not connect_test_bypass_enabled():
        payment_intent_data["transfer_data"] = {
            "destination": connect.stripe_account_id.strip(),
        }
    elif connect_test_bypass_enabled():
        meta["connect_bypass"] = "1"

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": currency,
                    "unit_amount": unit_amount,
                    "product_data": {"name": product_name[:200]},
                },
                "quantity": 1,
            }
        ],
        payment_intent_data=payment_intent_data,
        metadata=meta,
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=f"vyuctovani:{vyuctovani.pk}"[:200],
    )

    url = session.url or ""
    vyuctovani.stripe_checkout_session_id = session.id or ""
    vyuctovani.stripe_checkout_url = url
    vyuctovani.payment_status = Vyuctovani.PaymentStatus.PENDING
    vyuctovani.save(
        update_fields=[
            "stripe_checkout_session_id",
            "stripe_checkout_url",
            "payment_status",
        ]
    )
    return url


def handle_player_checkout_completed(session) -> None:
    """Webhook: checkout.session.completed (mode=payment) → Transakce(PLATBA)."""
    from core.models import Hrac, Transakce, Vyuctovani

    meta = _meta(session)
    purpose = (meta.get("purpose") or "").strip()
    if purpose != PLAYER_PAYMENT_PURPOSE:
        return

    payment_status = (_get(session, "payment_status") or "").strip()
    if payment_status and payment_status != "paid":
        logger.info(
            "Ignoring player checkout session=%s payment_status=%s",
            _get(session, "id"),
            payment_status,
        )
        return

    payment_intent = _get(session, "payment_intent") or ""
    if hasattr(payment_intent, "id"):
        payment_intent = payment_intent.id
    payment_intent = str(payment_intent or "").strip()
    session_id = str(_get(session, "id") or "").strip()

    if payment_intent and Transakce.objects.filter(stripe_payment_intent_id=payment_intent).exists():
        logger.info("Player payment already recorded pi=%s", payment_intent)
        return

    vyuctovani_id = (meta.get("vyuctovani_id") or "").strip()
    hrac_id = (meta.get("hrac_id") or "").strip()

    vyuct = None
    if vyuctovani_id.isdigit():
        vyuct = Vyuctovani.objects.filter(pk=int(vyuctovani_id)).select_related("hrac").first()

    if vyuct is not None and vyuct.payment_status == Vyuctovani.PaymentStatus.PAID:
        logger.info("Vyuctovani already paid id=%s", vyuct.pk)
        return

    hrac = None
    if vyuct is not None:
        hrac = vyuct.hrac
    elif hrac_id.isdigit():
        hrac = Hrac.objects.filter(pk=int(hrac_id)).first()

    if hrac is None:
        logger.error(
            "Player payment webhook missing hrac (vyuctovani_id=%s hrac_id=%s session=%s)",
            vyuctovani_id,
            hrac_id,
            session_id,
        )
        return

    amount_total = _get(session, "amount_total")
    if amount_total is not None:
        castka = (Decimal(int(amount_total)) / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    elif vyuct is not None:
        castka = Decimal(vyuct.amount_due or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        logger.error("Player payment webhook missing amount session=%s", session_id)
        return

    if castka <= 0:
        logger.warning("Player payment zero amount session=%s", session_id)
        return

    # Fallback idempotence key when PI id missing (should be rare).
    idem_key = payment_intent or (f"cs:{session_id}" if session_id else "")
    if not idem_key:
        logger.error("Player payment missing payment_intent and session id")
        return

    popis = "Online platba (Stripe)"
    if vyuct is not None:
        popis = f"Online platba (Stripe) – vyúčtování #{vyuct.pk}"

    with transaction.atomic():
        if Transakce.objects.filter(stripe_payment_intent_id=idem_key).exists():
            return

        Transakce.objects.create(
            hrac=hrac,
            typ=Transakce.Typ.PLATBA,
            castka=castka,
            popis=popis,
            vytvoreno=timezone.now(),
            vyuctovani=vyuct,
            stripe_payment_intent_id=idem_key,
        )

        if vyuct is not None:
            update_fields = ["payment_status", "stripe_payment_intent_id"]
            vyuct.payment_status = Vyuctovani.PaymentStatus.PAID
            vyuct.stripe_payment_intent_id = idem_key
            if session_id and not vyuct.stripe_checkout_session_id:
                vyuct.stripe_checkout_session_id = session_id
                update_fields.append("stripe_checkout_session_id")
            vyuct.save(update_fields=update_fields)

    logger.info(
        "Recorded player PLATBA hrac_id=%s castka=%s pi=%s vyuctovani_id=%s",
        hrac.pk,
        castka,
        idem_key,
        getattr(vyuct, "pk", None),
    )


def maybe_attach_checkout(vyuctovani) -> str:
    """Vytvoří (vždy čerstvou) Checkout Session pokud dává smysl. Vrátí URL nebo ''."""
    from django.urls import reverse

    from core.models import Vyuctovani

    if not isinstance(vyuctovani, Vyuctovani):
        return ""
    amount = Decimal(vyuctovani.amount_due or 0)
    if amount <= 0:
        return ""
    if vyuctovani.payment_status == Vyuctovani.PaymentStatus.PAID:
        return ""
    if not player_payments_ready():
        return ""
    try:
        base = public_base_url()
        # Stripe Checkout Session expiruje (~24 h) → vždy nová session.
        return create_player_checkout_session(
            vyuctovani,
            success_url=f"{base}{reverse('payment_success')}",
            cancel_url=f"{base}{reverse('payment_cancelled')}",
        )
    except Exception:
        logger.exception(
            "Failed to create player checkout for vyuctovani_id=%s",
            getattr(vyuctovani, "pk", None),
        )
        return ""


def is_player_payment_event(event) -> bool:
    etype = event["type"] if isinstance(event, dict) else event.type
    if etype == "account.updated":
        return True
    if etype != "checkout.session.completed":
        return False
    data = event["data"]["object"] if isinstance(event, dict) else event.data.object
    meta = _meta(data)
    return (meta.get("purpose") or "").strip() == PLAYER_PAYMENT_PURPOSE


def handle_stripe_event(event) -> bool:
    """Zpracuje player-payment eventy. True = obslouženo (SaaS handler přeskočit)."""
    if not is_player_payment_event(event):
        return False

    etype = event["type"] if isinstance(event, dict) else event.type
    data = event["data"]["object"] if isinstance(event, dict) else event.data.object

    if etype == "account.updated":
        account_id = str(_get(data, "id") or "")
        connect = get_connect()
        known = (connect.stripe_account_id or "").strip()
        if known and account_id and known != account_id:
            return True
        if not known:
            # Bez lokálního účtu ber jen Connect účty vytvořené touto appkou.
            meta = _meta(data)
            if (meta.get("purpose") or "").strip() != PLAYER_PAYMENT_PURPOSE:
                return True
            instance = (getattr(settings, "INSTANCE_NAME", "") or "").strip()
            meta_instance = (meta.get("instance") or "").strip()
            if instance and meta_instance and instance != meta_instance:
                return True
        sync_connect_from_account(data)
        return True

    if etype == "checkout.session.completed":
        handle_player_checkout_completed(data)
        return True

    return False
