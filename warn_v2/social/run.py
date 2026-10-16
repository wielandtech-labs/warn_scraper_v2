"""One ``warn-v2 post-alerts`` pass: select, render, post, record.

A row lands in ``notice_social_posts`` (and is committed) right after the
platform accepted the post, so a crash mid-run never re-posts what already
went out. The first failure on a platform stops that platform for the run --
a bad credential or an outage would fail every remaining post the same way.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from warn_v2.api.routes.og import notice_card_png
from warn_v2.db.models import Notice, NoticeSocialPost
from warn_v2.social import bluesky, webhook
from warn_v2.social.candidates import select_candidates
from warn_v2.social.format import notice_url, render_post

log = logging.getLogger(__name__)

PLATFORMS = ("bluesky", *webhook.WEBHOOKS)


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
    http = http or httpx.Client(timeout=30)
    summary: dict[str, int] = {}
    for platform in platforms:
        summary[platform] = 0
        if not dry_run and not is_configured(platform):
            log.warning("post-alerts: %s not configured, skipping", platform)
            continue
        notices = select_candidates(
            db, now=now, platform=platform, min_layoffs=min_layoffs, limit=max_posts
        )
        log.info("post-alerts: %s: %d candidate(s)", platform, len(notices))
        bsky = bluesky.BlueskyClient(http) if platform == "bluesky" else None
        for notice in notices:
            text = render_post(notice)
            if dry_run:
                log.info("post-alerts [dry-run] %s %s:\n%s", platform, notice.notice_id, text)
                summary[platform] += 1
                continue
            try:
                if bsky is not None:
                    external_id, body = _post_bluesky(bsky, notice, text, now)
                else:
                    external_id, body = None, webhook.payload(platform, text)
                    webhook.send(platform, text, http)
            except Exception:
                log.exception(
                    "post-alerts: %s failed on %s; stopping it", platform, notice.notice_id
                )
                break
            db.add(
                NoticeSocialPost(
                    notice_id=notice.notice_id,
                    platform=platform,
                    external_post_id=external_id,
                    posted_at=now,
                    payload=json.dumps(body, default=str),
                )
            )
            db.commit()
            summary[platform] += 1
            log.info("post-alerts: %s posted %s", platform, notice.notice_id)
    return summary
