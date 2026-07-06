"""Routes: /api/subscriptions — email-alert signup with double opt-in.

POST creates an unconfirmed subscription and emails a confirmation link;
GET /confirm and /unsubscribe are the links in that email (and in every digest),
so they return a small self-contained HTML page rather than JSON.
"""
from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_db
from warn_v2.api.pages import page as _page
from warn_v2.api.seo import site_base_url
from warn_v2.db.models import Subscription
from warn_v2.notifications.email import EmailNotConfigured, send_email
from warn_v2.notifications.templates import FONT, button, render_shell

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SubscriptionCreate(BaseModel):
    email: str
    state: str | None = None
    industry: str | None = None
    employer_query: str | None = None

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v) or len(v) > 320:
            raise ValueError("invalid email")
        return v


@router.post("")
def create_subscription(
    payload: SubscriptionCreate, db: Session = Depends(get_db)
) -> dict[str, str]:
    sub = Subscription(
        email=payload.email,
        state=payload.state.upper() if payload.state else None,
        industry=payload.industry or None,
        employer_query=(payload.employer_query or "").strip() or None,
        confirm_token=secrets.token_urlsafe(24),
        unsubscribe_token=secrets.token_urlsafe(24),
    )
    db.add(sub)
    db.flush()

    base = site_base_url()
    confirm_url = f"{base}/api/subscriptions/confirm?token={sub.confirm_token}"
    html_body = render_shell(
        preheader="Confirm your email to start receiving WARN layoff alerts.",
        content=(
            f'<tr><td style="padding:24px 24px 8px;{FONT};font-size:15px;line-height:22px;'
            'color:#0f172a;">Confirm your email to start receiving WARN layoff '
            "alerts:</td></tr>"
            f'<tr><td align="center" style="padding:16px 24px 24px;">'
            f"{button(confirm_url, 'Confirm subscription')}</td></tr>"
        ),
        footer="If you didn't request this, ignore this message.",
        base=base,
    )
    try:
        send_email(
            sub.email,
            "Confirm your WARN Tracker alerts",
            f"Confirm your email to start receiving WARN layoff alerts:\n\n{confirm_url}\n\n"
            "If you didn't request this, ignore this message.",
            html_body,
        )
    except EmailNotConfigured as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Email not configured") from exc

    db.commit()
    return {"status": "pending", "message": "Check your email to confirm the subscription."}


@router.get("/confirm")
def confirm_subscription(token: str = Query(...), db: Session = Depends(get_db)) -> HTMLResponse:
    sub = db.scalar(select(Subscription).where(Subscription.confirm_token == token))
    if sub is None:
        return _page("Link not found", "This confirmation link is invalid or has expired.")
    if sub.confirmed_at is None:
        now = datetime.now(UTC)
        sub.confirmed_at = now
        sub.last_notified_at = now  # only notify on notices found after confirming
        db.commit()
    return _page(
        "Subscription confirmed",
        "You're all set — you'll get an email when new matching WARN notices are filed.",
    )


def _delete_by_token(db: Session, token: str) -> None:
    sub = db.scalar(select(Subscription).where(Subscription.unsubscribe_token == token))
    if sub is not None:
        db.delete(sub)
        db.commit()


@router.get("/unsubscribe")
def unsubscribe(token: str = Query(...), db: Session = Depends(get_db)) -> HTMLResponse:
    _delete_by_token(db, token)
    # Always show success so the link doesn't leak which tokens are valid.
    return _page("Unsubscribed", "You won't receive any further WARN Tracker alerts.")


@router.post("/unsubscribe")
def unsubscribe_one_click(
    token: str = Query(...), db: Session = Depends(get_db)
) -> dict[str, str]:
    """RFC 8058 one-click unsubscribe: mail providers POST to the header URL."""
    _delete_by_token(db, token)
    return {"status": "unsubscribed"}
