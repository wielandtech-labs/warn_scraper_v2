"""Auth endpoints: cookie-session login plus self-signup and password reset.

Self-signup is gated behind SIGNUP_ENABLED=1 so this code can ship dark and be
switched on via chart values once the frontend pages exist.
"""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from warn_v2 import auth
from warn_v2.api.deps import get_current_user, get_db
from warn_v2.api.pages import page as _page
from warn_v2.api.ratelimit import SlidingWindowLimiter
from warn_v2.api.seo import site_base_url
from warn_v2.db.models import User, UserSession
from warn_v2.notifications.email import EmailNotConfigured, send_email
from warn_v2.notifications.templates import FONT, button, render_shell

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Signup and forgot-password send email on anonymous input — keep them on a
# tight per-IP budget, independent of the general API limiter.
_EMAIL_ENDPOINT_LIMIT = 5  # per hour per IP
_email_limiter = SlidingWindowLimiter(window=3600)


def _signup_enabled() -> bool:
    return os.getenv("SIGNUP_ENABLED", "0") == "1"


def _guard_email_endpoint(request: Request) -> None:
    if not _signup_enabled():
        raise HTTPException(status_code=503, detail="Signup is not enabled")
    ip = request.client.host if request.client else "unknown"
    allowed, _, retry_after = _email_limiter.hit(f"signup:{ip}", _EMAIL_ENDPOINT_LIMIT)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts; try again later.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


class LoginIn(BaseModel):
    # Plain str, not EmailStr — EmailStr would pull in the email-validator dep
    # for no gain on admin-provisioned accounts. Length bounds cap the only
    # body-accepting endpoint (argon2 hashes the full password otherwise).
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class MeOut(BaseModel):
    email: str
    role: str


def _cookie_secure() -> bool:
    # Secure by default (prod is HTTPS; browsers trust localhost in dev).
    # AUTH_COOKIE_SECURE=0 is a plain-HTTP escape hatch only.
    return os.getenv("AUTH_COOKIE_SECURE", "1") != "0"


@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> MeOut:
    result = auth.authenticate(db, body.email, body.password)
    if result is None:
        # Same message for unknown email and wrong password — no enumeration.
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user, token = result
    db.commit()  # get_db never commits; persist the session row explicitly
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        max_age=int(auth.SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
    )
    return MeOut(email=user.email, role=user.role)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    token = request.cookies.get(auth.COOKIE_NAME)
    if token:
        auth.end_session(db, token)
        db.commit()
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/me")
def me(user: User | None = Depends(get_current_user)) -> MeOut:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return MeOut(email=user.email, role=user.role)


# ---------------------------------------------------------------------------
# Self-signup + email verification + password reset (SIGNUP_ENABLED=1)
# ---------------------------------------------------------------------------

class SignupIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=auth.MIN_PASSWORD_LEN, max_length=1024)


class EmailIn(BaseModel):
    email: str = Field(max_length=320)


class ResetIn(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=auth.MIN_PASSWORD_LEN, max_length=1024)


_PENDING_MSG = "If that address is new, a verification email is on its way."
_RESET_MSG = "If that address has an account, a reset email is on its way."


def _send_link_email(to: str, subject: str, intro: str, url: str, cta: str) -> None:
    base = site_base_url()
    html_body = render_shell(
        preheader=intro,
        content=(
            f'<tr><td style="padding:24px 24px 8px;{FONT};font-size:15px;line-height:22px;'
            f'color:#0f172a;">{escape(intro)}</td></tr>'
            f'<tr><td align="center" style="padding:16px 24px 24px;">{button(url, cta)}</td></tr>'
        ),
        footer="If you didn't request this, ignore this message.",
        base=base,
    )
    send_email(
        to,
        subject,
        f"{intro}\n\n{url}\n\nIf you didn't request this, ignore this message.",
        html_body,
    )


@router.post("/signup")
def signup(body: SignupIn, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    _guard_email_endpoint(request)
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Invalid email address")

    # Existing address: return the same 200 without sending — no enumeration.
    if db.scalar(select(User).where(User.email == email)) is not None:
        return {"status": "pending", "message": _PENDING_MSG}

    user = User(email=email, password_hash=auth.hash_password(body.password), role="free")
    db.add(user)
    db.flush()
    token = auth.issue_token(db, user, "verify")
    try:
        _send_link_email(
            email,
            "Verify your WARN Tracker account",
            "Confirm your email to activate your WARN Tracker API account:",
            f"{site_base_url()}/api/auth/verify?token={token}",
            "Verify email",
        )
    except EmailNotConfigured as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Email not configured") from exc
    db.commit()
    return {"status": "pending", "message": _PENDING_MSG}


@router.get("/verify")
def verify_email(token: str = Query(...), db: Session = Depends(get_db)) -> HTMLResponse:
    user = auth.consume_token(db, token, "verify")
    if user is None:
        db.commit()  # consume_token may have deleted an expired row
        return _page("Link not valid", "This verification link is invalid or has expired.")
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    db.commit()
    return _page(
        "Email verified",
        "Your account is active — you can now sign in and create API keys.",
    )


@router.post("/forgot")
def forgot_password(
    body: EmailIn, request: Request, db: Session = Depends(get_db)
) -> dict[str, str]:
    _guard_email_endpoint(request)
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        return {"status": "pending", "message": _RESET_MSG}  # no enumeration

    token = auth.issue_token(db, user, "reset")
    try:
        _send_link_email(
            email,
            "Reset your WARN Tracker password",
            "Use the link below to choose a new WARN Tracker password (valid for 1 hour):",
            f"{site_base_url()}/api/auth/reset-page?token={token}",
            "Reset password",
        )
    except EmailNotConfigured as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Email not configured") from exc
    db.commit()
    return {"status": "pending", "message": _RESET_MSG}


@router.get("/reset-page")
def reset_page(token: str = Query(...)) -> HTMLResponse:
    """Self-contained password form for the emailed reset link.

    Works without the SPA: an inline script POSTs JSON to /api/auth/reset.
    The token isn't validated here — the POST is the single point of truth.
    """
    form = f"""
<form id="f" style="margin:1rem 0">
  <input type="hidden" id="token" value="{escape(token)}">
  <label>New password (min {auth.MIN_PASSWORD_LEN} characters)<br>
    <input type="password" id="pw" minlength="{auth.MIN_PASSWORD_LEN}" required
           style="width:100%;padding:.5rem;margin:.5rem 0"></label>
  <button type="submit" style="padding:.5rem 1rem">Set new password</button>
  <p id="msg"></p>
</form>
<script>
document.getElementById('f').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const msg = document.getElementById('msg');
  const resp = await fetch('/api/auth/reset', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{
      token: document.getElementById('token').value,
      password: document.getElementById('pw').value,
    }}),
  }});
  msg.textContent = resp.ok
    ? 'Password updated - you can sign in now.'
    : (await resp.json()).detail || 'Something went wrong.';
}});
</script>"""
    return _page("Reset your password", "Choose a new password for your account.", form)


@router.post("/reset")
def reset_password(body: ResetIn, db: Session = Depends(get_db)) -> dict[str, str]:
    user = auth.consume_token(db, body.token, "reset")
    if user is None:
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user.password_hash = auth.hash_password(body.password)
    # A reset proves control of the mailbox — treat the email as verified and
    # revoke every outstanding session (compromise response, mirrors the CLI).
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.commit()
    return {"status": "ok"}
