"""Routes: /api/billing — Stripe checkout, customer portal, and webhook.

Checkout/portal authenticate via the session cookie only (like key
management). The webhook authenticates via Stripe's signature instead and
must never sit behind the rate limiter or require a key.

Role rules: the webhook only ever moves users between 'free' and 'paid'.
'admin' and 'enterprise' are provisioned manually and are never demoted by a
billing event.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2 import billing
from warn_v2.api.deps import get_cookie_user, get_db
from warn_v2.api.seo import site_base_url
from warn_v2.db.models import User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

# Roles the webhook is allowed to rewrite. Everything else is hands-off.
_BILLING_MANAGED_ROLES = ("free", "paid")


def _require_session(user: User | None = Depends(get_cookie_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.post("/checkout")
def checkout(user: User = Depends(_require_session)) -> dict[str, str]:
    if user.email_verified_at is None:
        raise HTTPException(status_code=403, detail="Verify your email first")
    if user.role != "free":
        raise HTTPException(status_code=400, detail="Account already has a plan")
    base = site_base_url()
    try:
        url = billing.create_checkout_session(
            user,
            success_url=f"{base}/account?checkout=success",
            cancel_url=f"{base}/account?checkout=cancelled",
        )
    except billing.StripeNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Billing not configured") from exc
    return {"url": url}


@router.post("/portal")
def portal(user: User = Depends(_require_session)) -> dict[str, str]:
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account")
    try:
        url = billing.create_portal_session(
            user.stripe_customer_id, return_url=f"{site_base_url()}/account"
        )
    except billing.StripeNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Billing not configured") from exc
    return {"url": url}


def _set_role(db: Session, user: User, role: str, event_id: str) -> None:
    if user.role not in _BILLING_MANAGED_ROLES:
        log.info("billing event %s: leaving %s role %r alone", event_id, user.email, user.role)
        return
    if user.role != role:
        log.info("billing event %s: %s role %r -> %r", event_id, user.email, user.role, role)
        user.role = role


def _user_by_customer(db: Session, customer_id: str | None) -> User | None:
    if not customer_id:
        return None
    return db.scalar(select(User).where(User.stripe_customer_id == customer_id))


def _get(obj, key: str, default=None):
    """StripeObject supports [] but not dict.get (stripe v15)."""
    try:
        return obj[key]
    except KeyError:
        return default


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = billing.verify_webhook(payload, sig)
    except billing.StripeNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Billing not configured") from exc
    except Exception as exc:  # bad signature / malformed payload
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from exc

    obj = event["data"]["object"]
    if event["type"] == "checkout.session.completed":
        ref = _get(obj, "client_reference_id")
        user = db.get(User, int(ref)) if ref else None
        if user is None:
            log.warning("billing event %s: unknown client_reference_id %r", event["id"], ref)
        else:
            user.stripe_customer_id = _get(obj, "customer") or user.stripe_customer_id
            _set_role(db, user, "paid", event["id"])
    elif event["type"] == "customer.subscription.updated":
        user = _user_by_customer(db, _get(obj, "customer"))
        if user is not None:
            active = _get(obj, "status") in ("active", "trialing")
            _set_role(db, user, "paid" if active else "free", event["id"])
    elif event["type"] == "customer.subscription.deleted":
        user = _user_by_customer(db, _get(obj, "customer"))
        if user is not None:
            _set_role(db, user, "free", event["id"])
    else:
        log.debug("billing event %s: ignoring type %s", event["id"], event["type"])

    db.commit()  # idempotent role-sets; Stripe retries on non-2xx
    return {"status": "ok"}
