"""Tests for email-alert subscriptions: signup, double opt-in, and digests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from warn_v2.db.models import Notice, Subscription
from warn_v2.notifications.digest import render_digest, run_digest

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture()
def sent(monkeypatch):
    """Capture outbound emails instead of sending. Returns the captured list."""
    box: list[dict] = []

    def _fake(to, subject, text_body, html_body=None, **kwargs):
        box.append({"to": to, "subject": subject, "text": text_body, "html": html_body})

    monkeypatch.setattr("warn_v2.api.routes.subscriptions.send_email", _fake)
    monkeypatch.setattr("warn_v2.notifications.digest.send_email", _fake)
    return box


@pytest.fixture()
def api_client(db):
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


def _notice(db, employer="Acme Inc", state="CA", scraped_at=None, **kw):
    n = Notice(
        notice_id=kw.pop("notice_id", f"sub_{employer[:8]}_{state}_{scraped_at}"),
        state=state,
        employer=employer,
        notice_date=kw.pop("notice_date", None),
        scraped_at=scraped_at,
        **kw,
    )
    db.add(n)
    db.flush()
    return n


def _sub(db, email="me@example.com", confirmed=True, last_notified_at=EPOCH, **kw):
    suffix = kw.pop("suffix", email)
    s = Subscription(
        email=email,
        confirm_token=f"c-{suffix}",
        unsubscribe_token=f"u-{suffix}",
        confirmed_at=EPOCH if confirmed else None,
        last_notified_at=last_notified_at if confirmed else None,
        **kw,
    )
    db.add(s)
    db.flush()
    return s


# --- signup + double opt-in ------------------------------------------------

def test_create_subscription_sends_confirmation(api_client, db, sent):
    resp = api_client.post("/api/subscriptions", json={"email": "Me@Example.com", "state": "ca"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    db.commit()

    sub = db.scalar(select(Subscription))
    assert sub.email == "me@example.com"  # normalized
    assert sub.state == "CA"
    assert sub.confirmed_at is None  # unconfirmed until the link is clicked
    assert len(sent) == 1
    assert sub.confirm_token in sent[0]["text"]


def test_invalid_email_rejected(api_client, db, sent):
    assert api_client.post("/api/subscriptions", json={"email": "not-an-email"}).status_code == 422
    assert sent == []


def test_confirm_activates_subscription(api_client, db, sent):
    api_client.post("/api/subscriptions", json={"email": "me@example.com"})
    db.commit()
    sub = db.scalar(select(Subscription))

    resp = api_client.get(f"/api/subscriptions/confirm?token={sub.confirm_token}")
    assert resp.status_code == 200
    assert "confirmed" in resp.text.lower()
    db.refresh(sub)
    assert sub.confirmed_at is not None
    assert sub.last_notified_at is not None  # watermark set so only future notices send


def test_confirm_bad_token_is_friendly(api_client, db):
    db.commit()
    resp = api_client.get("/api/subscriptions/confirm?token=nope")
    assert resp.status_code == 200
    assert "invalid" in resp.text.lower()


def test_unsubscribe_deletes_row(api_client, db, sent):
    api_client.post("/api/subscriptions", json={"email": "me@example.com"})
    db.commit()
    sub = db.scalar(select(Subscription))

    resp = api_client.get(f"/api/subscriptions/unsubscribe?token={sub.unsubscribe_token}")
    assert resp.status_code == 200
    assert db.scalar(select(Subscription)) is None


# --- digest ----------------------------------------------------------------

def test_digest_emails_new_matching_notices(db, sent):
    _sub(db, email="me@example.com", state="CA")
    _notice(db, employer="Acme Inc", state="CA", scraped_at=EPOCH + timedelta(days=1))
    _notice(db, employer="Texas Co", state="TX", scraped_at=EPOCH + timedelta(days=1))
    db.commit()

    summary = run_digest(db, EPOCH + timedelta(days=2))
    assert summary == {"subscriptions": 1, "emailed": 1, "notices": 1, "failed": 0}
    assert len(sent) == 1
    assert "Acme Inc" in sent[0]["text"]
    assert "Texas Co" not in sent[0]["text"]  # state filter excluded it


def test_digest_advances_watermark_no_resend(db, sent):
    _sub(db, email="me@example.com")
    _notice(db, employer="Acme Inc", scraped_at=EPOCH + timedelta(days=1))
    db.commit()

    run_digest(db, EPOCH + timedelta(days=2))
    assert len(sent) == 1
    # Second run with no newer notices sends nothing.
    summary = run_digest(db, EPOCH + timedelta(days=3))
    assert summary["emailed"] == 0
    assert len(sent) == 1


def test_digest_skips_unconfirmed_and_superseded(db, sent):
    _sub(db, email="unconfirmed@example.com", confirmed=False, suffix="unconf")
    _sub(db, email="confirmed@example.com", confirmed=True, suffix="conf")
    _notice(db, employer="Active Co", scraped_at=EPOCH + timedelta(days=1))
    sup = _notice(db, employer="Old Co", scraped_at=EPOCH + timedelta(days=1),
                  notice_id="sup1")
    sup.is_superseded = True
    db.commit()

    summary = run_digest(db, EPOCH + timedelta(days=2))
    assert summary["emailed"] == 1  # only the confirmed subscriber
    assert sent[0]["to"] == "confirmed@example.com"
    assert "Active Co" in sent[0]["text"]
    assert "Old Co" not in sent[0]["text"]


def test_digest_html_escapes_untrusted_fields(db):
    # Scraped employer names and user-supplied filter text must not become
    # live markup in the HTML alternative.
    sub = _sub(db, email="me@example.com", employer_query="<b>Evil & Co</b>")
    notice = _notice(
        db, employer="<img src=x onerror=alert(1)> & Sons",
        scraped_at=EPOCH + timedelta(days=1), notice_id="esc1",
    )

    _subject, text, html = render_digest(sub, [notice])
    assert "<img" not in html
    assert "&lt;img src=x onerror=alert(1)&gt; &amp; Sons" in html
    assert "&lt;b&gt;Evil &amp; Co&lt;/b&gt;" in html
    # The plain-text alternative is not HTML and stays raw.
    assert "<img src=x onerror=alert(1)> & Sons" in text


def test_digest_isolates_send_failures(db, monkeypatch):
    _sub(db, email="good1@example.com", suffix="g1")
    _sub(db, email="bad@example.com", suffix="bad")
    _sub(db, email="good2@example.com", suffix="g2")
    _notice(db, employer="Acme Inc", scraped_at=EPOCH + timedelta(days=1))
    db.commit()

    calls: list[str] = []

    def _flaky(to, subject, text_body, html_body=None, **kwargs):
        calls.append(to)
        if to == "bad@example.com":
            raise RuntimeError("smtp boom")

    monkeypatch.setattr("warn_v2.notifications.digest.send_email", _flaky)
    summary = run_digest(db, EPOCH + timedelta(days=2))
    assert summary["emailed"] == 2
    assert summary["failed"] == 1
    assert set(calls) == {"good1@example.com", "bad@example.com", "good2@example.com"}
    # The good subscribers' watermarks advanced; the failed one's did not.
    # (SQLite returns naive datetimes, so compare tz-stripped.)
    bad = db.scalar(select(Subscription).where(Subscription.email == "bad@example.com"))
    assert bad.last_notified_at.replace(tzinfo=None) == EPOCH.replace(tzinfo=None)


# --- rich HTML rendering ----------------------------------------------------

def test_digest_cta_deep_links_filters(db):
    sub = _sub(db, email="me@example.com", state="CA", industry="31-33",
               employer_query="acme co")
    notice = _notice(db, state="CA", scraped_at=EPOCH + timedelta(days=1))

    _subject, _text, html = render_digest(sub, [notice])
    assert "/notices?" in html
    assert "state=CA" in html
    assert "industry=31-33" in html
    assert "employer=acme+co" in html

    plain = _sub(db, email="all@example.com", suffix="all")
    _subject, _text, html = render_digest(plain, [notice])
    # No filters → bare list link (the URL lands in an escaped href).
    assert "/notices?" not in html


def test_digest_summary_and_rows(db):
    sub = _sub(db, email="me@example.com")
    counted = _notice(db, employer="Acme Inc", state="CA",
                      scraped_at=EPOCH + timedelta(days=1), notice_id="rich1",
                      notice_date=datetime(2026, 6, 3, tzinfo=UTC).date(),
                      layoff_count=250, closure_category="Closure")
    # No date, count, or category — those fragments must be omitted entirely.
    bare = _notice(db, employer="Mystery Co", state="CA",
                   scraped_at=EPOCH + timedelta(days=1), notice_id="rich2")

    _subject, _text, html = render_digest(sub, [counted, bare])
    assert "2 new layoff notices" in html
    assert "250 workers affected" in html
    assert "California" in html  # full state name, not the code
    assert "Jun 3, 2026" in html
    assert "CLOSURE" in html  # category badge
    assert f"/notices/{counted.notice_id}" in html
    assert f"/notices/{bare.notice_id}" in html
    assert "None" not in html  # missing fields are omitted, not rendered


def test_digest_truncation_note_only_at_cap(db):
    from warn_v2.notifications.digest import _MAX_PER_DIGEST

    sub = _sub(db, email="me@example.com")
    notices = [
        _notice(db, employer=f"Co {i}", scraped_at=EPOCH + timedelta(days=1),
                notice_id=f"cap{i}")
        for i in range(_MAX_PER_DIGEST)
    ]

    _subject, _text, html = render_digest(sub, notices)
    assert "there may be more" in html
    _subject, _text, html = render_digest(sub, notices[:-1])
    assert "there may be more" not in html


def test_fmt_date_windows_safe():
    from datetime import date

    from warn_v2.notifications.templates import fmt_date

    assert fmt_date(date(2026, 6, 3)) == "Jun 3, 2026"  # no leading zero
    assert fmt_date(None) == ""


def test_send_email_sets_list_unsubscribe_headers():
    from warn_v2.notifications.email import _build_message

    msg = _build_message("from@x.com", "to@x.com", "s", "t", "<p>h</p>",
                         "https://x.com/unsub?token=abc")
    assert msg["List-Unsubscribe"] == "<https://x.com/unsub?token=abc>"
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"

    plain = _build_message("from@x.com", "to@x.com", "s", "t")
    assert "List-Unsubscribe" not in plain
    assert "List-Unsubscribe-Post" not in plain


def test_one_click_unsubscribe_post(api_client, db, sent):
    api_client.post("/api/subscriptions", json={"email": "me@example.com"})
    db.commit()
    sub = db.scalar(select(Subscription))

    resp = api_client.post(f"/api/subscriptions/unsubscribe?token={sub.unsubscribe_token}")
    assert resp.status_code == 200
    assert db.scalar(select(Subscription)) is None
    # Bad tokens still 200 so validity doesn't leak.
    assert api_client.post("/api/subscriptions/unsubscribe?token=nope").status_code == 200


def test_confirmation_email_uses_shell(api_client, db, sent):
    api_client.post("/api/subscriptions", json={"email": "me@example.com"})
    db.commit()
    sub = db.scalar(select(Subscription))

    html = sent[0]["html"]
    assert "Layoff notices" in html  # brand wordmark header
    confirm_url = f"/api/subscriptions/confirm?token={sub.confirm_token}"
    assert f'href="https://warn.wielandtech.com{confirm_url}"' in html


def test_write_preview_html(db):
    """Env-gated: WRITE_EMAIL_PREVIEW=<dir> pytest -k preview → digest_preview.html."""
    import os

    out_dir = os.environ.get("WRITE_EMAIL_PREVIEW")
    if not out_dir:
        pytest.skip("set WRITE_EMAIL_PREVIEW=<dir> to write the preview file")

    from pathlib import Path

    sub = _sub(db, email="preview@example.com", state="CA")
    samples = [
        _notice(db, employer="Acme Manufacturing LLC", state="CA",
                scraped_at=EPOCH, notice_id="pv1",
                notice_date=datetime(2026, 6, 30, tzinfo=UTC).date(),
                layoff_count=1250, closure_category="Closure"),
        _notice(db, employer="Globex & Sons", state="CA", scraped_at=EPOCH,
                notice_id="pv2", notice_date=datetime(2026, 6, 28, tzinfo=UTC).date(),
                layoff_count=87, closure_category="Layoff"),
        _notice(db, employer="Initech (Regional HQ)", state="CA", scraped_at=EPOCH,
                notice_id="pv3", layoff_count=460),
        _notice(db, employer="Undated Widgets Inc", state="CA", scraped_at=EPOCH,
                notice_id="pv4", closure_category="Layoff"),
        _notice(db, employer="Tiny Startup <html> Test & Co", state="CA",
                scraped_at=EPOCH, notice_id="pv5",
                notice_date=datetime(2026, 6, 25, tzinfo=UTC).date()),
    ]
    _subject, _text, html = render_digest(sub, samples)
    out = Path(out_dir) / "digest_preview.html"
    out.write_text(html, encoding="utf-8")


def test_email_not_configured_surfaces_503(api_client, db, monkeypatch):
    from warn_v2.notifications.email import EmailNotConfigured

    def _raise(*a, **k):
        raise EmailNotConfigured("nope")

    monkeypatch.setattr("warn_v2.api.routes.subscriptions.send_email", _raise)
    resp = api_client.post("/api/subscriptions", json={"email": "me@example.com"})
    assert resp.status_code == 503
    db.rollback()
    assert db.scalar(select(Subscription)) is None  # rolled back, no orphan row
