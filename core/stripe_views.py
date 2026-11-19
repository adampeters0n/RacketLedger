"""Stripe webhook endpoint (CSRF-exempt, signature-verified)."""

from __future__ import annotations

import logging

from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    from core.billing import construct_webhook_event, handle_stripe_event, stripe_webhook_configured

    if not stripe_webhook_configured():
        return HttpResponseForbidden("Stripe webhook is not configured.")

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    if not sig_header:
        return HttpResponseBadRequest("Missing Stripe-Signature header.")

    try:
        event = construct_webhook_event(payload, sig_header)
    except ValueError:
        logger.warning("Stripe webhook invalid payload")
        return HttpResponseBadRequest("Invalid payload.")
    except Exception as exc:
        # stripe.error.SignatureVerificationError
        logger.warning("Stripe webhook signature error: %s", exc)
        return HttpResponseBadRequest("Invalid signature.")

    try:
        handle_stripe_event(event)
    except Exception:
        logger.exception("Stripe webhook handler failed")
        return HttpResponse(status=500)

    return HttpResponse(status=200)
