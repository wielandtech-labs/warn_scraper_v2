"""Tests for the social alert bot (warn_v2.social) and `warn-v2 post-alerts`."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import respx
from click.testing import CliRunner
from sqlalchemy import select

from warn_v2 import cli
from warn_v2.db.models import Location, Notice, NoticeSocialPost
from warn_v2.social import bluesky, format, run
from warn_v2.social.candidates import select_candidates

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_social_env(monkeypatch: pytest.MonkeyPatch):
    for var in (
        "BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD", "DISCORD_WEBHOOK_URL", "SLACK_WEBHOOK_URL"
    ):
        monkeypatch.delenv(var, raising=False)
    # Rendering the real card is covered in test_og_cards; keep these fast.
    monkeypatch.setattr(run, "notice_card_png", lambda notice: b"png")


def _notice(
    nid: str,
    count: int | None = 500,
    *,
    filed: date = date(2026, 10, 14),
    scraped: datetime = NOW - timedelta(hours=3),
    **kw,
) -> Notice:
    return Notice(
        notice_id=nid,
        state="WA",
        employer=kw.pop("employer", "Acme Corp"),
        notice_date=filed,
        layoff_count=count,
        scraped_at=scraped,
        source_url="https://example.com",
        **kw,
    )


def _ids(db, platform="bluesky", min_layoffs=250, limit=10):
    return [
        n.notice_id
        for n in select_candidates(
            db, now=NOW, platform=platform, min_layoffs=min_layoffs, limit=limit
        )
    ]


# ----- candidate selection -----

def test_candidates_filter_and_order(db):
    db.add_all(
        [
            _notice("big", 1200),
            _notice("mid", 300),
            _notice("small", 100),
            _notice("nocount", None),
            _notice("superseded", 900, is_superseded=True),
            _notice("nonwarn", 900, closure_category="Non-WARN"),
            _notice("stale-scrape", 900, scraped=NOW - timedelta(hours=49)),
            # A backfill: found today, but filed years ago.
            _notice("backfill", 5000, filed=date(2019, 3, 1)),
        ]
    )
    db.commit()
    assert _ids(db) == ["big", "mid"]
    assert _ids(db, limit=1) == ["big"]


def test_candidates_are_per_platform(db):
    db.add(_notice("n1"))
    db.add(NoticeSocialPost(notice_id="n1", platform="bluesky", posted_at=NOW))
    db.commit()
    assert _ids(db, "bluesky") == []
    assert _ids(db, "discord") == ["n1"]


# ----- post text -----

def test_render_post_format():
    n = _notice("abc", 1350, closure_category="Layoff", effective_date=date(2026, 12, 13))
    n.location = Location(city="Seattle", state="WA")
    text = format.render_post(n)
    assert text.splitlines()[0] == "🚨 WARN notice: Acme Corp (WA)"
    assert "• Workers affected: 1,350" in text
    assert "• Action: Mass layoff" in text
    assert "• Location: Seattle, WA" in text
    assert "• Effective: Dec 13, 2026" in text
    assert text.endswith("https://warnindex.com/notices/abc")


def test_render_post_fallbacks():
    text = format.render_post(_notice("abc", None))
    assert "Workers affected: Not published" in text
    assert "Action: WARN notice" in text  # uncategorized is never called a layoff
    assert "Location: Washington" in text
    assert "Effective: Pending" in text


def test_render_post_truncates_long_employer_to_limit():
    text = format.render_post(_notice("a" * 32, 300, employer="Very Long Employer " * 30))
    assert len(text) <= format.MAX_POST_CHARS
    assert "…" in text.splitlines()[0]
    assert text.endswith("/notices/" + "a" * 32)  # the link survives


# ----- bluesky -----

def test_link_facet_uses_utf8_byte_offsets():
    url = "https://warnindex.com/notices/x"
    text = f"🚨 é\n{url}"
    facet = bluesky.link_facet(text, url)
    raw = text.encode("utf-8")
    start, end = facet["index"]["byteStart"], facet["index"]["byteEnd"]
    assert raw[start:end].decode() == url
    assert start == len("🚨 é\n".encode())


@respx.mock
def test_bluesky_client_logs_in_once_and_posts(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "warnindex.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "app-pw")
    base = "https://bsky.social/xrpc/"
    login = respx.post(base + "com.atproto.server.createSession").mock(
        return_value=httpx.Response(200, json={"accessJwt": "jwt", "did": "did:plc:x"})
    )
    blob = {"$type": "blob", "ref": {"$link": "b"}, "mimeType": "image/png", "size": 3}
    upload = respx.post(base + "com.atproto.repo.uploadBlob").mock(
        return_value=httpx.Response(200, json={"blob": blob})
    )
    create = respx.post(base + "com.atproto.repo.createRecord").mock(
        return_value=httpx.Response(200, json={"uri": "at://did:plc:x/post/1", "cid": "c"})
    )
    client = bluesky.BlueskyClient(httpx.Client())
    thumb = client.upload_png(b"png")
    url = "https://warnindex.com/notices/n"
    record = bluesky.build_record(f"hi\n{url}", url, "t", "d", thumb, NOW)
    assert client.post(record) == "at://did:plc:x/post/1"

    assert login.call_count == 1
    assert upload.calls[0].request.headers["Authorization"] == "Bearer jwt"
    assert upload.calls[0].request.headers["Content-Type"] == "image/png"
    sent = json.loads(create.calls[0].request.content)
    assert sent["repo"] == "did:plc:x"
    assert sent["record"]["createdAt"] == "2026-10-16T12:00:00Z"
    assert sent["record"]["embed"]["external"]["thumb"] == blob


# ----- run_alerts -----

@respx.mock
def test_run_posts_records_and_does_not_repost(db, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    hook = respx.post("https://discord.test/hook").mock(return_value=httpx.Response(204))
    db.add_all([_notice("n1", 800), _notice("n2", 400)])
    db.commit()

    kw = dict(now=NOW, platforms=["discord"], min_layoffs=250, max_posts=5, dry_run=False)
    assert run.run_alerts(db, http=httpx.Client(), **kw) == {"discord": 2}
    assert json.loads(hook.calls[0].request.content)["content"].startswith("🚨")
    rows = db.scalars(select(NoticeSocialPost).order_by(NoticeSocialPost.notice_id)).all()
    assert [(r.notice_id, r.platform) for r in rows] == [("n1", "discord"), ("n2", "discord")]

    assert run.run_alerts(db, http=httpx.Client(), **kw) == {"discord": 0}
    assert hook.call_count == 2


@respx.mock
def test_run_stops_platform_on_first_failure(db, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://slack.test/hook")
    hook = respx.post("https://slack.test/hook").mock(return_value=httpx.Response(500))
    db.add_all([_notice("n1", 800), _notice("n2", 400)])
    db.commit()
    summary = run.run_alerts(
        db, now=NOW, platforms=["slack"], min_layoffs=250, max_posts=5, dry_run=False,
        http=httpx.Client(),
    )
    assert summary == {"slack": 0}
    assert hook.call_count == 1
    assert db.scalars(select(NoticeSocialPost)).all() == []


def test_run_skips_unconfigured_platforms(db):
    db.add(_notice("n1"))
    db.commit()
    summary = run.run_alerts(
        db, now=NOW, platforms=["bluesky"], min_layoffs=250, max_posts=5, dry_run=False
    )
    assert summary == {"bluesky": 0}


# ----- CLI -----

def test_cli_dry_run_writes_nothing(db, monkeypatch):
    monkeypatch.setattr(run, "select_candidates", lambda *a, **kw: [_notice("n1")])
    result = CliRunner().invoke(cli.main, ["post-alerts", "--dry-run", "--platform", "bluesky"])
    assert result.exit_code == 0, result.output
    assert "bluesky=1 (dry run)" in result.output
    assert db.scalars(select(NoticeSocialPost)).all() == []


def test_cli_rejects_unknown_platform():
    result = CliRunner().invoke(cli.main, ["post-alerts", "--platform", "myspace"])
    assert result.exit_code != 0
    assert "unknown platform" in result.output
