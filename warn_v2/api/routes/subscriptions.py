"""Routes: /api/subscriptions — email-alert signup, double opt-in, and management.

POST creates an unconfirmed subscription and emails a confirmation link;
GET /confirm and /unsubscribe are the links in that email (and in every digest),
so they return a small self-contained HTML page rather than JSON.

The /manage endpoints back the alert-management page. They authenticate one of
two ways (see ``resolve_subscriber``): a ``manage_token`` from an emailed link,
or a logged-in session whose email is verified — so anonymous subscribers and
account holders both get to the same list without a second implementation.
"""
from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_cookie_user, get_db
from warn_v2.api.pages import page as _page
from warn_v2.api.seo import site_base_url
from warn_v2.companies.naics import SECTOR_NAME, sector_for_code, subsector_name
from warn_v2.db.models import Subscription, User
from warn_v2.notifications.digest import describe_scope, manage_url
from warn_v2.notifications.email import EmailNotConfigured, send_email
from warn_v2.notifications.templates import FONT, button, render_shell
from warn_v2.states import is_valid_state

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

CLOSURE_CATEGORIES = ("Closure", "Layoff", "Non-WARN")
FREQUENCIES = ("daily", "weekly")
# Plenty for a newsroom watching several states, low enough that the signup form
# can't be used to pump mail at one address.
MAX_PER_EMAIL = 20
# Above the largest layoff ever filed — a threshold past this is a typo, and
# would silently match nothing.
MAX_MIN_LAYOFFS = 100_000

# The one answer every signup gets — new alert, duplicate, or already confirmed.
# Varying it would tell a stranger whether an address is subscribed.
_PENDING = {"status": "pending", "message": "Check your email to confirm the subscription."}

# The filter fields a caller may set, in one place: the create body, the update
# body and the output schema all derive from this list.
FILTER_FIELDS = (
    "state",
    "industry",
    "subsector",
    "employer_query",
    "min_layoffs",
    "closure_category",
)


def _normalize_email(value: str) -> str:
    """Lowercase and sanity-check an address; raises for anything unusable."""
    value = value.strip().lower()
    if not _EMAIL_RE.match(value) or len(value) > 320:
        raise ValueError("invalid email")
    return value


