"""Transactional email over SMTP (implicit TLS).

Uses the stdlib ``smtplib``/``email`` — no third-party dependency. Configured
entirely from the environment so credentials stay in a SealedSecret:

    SMTP_HOST      e.g. mail.wielandtech.com
    SMTP_PORT      e.g. 465 (implicit TLS / SMTP_SSL)
    SMTP_USERNAME  e.g. no-reply@wielandtech.com
    SMTP_PASSWORD  (secret)
    SMTP_FROM      From: header (defaults to SMTP_USERNAME)

``send_email`` is the single seam tests monkeypatch, so nothing actually
connects to a mail server during the suite.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


class EmailNotConfigured(RuntimeError):
    """Raised when SMTP_* env vars are missing so callers can degrade gracefully."""


def _config() -> dict[str, str | int]:
    host = os.environ.get("SMTP_HOST")
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    if not (host and username and password):
        raise EmailNotConfigured("SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD must be set")
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "465")),
        "username": username,
        "password": password,
        "from": os.environ.get("SMTP_FROM", username),
    }


def send_email(to: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    """Send one email via SMTP implicit TLS. Raises EmailNotConfigured if unset."""
    cfg = _config()
    msg = EmailMessage()
    msg["From"] = cfg["from"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP_SSL(cfg["host"], cfg["port"]) as server:
        server.login(cfg["username"], cfg["password"])
        server.send_message(msg)
