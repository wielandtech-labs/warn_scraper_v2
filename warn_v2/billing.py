"""Stripe billing seam.

Thin wrappers over the stripe SDK so routes (and tests) depend on these
functions rather than the SDK: tests monkeypatch create_checkout_session /
create_portal_session, and exercise verify_webhook against real computed
signatures.

Configured from the environment (SealedSecret in prod):

    STRIPE_SECRET_KEY      sk_test_... / sk_live_...
    STRIPE_WEBHOOK_SECRET  whsec_...
    STRIPE_PRICE_ID        price_...  (the single paid tier at launch)

Raises StripeNotConfigured when unset so routes can degrade to 503, mirroring
EmailNotConfigured.
"""
from __future__ import annotations

import os

import stripe

from warn_v2.db.models import User


class StripeNotConfigured(RuntimeError):
    """Raised when STRIPE_* env vars are missing so callers can degrade gracefully."""


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise StripeNotConfigured(f"{name} must be set")
    return value


def create_checkout_session(user: User, success_url: str, cancel_url: str) -> str:
    """Start a subscription Checkout for ``user``; returns the redirect URL."""
    session = stripe.checkout.Session.create(
        api_key=_env("STRIPE_SECRET_KEY"),
        mode="subscription",
        line_items=[{"price": _env("STRIPE_PRICE_ID"), "quantity": 1}],
        # client_reference_id survives to checkout.session.completed — it is
        # how the webhook maps the Stripe customer back to our user row.
        client_reference_id=str(user.id),
        customer_email=user.email,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return session.url


def create_portal_session(customer_id: str, return_url: str) -> str:
    """Open the Stripe customer portal (manage/cancel subscription)."""
    session = stripe.billing_portal.Session.create(
        api_key=_env("STRIPE_SECRET_KEY"),
        customer=customer_id,
        return_url=return_url,
    )
    return session.url


def verify_webhook(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify a webhook signature and parse the event; raises on any mismatch."""
    return stripe.Webhook.construct_event(payload, sig_header, _env("STRIPE_WEBHOOK_SECRET"))