class AlertFilters(BaseModel):
    """The search criteria of one alert. Null/omitted means "no constraint"."""

    state: str | None = None
    industry: str | None = None
    subsector: str | None = None
    employer_query: str | None = None
    min_layoffs: int | None = Field(None, ge=1, le=MAX_MIN_LAYOFFS)
    closure_category: str | None = None
    frequency: str = "daily"

    @field_validator("state")
    @classmethod
    def _valid_state(cls, v: str | None) -> str | None:
        if not v:
            return None
        if not is_valid_state(v):
            raise ValueError("unknown state")
        return v.upper()

    @field_validator("industry")
    @classmethod
    def _valid_industry(cls, v: str | None) -> str | None:
        if not v:
            return None
        if v not in SECTOR_NAME:
            raise ValueError("unknown NAICS sector")
        return v

    @field_validator("subsector")
    @classmethod
    def _valid_subsector(cls, v: str | None) -> str | None:
        if not v:
            return None
        if subsector_name(v) is None:
            raise ValueError("unknown NAICS subsector")
        return v

    @field_validator("employer_query")
    @classmethod
    def _clean_employer(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if not v:
            return None
        if len(v) > 256:
            raise ValueError("employer query too long")
        return v

    @field_validator("closure_category")
    @classmethod
    def _valid_category(cls, v: str | None) -> str | None:
        if not v:
            return None
        if v not in CLOSURE_CATEGORIES:
            raise ValueError("unknown closure category")
        return v

    @field_validator("frequency")
    @classmethod
    def _valid_frequency(cls, v: str) -> str:
        if v not in FREQUENCIES:
            raise ValueError("frequency must be daily or weekly")
        return v

    @model_validator(mode="after")
    def _sector_matches_subsector(self) -> AlertFilters:
        """Keep sector and subsector consistent (the subsector is authoritative).

        ``naics_filter`` lets a subsector win over its sector anyway; normalizing
        here means the stored row, the digest's scope label and the deep link all
        agree instead of quietly disagreeing.
        """
        if self.subsector:
            self.industry = sector_for_code(self.subsector)
        return self


class SubscriptionCreate(AlertFilters):
    email: str

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        return _normalize_email(v)


class ManageLinkRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        return _normalize_email(v)


class SubscriptionOut(BaseModel):
    """One alert as the management UI sees it. Never exposes the tokens."""

    id: int
    email: str
    state: str | None
    industry: str | None
    subsector: str | None
    employer_query: str | None
    min_layoffs: int | None
    closure_category: str | None
    frequency: str
    scope: str  # human label, identical to the one used in digest subjects
    confirmed: bool
    created_at: datetime | None
    last_notified_at: datetime | None


def _out(sub: Subscription) -> SubscriptionOut:
    return SubscriptionOut(
        id=sub.id,
        email=sub.email,
        state=sub.state,
        industry=sub.industry,
        subsector=sub.subsector,
        employer_query=sub.employer_query,
        min_layoffs=sub.min_layoffs,
        closure_category=sub.closure_category,
        frequency=sub.frequency,
        scope=describe_scope(sub),
        confirmed=sub.confirmed_at is not None,
        created_at=sub.created_at,
        last_notified_at=sub.last_notified_at,
    )


def _apply_filters(sub: Subscription, filters: AlertFilters) -> None:
    """Copy a validated filter set onto a subscription row (full replacement)."""
    for field in FILTER_FIELDS:
        setattr(sub, field, getattr(filters, field))
    sub.frequency = filters.frequency


def _matching(db: Session, email: str, filters: AlertFilters) -> Subscription | None:
    """An existing subscription for this address with the identical filter set."""
    stmt = select(Subscription).where(Subscription.email == email)
    for field in FILTER_FIELDS:
        stmt = stmt.where(getattr(Subscription, field) == getattr(filters, field))
    return db.scalars(stmt).first()


# --- emails ----------------------------------------------------------------

def _send_confirmation(sub: Subscription) -> None:
    base = site_base_url()
    confirm_url = f"{base}/api/subscriptions/confirm?token={sub.confirm_token}"
    scope = describe_scope(sub)
    html_body = render_shell(
        preheader="Confirm your email to start receiving WARN layoff alerts.",
        content=(
            f'<tr><td style="padding:24px 24px 8px;{FONT};font-size:15px;line-height:22px;'
            'color:#0f172a;">Confirm your email to start receiving WARN layoff '
            f"alerts for <strong>{escape(scope)}</strong>:</td></tr>"
            f'<tr><td align="center" style="padding:16px 24px 24px;">'
            f"{button(confirm_url, 'Confirm subscription')}</td></tr>"
        ),
        footer="If you didn't request this, ignore this message.",
        base=base,
    )
    send_email(
        sub.email,
        "Confirm your WARN Tracker alerts",
        f"Confirm your email to start receiving WARN layoff alerts for {scope}:\n\n"
        f"{confirm_url}\n\nIf you didn't request this, ignore this message.",
        html_body,
    )


def _send_manage_link(sub: Subscription, *, already_subscribed: bool = False) -> None:
    """Email the management link for an address.

    Doubles as the "you're already subscribed" reply to a duplicate signup, so a
    repeat submission never creates a second alert or a second confirmation link.
    """
    base = site_base_url()
    url = manage_url(sub, base)
    lead = (
        f"You're already subscribed to WARN Tracker alerts for {describe_scope(sub)}. "
        "Use the link below to change or remove your alerts:"
        if already_subscribed
        else "Use the link below to view, change or remove your WARN Tracker alerts:"
    )
    html_body = render_shell(
        preheader="Manage your WARN Tracker alerts.",
        content=(
            f'<tr><td style="padding:24px 24px 8px;{FONT};font-size:15px;line-height:22px;'
            f'color:#0f172a;">{escape(lead)}</td></tr>'
            f'<tr><td align="center" style="padding:16px 24px 24px;">'
            f"{button(url, 'Manage my alerts')}</td></tr>"
        ),
        footer="If you didn't request this, ignore this message.",
        base=base,
    )
    send_email(
        sub.email,
        "Your WARN Tracker alerts",
        f"{lead}\n\n{url}\n\nIf you didn't request this, ignore this message.",
        html_body,
    )


# --- signup + double opt-in ------------------------------------------------

@router.post("")
def create_subscription(
    payload: SubscriptionCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_cookie_user),
) -> dict[str, str]:
    """Create an alert and email its confirmation link.

    The response body is identical whether the alert is new, a duplicate, or
    already confirmed — it must not reveal whether an address is subscribed.
    """
    existing = _matching(db, payload.email, payload)
    if existing is not None:
        # Don't stack duplicates: nudge the subscriber to the copy they have.
        try:
            if existing.confirmed_at is None:
                _send_confirmation(existing)
            else:
                _send_manage_link(existing, already_subscribed=True)
        except EmailNotConfigured as exc:
            raise HTTPException(status_code=503, detail="Email not configured") from exc
        return _PENDING

    count = db.scalar(
        select(func.count()).select_from(Subscription).where(Subscription.email == payload.email)
    )
    if (count or 0) >= MAX_PER_EMAIL:
        raise HTTPException(
            status_code=400,
            detail=f"This address already has {MAX_PER_EMAIL} alerts; remove one first.",
        )

    sub = Subscription(
        email=payload.email,
        confirm_token=secrets.token_urlsafe(24),
        unsubscribe_token=secrets.token_urlsafe(24),
        manage_token=secrets.token_urlsafe(24),
        user_id=_claimable_user_id(user, payload.email),
    )
    _apply_filters(sub, payload)
    db.add(sub)
    db.flush()

    try:
        _send_confirmation(sub)
    except EmailNotConfigured as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Email not configured") from exc

    db.commit()
    return _PENDING


