"""One ``warn-v2 post-alerts`` pass: select, render, post, record.

A row lands in ``notice_social_posts`` (and is committed) right after the
platform accepted the post, so a crash mid-run never re-posts what already
went out. A platform-wide failure (outage, bad credential, rate limit) stops
that platform for the run, since every remaining post would fail the same
way; a rejection of one notice's post (other 4xx) skips just that notice, so
it can't block the notices behind it run after run.

Errors are logged without their message: an httpx error names the request
URL, and a webhook URL is itself the credential.
"""
from __future__ import annotations

import contextlib
import json
import logging
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from warn_v2.api.og_cards import notice_card_png
from warn_v2.db.models import Notice, NoticeSocialPost
from warn_v2.social import bluesky, webhook
from warn_v2.social.candidates import select_candidates
from warn_v2.social.format import notice_url, render_post

log = logging.getLogger(__name__)

PLATFORMS = ("bluesky", *webhook.WEBHOOKS)
# 4xx statuses that mean the platform, not this notice, is the problem.
_PLATFORM_WIDE_4XX = {401, 403, 429}


def is_configured(platform: str) -> bool:
    return bluesky.configured() if platform == "bluesky" else webhook.configured(platform)


def _post_bluesky(client: bluesky.BlueskyClient, notice: Notice, text: str, now: datetime):
    url = notice_url(notice)
    thumb = client.upload_png(notice_card_png(notice))
    record = bluesky.build_record(
        text,
        url,
        title=f"{notice.employer} ({notice.state}) WARN notice",
        description="Filing details, history and related notices on WARN Index.",
        thumb=thumb,
        now=now,
    )
    return client.post(record), record


def run_alerts(
    db: Session,
    *,
    now: datetime,
    platforms: list[str],
    min_layoffs: int,
    max_posts: int,
    dry_run: bool,
    http: httpx.Client | None = None,
) -> dict[str, int]:
    """Post up to `max_posts` new notices per platform; returns posts per platform.
    `dry_run` logs what would be posted (even on unconfigured platforms) and
    writes nothing."""
    with contextlib.ExitStack() as stack:
        if http is None:
            http = stack.enter_context(httpx.Client(timeout=30))
        return {
            platform: _run_platform(
                db, http, platform, now, min_layoffs, max_posts, dry_run
            )
            for platform in platforms
        }


def _run_platform(
    db: Session,
    http: httpx.Client,
    platform: str,
    now: datetime,
    min_layoffs: int,
    max_posts: int,
    dry_run: bool,
) -> int:
    if not dry_run and not is_configured(platform):
        log.warning("post-alerts: %s not configured, skipping", platform)
        return 0
    notices = select_candidates(
        db, now=now, platform=platform, min_layoffs=min_layoffs, limit=max_posts
    )
    log.info("post-alerts: %s: %d candidate(s)", platform, len(notices))
    bsky = bluesky.BlueskyClient(http) if platform == "bluesky" else None
    posted = 0
    for notice in notices:
        nid = notice.notice_id
        text = render_post(notice)
        if dry_run:
            log.info("post-alerts [dry-run] %s %s:\n%s", platform, nid, text)
            posted += 1
            continue
        try:
            if bsky is not None:
                external_id, body = _post_bluesky(bsky, notice, text, now)
            else:
                external_id, body = None, webhook.payload(platform, text)
                webhook.send(platform, text, http)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if 400 <= status < 500 and status not in _PLATFORM_WIDE_4XX:
                log.error("post-alerts: %s rejected %s (HTTP %d); skipping it",
                          platform, nid, status)
                continue
            log.error("post-alerts: %s returned HTTP %d on %s; stopping it",
                      platform, status, nid)
            break
        except httpx.HTTPError as exc:
            log.error("post-alerts: %s unreachable on %s (%s); stopping it",
                      platform, nid, type(exc).__name__)
            break
        db.add(
            NoticeSocialPost(
                notice_id=nid,
                platform=platform,
                external_post_id=external_id,
                posted_at=now,
                payload=json.dumps(body, default=str),
            )
        )
        db.commit()
        posted += 1
        log.info("post-alerts: %s posted %s", platform, nid)
    return posted
