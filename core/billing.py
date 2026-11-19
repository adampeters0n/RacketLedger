"""Předplatné za TenisSystém (Stripe) — oddělené od klubového vyúčtování hráčů.

Tok:
- platforma nastaví STRIPE_SECRET_KEY + STRIPE_PRICE_ID (+ webhook secret)
- klub v Nastavení klikne Checkout → zaplatí
- webhook uloží customer/subscription status do SoftwareBilling
- billing_active() podle stavu (ops může stále vynutit BILLING_ACTIVE=0)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = frozenset({"active", "trialing"})
INACTIVE_STATUSES = frozenset(
    {
        "past_due",
        "canceled",
        "unpaid",
        "incomplete",
        "incomplete_expired",
        "paused",
    }
)


def _stripe():
    import stripe

    key = (getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY is not set.")
    stripe.api_key = key
    return stripe


def stripe_api_configured() -> bool:
    return bool((getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip())


def stripe_checkout_configured() -> bool:
    """Checkout potřebuje secret key + Price ID."""
    price = (getattr(settings, "STRIPE_PRICE_ID", "") or "").strip()
    return stripe_api_configured() and bool(price)


def stripe_webhook_configured() -> bool:
    secret = (getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or "").strip()
    return stripe_api_configured() and bool(secret)


def get_software_billing():
    from core.models import SoftwareBilling

    return SoftwareBilling.load()


def resolve_customer_id(billing=None) -> str:
    """Customer z DB, jinak seed z env (ruční napojení starší instance)."""
    if billing is None:
        billing = get_software_billing()
    db_id = (billing.stripe_customer_id or "").strip()
    if db_id:
        return db_id
    env_id = (getattr(settings, "STRIPE_CUSTOMER_ID", "") or "").strip()
    if env_id:
        billing.stripe_customer_id = env_id
        billing.save(update_fields=["stripe_customer_id", "updated_at"])
        return env_id
    return ""


def stripe_configured() -> bool:
    """Portal / napojený customer: secret + customer ID (DB nebo env)."""
    return stripe_api_configured() and bool(resolve_customer_id())


def subscription_status(billing=None) -> str:
    if billing is None:
        billing = get_software_billing()
    return (billing.stripe_subscription_status or "").strip().lower()


def billing_active() -> bool:
    """False = instance read-only / suspend.

    Priorita:
    1) BILLING_ACTIVE=0 vždy zamkne (ops kill-switch)
    2) známý Stripe status active/trialing → otevřeno
    3) známý neaktivní status → zamčeno
    4) ještě žádný status:
       - STRIPE_REQUIRE_SUBSCRIPTION=1 + Checkout připraven → zamčeno (musí zaplatit)
       - jinak BILLING_ACTIVE (default True = grace při provisioningu)
    """
    if not bool(getattr(settings, "BILLING_ACTIVE", True)):
        return False

    status = subscription_status()
    if status in ACTIVE_STATUSES:
        return True
    if status in INACTIVE_STATUSES:
        return False

    require = bool(getattr(settings, "STRIPE_REQUIRE_SUBSCRIPTION", False))
    if require and stripe_checkout_configured():
        return False

    return True


def apply_subscription_snapshot(
    *,
    customer_id: str = "",
    subscription_id: str = "",
    status: str = "",
    price_id: str = "",
    current_period_end=None,
) -> None:
    billing = get_software_billing()
    changed = False

    if customer_id and billing.stripe_customer_id != customer_id:
        billing.stripe_customer_id = customer_id
        changed = True
    if subscription_id and billing.stripe_subscription_id != subscription_id:
        billing.stripe_subscription_id = subscription_id
        changed = True
    if status:
        norm = status.strip().lower()
        if billing.stripe_subscription_status != norm:
            billing.stripe_subscription_status = norm
            changed = True
    if price_id and billing.stripe_price_id != price_id:
        billing.stripe_price_id = price_id
        changed = True
    if current_period_end is not None and billing.current_period_end != current_period_end:
        billing.current_period_end = current_period_end
        changed = True

    if changed:
        billing.save()


def _period_end_from_subscription(sub) -> datetime | None:
    raw = getattr(sub, "current_period_end", None)
    if raw is None and isinstance(sub, dict):
        raw = sub.get("current_period_end")
    if not raw:
        return None
    try:
        dt = datetime.fromtimestamp(int(raw), tz=dt_timezone.utc)
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, timezone=dt_timezone.utc)
        return dt
    except (TypeError, ValueError, OSError):
        return None


def _price_id_from_subscription(sub) -> str:
    try:
        items = sub["items"]["data"] if isinstance(sub, dict) else sub["items"]["data"]
        if not items:
            return ""
        price = items[0].get("price") if isinstance(items[0], dict) else items[0].price
        if isinstance(price, str):
            return price
        return getattr(price, "id", None) or (price.get("id") if isinstance(price, dict) else "") or ""
    except Exception:
        return ""


def sync_from_subscription_object(sub) -> None:
    if not sub:
        return
    if isinstance(sub, str):
        stripe = _stripe()
        sub = stripe.Subscription.retrieve(sub)

    customer = sub.get("customer") if isinstance(sub, dict) else sub.customer
    if hasattr(customer, "id"):
        customer = customer.id
    sub_id = sub.get("id") if isinstance(sub, dict) else sub.id
    status = sub.get("status") if isinstance(sub, dict) else sub.status

    apply_subscription_snapshot(
        customer_id=str(customer or ""),
        subscription_id=str(sub_id or ""),
        status=str(status or ""),
        price_id=_price_id_from_subscription(sub),
        current_period_end=_period_end_from_subscription(sub),
    )


def create_checkout_session(*, success_url: str, cancel_url: str, customer_email: str = "") -> str:
    """Stripe Checkout (subscription) → URL pro redirect."""
    if not stripe_checkout_configured():
        raise RuntimeError("Stripe Checkout is not configured (STRIPE_SECRET_KEY / STRIPE_PRICE_ID).")

    stripe = _stripe()
    billing = get_software_billing()
    customer_id = resolve_customer_id(billing)
    price_id = (getattr(settings, "STRIPE_PRICE_ID", "") or "").strip()

    params: dict = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "allow_promotion_codes": True,
        "client_reference_id": (getattr(settings, "INSTANCE_NAME", "") or "")[:200],
    }
    if customer_id:
        params["customer"] = customer_id
    elif customer_email:
        params["customer_email"] = customer_email

    session = stripe.checkout.Session.create(**params)
    return session.url


def create_billing_portal_url(*, return_url: str) -> str:
    """Stripe Customer Portal session → URL."""
    customer_id = resolve_customer_id()
    if not stripe_api_configured() or not customer_id:
        raise RuntimeError("Stripe is not configured (STRIPE_SECRET_KEY / customer id).")

    stripe = _stripe()
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session.url


def construct_webhook_event(payload: bytes, sig_header: str):
    if not stripe_webhook_configured():
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not set.")
    stripe = _stripe()
    return stripe.Webhook.construct_event(
        payload,
        sig_header,
        settings.STRIPE_WEBHOOK_SECRET,
    )


def handle_stripe_event(event) -> None:
    """Zpracuje relevantní Stripe eventy (idempotentní snapshot).

    Nejdřív předá event player-payment handleru (Connect / Checkout payment);
    teprve pak SaaS předplatné.
    """
    from core import player_payments

    if player_payments.handle_stripe_event(event):
        return

    etype = event["type"] if isinstance(event, dict) else event.type
    data = event["data"]["object"] if isinstance(event, dict) else event.data.object

    if etype == "checkout.session.completed":
        mode = data.get("mode") if isinstance(data, dict) else getattr(data, "mode", None)
        if mode and mode != "subscription":
            return
        customer = data.get("customer") if isinstance(data, dict) else data.customer
        subscription = data.get("subscription") if isinstance(data, dict) else data.subscription
        if customer:
            apply_subscription_snapshot(customer_id=str(customer))
        if subscription:
            sync_from_subscription_object(subscription)
        elif customer:
            # Checkout hotový, subscription někdy dorazí až subscription.updated
            apply_subscription_snapshot(status="active", customer_id=str(customer))
        return

    if etype in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        sync_from_subscription_object(data)
        return

    if etype == "invoice.paid":
        sub = data.get("subscription") if isinstance(data, dict) else getattr(data, "subscription", None)
        if sub:
            sync_from_subscription_object(sub)
        return

    if etype == "invoice.payment_failed":
        sub = data.get("subscription") if isinstance(data, dict) else getattr(data, "subscription", None)
        customer = data.get("customer") if isinstance(data, dict) else getattr(data, "customer", None)
        if sub:
            sync_from_subscription_object(sub)
        elif customer:
            apply_subscription_snapshot(customer_id=str(customer), status="past_due")
        return

    logger.debug("Ignoring Stripe event type=%s", etype)