def _claimable_user_id(user: User | None, email: str) -> int | None:
    """The account id to attach, when a verified user owns this address.

    Unverified accounts are excluded: anyone can sign up with someone else's
    address, and attaching it would show them that address's alerts.
    """
    if user is None or user.email_verified_at is None:
        return None
    return user.id if user.email.strip().lower() == email else None


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
    manage = manage_url(sub, site_base_url())
    return _page(
        "Subscription confirmed",
        "You're all set — you'll get an email when new matching WARN notices are filed.",
        extra_html=f"<p><a href='{manage}'>Manage your alerts</a></p>",
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


# --- management ------------------------------------------------------------

class Subscriber:
    """The address a /manage request is allowed to act on, and how it proved it."""

    def __init__(self, email: str, user: User | None) -> None:
        self.email = email
        self.user = user


def resolve_subscriber(
    token: str | None = Query(None, description="manage_token from an emailed link"),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_cookie_user),
) -> Subscriber:
    """Authenticate a management request by manage token or verified session.

    Session auth is cookie-only (``get_cookie_user``) so a leaked API key can't
    read or edit someone's alerts — the same rule the key routes follow.
    """
    if token:
        sub = db.scalar(select(Subscription).where(Subscription.manage_token == token))
        if sub is None:
            raise HTTPException(status_code=404, detail="This management link is no longer valid.")
        return Subscriber(sub.email, user)
    if user is not None and user.email_verified_at is not None:
        return Subscriber(user.email.strip().lower(), user)
    raise HTTPException(status_code=401, detail="Not authenticated")


def _owned(db: Session, sub_id: int, subscriber: Subscriber) -> Subscription:
    sub = db.get(Subscription, sub_id)
    # 404 (not 403) for another address's id: the caller shouldn't learn it exists.
    if sub is None or sub.email != subscriber.email:
        raise HTTPException(status_code=404, detail="Alert not found")
    return sub


@router.post("/manage-link")
def request_manage_link(
    payload: ManageLinkRequest, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Email a management link for an address, if it has any alerts.

    Answers identically for an address with no alerts — the response must not
    reveal whether someone is subscribed.
    """
    sub = db.scalars(select(Subscription).where(Subscription.email == payload.email)).first()
    if sub is not None:
        try:
            _send_manage_link(sub)
        except EmailNotConfigured as exc:
            raise HTTPException(status_code=503, detail="Email not configured") from exc
    return {
        "status": "sent",
        "message": "If that address has alerts, a management link is on its way.",
    }


@router.get("/manage")
def list_subscriptions(
    subscriber: Subscriber = Depends(resolve_subscriber), db: Session = Depends(get_db)
) -> list[SubscriptionOut]:
    """Every alert for the resolved address, newest first."""
    subs = list(
        db.scalars(
            select(Subscription)
            .where(Subscription.email == subscriber.email)
            .order_by(Subscription.created_at.desc(), Subscription.id.desc())
        )
    )
    # Adopt anonymous rows for the signed-in owner of the address, so alerts
    # created before they had an account show up on /account from now on.
    user = subscriber.user
    if user is not None and user.email_verified_at is not None:
        claimed = False
        for sub in subs:
            if sub.user_id is None and sub.email == user.email.strip().lower():
                sub.user_id = user.id
                claimed = True
        if claimed:
            db.commit()
    return [_out(s) for s in subs]


@router.put("/manage/{sub_id}")
def update_subscription(
    sub_id: int,
    payload: AlertFilters,
    subscriber: Subscriber = Depends(resolve_subscriber),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    """Replace an alert's search criteria (the body is the complete filter set)."""
    sub = _owned(db, sub_id, subscriber)
    _apply_filters(sub, payload)
    db.commit()
    return _out(sub)


@router.delete("/manage/{sub_id}")
def delete_subscription(
    sub_id: int,
    subscriber: Subscriber = Depends(resolve_subscriber),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    sub = _owned(db, sub_id, subscriber)
    db.delete(sub)
    db.commit()
    return {"status": "deleted"}


@router.post("/manage/{sub_id}/resend-confirmation")
def resend_confirmation(
    sub_id: int,
    subscriber: Subscriber = Depends(resolve_subscriber),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Re-send the opt-in link for an alert that was never confirmed."""
    sub = _owned(db, sub_id, subscriber)
    if sub.confirmed_at is not None:
        return {"status": "confirmed"}
    try:
        _send_confirmation(sub)
    except EmailNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Email not configured") from exc
    return {"status": "sent"}
