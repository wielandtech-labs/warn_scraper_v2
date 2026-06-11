"""Login/logout/me endpoints for cookie-session auth."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from warn_v2 import auth
from warn_v2.api.deps import get_current_user, get_db
from warn_v2.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


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
