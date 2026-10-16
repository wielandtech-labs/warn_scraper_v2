"""A minimal Bluesky (AT Protocol) client: log in, upload a card, post.

Three XRPC calls over httpx, so no SDK dependency: createSession with an app
password, uploadBlob for the share card, createRecord for the post. The link
is made clickable with a richtext facet (UTF-8 byte offsets) and unfurled as
an external embed whose thumbnail is the uploaded card.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx

SERVICE = "https://bsky.social"


def configured() -> bool:
    return bool(os.getenv("BLUESKY_HANDLE") and os.getenv("BLUESKY_APP_PASSWORD"))


def link_facet(text: str, url: str) -> dict[str, Any]:
    """Facet marking the last occurrence of `url` in `text` as a link."""
    start = text.rindex(url)
    byte_start = len(text[:start].encode("utf-8"))
    return {
        "index": {"byteStart": byte_start, "byteEnd": byte_start + len(url.encode("utf-8"))},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
    }


def build_record(
    text: str, url: str, title: str, description: str, thumb: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    external: dict[str, Any] = {"uri": url, "title": title, "description": description}
    if thumb is not None:
        external["thumb"] = thumb
    return {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "langs": ["en"],
        "facets": [link_facet(text, url)],
        "embed": {"$type": "app.bsky.embed.external", "external": external},
    }


class BlueskyClient:
    def __init__(self, client: httpx.Client | None = None, service: str = SERVICE):
        self._http = client or httpx.Client(timeout=30)
        self._service = service.rstrip("/")
        self._jwt: str | None = None
        self._did: str | None = None

    def _xrpc(self, method: str, **kwargs: Any) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        if self._jwt:
            headers["Authorization"] = f"Bearer {self._jwt}"
        resp = self._http.post(f"{self._service}/xrpc/{method}", headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def login(self) -> None:
        data = self._xrpc(
            "com.atproto.server.createSession",
            json={
                "identifier": os.environ["BLUESKY_HANDLE"],
                "password": os.environ["BLUESKY_APP_PASSWORD"],
            },
        )
        self._jwt, self._did = data["accessJwt"], data["did"]

    def _ensure_login(self) -> None:
        if self._jwt is None:
            self.login()

    def upload_png(self, png: bytes) -> dict[str, Any]:
        self._ensure_login()
        data = self._xrpc(
            "com.atproto.repo.uploadBlob", content=png, headers={"Content-Type": "image/png"}
        )
        return data["blob"]

    def post(self, record: dict[str, Any]) -> str:
        """Create the post; returns its at:// URI."""
        self._ensure_login()
        data = self._xrpc(
            "com.atproto.repo.createRecord",
            json={"repo": self._did, "collection": "app.bsky.feed.post", "record": record},
        )
        return data["uri"]
