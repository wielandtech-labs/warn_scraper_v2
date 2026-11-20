#!/usr/bin/env python3
"""Post to a LinkedIn organization page via the Community Management API.

Reads credentials from ~/.warnindex/linkedin.json.
Accepts post text from a file (arg 1) and an optional link URL (arg 2).
Handles token refresh automatically.

Uses only stdlib.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG = Path.home() / ".warnindex" / "linkedin.json"
API = "https://api.linkedin.com"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API_VERSION = "202401"


def _load_config() -> dict:
    with open(CONFIG) as f:
        return json.load(f)


def _save_config(cfg: dict) -> None:
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)
    CONFIG.chmod(0o600)


def _refresh_token(cfg: dict) -> str:
    if not cfg.get("refresh_token"):
        raise RuntimeError("No refresh token. Re-run linkedin_auth.py to re-authorize.")
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": cfg["refresh_token"],
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data)
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    cfg["access_token"] = result["access_token"]
    if "refresh_token" in result:
        cfg["refresh_token"] = result["refresh_token"]
    _save_config(cfg)
    return cfg["access_token"]


def _post(token: str, org_id: str, text: str, link_url: str | None = None) -> dict:
    body: dict = {
        "author": f"urn:li:organization:{org_id}",
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if link_url:
        body["content"] = {"article": {"source": link_url}}

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}/rest/posts",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": API_VERSION,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return {
            "status": resp.status,
            "post_id": resp.headers.get("x-restli-id", ""),
        }


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: linkedin_post.py <text-file> [link-url]"}))
        sys.exit(1)

    cfg = _load_config()
    text = Path(sys.argv[1]).read_text().strip()
    if not text:
        print(json.dumps({"error": "Empty post text"}))
        sys.exit(1)

    link_url = sys.argv[2] if len(sys.argv) > 2 else None
    org_id = cfg["organization_id"]
    token = cfg["access_token"]

    try:
        result = _post(token, org_id, text, link_url)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            token = _refresh_token(cfg)
            result = _post(token, org_id, text, link_url)
        else:
            body = e.read().decode() if e.fp else ""
            print(json.dumps({"error": f"HTTP {e.code}", "detail": body}))
            sys.exit(1)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
