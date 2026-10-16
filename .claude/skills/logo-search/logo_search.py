"""Helper for the logo-search skill: talks to the warnindex.com admin logo API.

Stdlib only (never imports warn_v2), so it runs under any Python with no venv.

    python logo_search.py queue [N]            companies due a logo search (JSON)
    python logo_search.py probe ID             what /api/logos/ID serves now (JSON)
    python logo_search.py wikifile "File:X"    raster thumbnail URL for a Wikipedia /
                                               Wikimedia Commons file (SVGs rendered to PNG)
    python logo_search.py set ID URL|none      store a logo (server validates) or stamp a miss

The admin API key comes from $WARNINDEX_ADMIN_KEY or ~/.warnindex/admin-key and
is never printed. $WARNINDEX_BASE_URL overrides https://warnindex.com.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("WARNINDEX_BASE_URL", "https://warnindex.com").rstrip("/")
UA = "WARNIndexLogoSearch/1.0 (+https://warnindex.com/about)"
THUMB_WIDTH = 256


def _key() -> str:
    key = os.environ.get("WARNINDEX_ADMIN_KEY")
    if not key:
        path = Path.home() / ".warnindex" / "admin-key"
        if not path.exists():
            sys.exit(f"no admin key: set WARNINDEX_ADMIN_KEY or create {path}")
        key = path.read_text(encoding="utf-8").strip()
    return key


def _request(method: str, url: str, body: dict | None = None, auth: bool = True):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if auth:
        req.add_header("Authorization", f"Bearer {_key()}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            ctype = resp.headers.get("content-type", "")
            payload = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        return e.code, {"error": detail}
    # Unknown /api paths return the SPA shell with a 200: insist on JSON.
    if "json" not in ctype:
        return 502, {"error": f"non-JSON response ({ctype}) - is the API deployed?"}
    return 200, json.loads(payload)


def _out(status: int, payload) -> None:
    print(json.dumps(payload, indent=1))
    sys.exit(0 if status == 200 else 1)


def queue(n: str = "40") -> None:
    _out(*_request("GET", f"{BASE}/api/admin/logo-queue?limit={int(n)}"))


def probe(company_id: str) -> None:
    _out(*_request("GET", f"{BASE}/api/admin/companies/{int(company_id)}/logo-probe"))


def wikifile(title: str) -> None:
    if not title.lower().startswith("file:"):
        title = "File:" + title
    # en.wikipedia resolves both its own (non-free) files and Commons files.
    qs = urllib.parse.urlencode({
        "action": "query", "titles": title, "prop": "imageinfo",
        "iiprop": "url|mime|size", "iiurlwidth": THUMB_WIDTH, "format": "json",
    })
    status, data = _request("GET", f"https://en.wikipedia.org/w/api.php?{qs}", auth=False)
    if status != 200:
        _out(status, data)
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        info = (page.get("imageinfo") or [None])[0]
        if info:
            # thumburl is a raster render (PNG for SVG sources); fall back to the
            # original only when it is itself raster.
            url = info.get("thumburl") or (
                info["url"] if info.get("mime", "").startswith("image/") and
                "svg" not in info.get("mime", "") else None)
            if url:
                url = url.split("?", 1)[0]  # drop utm_* tracking params
            _out(200 if url else 1, {"title": page.get("title"), "url": url,
                                     "mime": info.get("mime"), "width": info.get("width"),
                                     "height": info.get("height")})
    _out(1, {"error": f"no such file: {title}"})


def set_logo(company_id: str, url: str) -> None:
    body = {"logo_url": None if url.lower() == "none" else url}
    _out(*_request("PUT", f"{BASE}/api/admin/companies/{int(company_id)}/logo", body))


COMMANDS = {"queue": queue, "probe": probe, "wikifile": wikifile, "set": set_logo}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
