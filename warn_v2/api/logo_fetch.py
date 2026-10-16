"""Company logo lookup: fetch a site's own icon, server side, and cache it.

The browser never talks to the company's site (no third-party request, no
referrer leak); it asks /api/logos/{company_id} and gets either image bytes or
a 404, on which the UI keeps its monogram tile.

Only raster formats are served, identified by magic bytes rather than the
remote Content-Type. SVG is refused outright: it can carry script, and serving
it from our origin would make an XSS vector out of any company's favicon.

Outbound fetches are SSRF-guarded: https only, every hop's host must resolve
to public addresses, redirects are followed by hand (max 2) so each hop is
re-checked. The domain comes from Company.website (enrichment data), never
from the request, so this is not an open proxy -- the caller only picks a
company id. A DNS answer that changes between our check and httpx's own
lookup is not defended against; acceptable for that reason.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import struct
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 100_000
OVERRIDE_MAX_BYTES = 300_000  # admin-set logo images (e.g. a 256px Commons PNG)
MIN_LOGO_WIDTH = 64  # narrower reads as a blurry favicon, not a logo
HTML_MAX_BYTES = 200_000
TIMEOUT_S = 3.0
DEADLINE_S = 8.0  # whole lookup, all candidates; per-request timeouts reset per read
MAX_DECLARED = 3  # declared <link rel=icon> candidates tried, apple-touch first
MAX_REDIRECTS = 2
HIT_TTL_S = 7 * 24 * 3600
MISS_TTL_S = 24 * 3600
CACHE_SIZE = 4096

_UA = {"User-Agent": "WARNIndexLogoBot/1.0 (+https://warnindex.com/about)"}

# (magic prefix, offset, media type)
_SIGNATURES: list[tuple[bytes, int, str]] = [
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"\x00\x00\x01\x00", 0, "image/x-icon"),
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"WEBP", 8, "image/webp"),
]

_ICON_LINK = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r"""([a-zA-Z-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")


def sniff_type(data: bytes) -> str | None:
    for magic, offset, media in _SIGNATURES:
        if data[offset : offset + len(magic)] == magic:
            if media == "image/webp" and not data.startswith(b"RIFF"):
                continue
            return media
    return None


_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg_width(data: bytes) -> int | None:
    i = 2  # past SOI
    while i + 9 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in _JPEG_SOF:
            return struct.unpack(">H", data[i + 7 : i + 9])[0]
        if marker == 0x01 or 0xD0 <= marker <= 0xD9:  # standalone markers
            i += 2
            continue
        i += 2 + struct.unpack(">H", data[i + 2 : i + 4])[0]
    return None


def image_width(data: bytes, media: str) -> int | None:
    """Pixel width from the image header (largest entry for ICO); None if unreadable."""
    try:
        if media == "image/png":
            return struct.unpack(">I", data[16:20])[0]
        if media == "image/x-icon":
            count = struct.unpack("<H", data[4:6])[0]
            widths = [data[6 + 16 * n] or 256 for n in range(count)]  # 0 means 256
            return max(widths) if widths else None
        if media == "image/jpeg":
            return _jpeg_width(data)
        if media == "image/webp":
            chunk = data[12:16]
            if chunk == b"VP8 ":
                return struct.unpack("<H", data[26:28])[0] & 0x3FFF
            if chunk == b"VP8L":
                return 1 + (data[21] | ((data[22] & 0x3F) << 8))
            if chunk == b"VP8X":
                return 1 + int.from_bytes(data[24:27], "little")
    except (IndexError, struct.error):
        return None
    return None


def domain_of(website: str | None) -> str | None:
    """Normalise Company.website ("www.acme.com", "http://acme.com/x") to a host."""
    if not website:
        return None
    raw = website.strip()
    if "://" not in raw:
        raw = "https://" + raw
    host = (urlsplit(raw).hostname or "").lower().rstrip(".")
    if not host or "." not in host:
        return None
    return host


def _host_is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False
    try:
        addrs = {ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in infos}
    except ValueError:
        return False
    return bool(addrs) and all(a.is_global for a in addrs)


def _get(
    client: httpx.Client, url: str, cap: int, truncate: bool = False
) -> tuple[bytes, str] | None:
    """GET with manual, re-checked redirects and a body size cap.

    Over the cap, the body is refused -- or, with `truncate`, cut at the cap
    (HTML: the <head> we need is at the front). Returns (body, final url)."""
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or not _host_is_public(parts.hostname):
            return None
        with client.stream("GET", url) as resp:
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    return None
                url = urljoin(url, location)
                continue
            if resp.status_code != 200:
                return None
            body = bytearray()
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) > cap:
                    if not truncate:
                        return None
                    del body[cap:]
                    break
            return bytes(body), url
    return None


def _declared_icons(html: str, base: str) -> list[str]:
    """Icon hrefs from <link rel=...icon...>, apple-touch-icon first (bigger)."""
    found: list[tuple[int, str]] = []
    for tag in _ICON_LINK.findall(html):
        attrs = {k.lower(): v.strip("\"'") for k, v in _ATTR.findall(tag)}
        rel = attrs.get("rel", "").lower()
        href = attrs.get("href")
        if not href or "icon" not in rel or href.lower().endswith(".svg"):
            continue
        try:
            url = urljoin(base, href)
        except ValueError:  # e.g. an unbalanced IPv6 bracket
            continue
        found.append((0 if "apple-touch-icon" in rel else 1, url))
    ordered = [href for _, href in sorted(found, key=lambda pair: pair[0])]
    return ordered[:MAX_DECLARED]


# Malformed hrefs/Locations surface as ValueError or httpx.InvalidURL
# (not an HTTPError); any of them just means "no logo from this URL".
_FETCH_ERRORS = (httpx.HTTPError, httpx.InvalidURL, ValueError)


def fetch_image(url: str) -> tuple[bytes, str] | None:
    """One admin-set logo URL, under the same SSRF guard: (bytes, media type), or None."""
    with httpx.Client(timeout=TIMEOUT_S, headers=_UA, follow_redirects=False) as client:
        try:
            got = _get(client, url, OVERRIDE_MAX_BYTES)
        except _FETCH_ERRORS:
            return None
    if got is None:
        return None
    media = sniff_type(got[0])
    return (got[0], media) if media else None


def fetch_logo(domain: str) -> tuple[bytes, str] | None:
    """Best-effort icon for `domain`: (bytes, media type), or None."""
    base = f"https://{domain}/"
    deadline = time.monotonic() + DEADLINE_S
    with httpx.Client(timeout=TIMEOUT_S, headers=_UA, follow_redirects=False) as client:

        def try_image(url: str) -> tuple[bytes, str] | None:
            if time.monotonic() > deadline:
                return None
            try:
                got = _get(client, url, MAX_BYTES)
            except _FETCH_ERRORS:
                return None
            if got is None:
                return None
            media = sniff_type(got[0])
            return (got[0], media) if media else None

        hit = try_image(urljoin(base, "/apple-touch-icon.png"))
        if hit:
            return hit
        try:
            page = _get(client, base, HTML_MAX_BYTES, truncate=True)
        except _FETCH_ERRORS:
            page = None
        if page is not None:
            html = page[0].decode("utf-8", errors="replace")
            for href in _declared_icons(html, page[1]):
                hit = try_image(href)
                if hit:
                    return hit
        return try_image(urljoin(base, "/favicon.ico"))


class _TTLCache:
    """Small thread-safe LRU with per-entry expiry; None values cache misses."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._data: OrderedDict[str, tuple[float, tuple[bytes, str] | None]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[bool, tuple[bytes, str] | None]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None or entry[0] < time.monotonic():
                self._data.pop(key, None)
                return False, None
            self._data.move_to_end(key)
            return True, entry[1]

    def put(self, key: str, value: tuple[bytes, str] | None) -> None:
        ttl = HIT_TTL_S if value else MISS_TTL_S
        with self._lock:
            self._data[key] = (time.monotonic() + ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self._size:
                self._data.popitem(last=False)

    def evict(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


cache = _TTLCache(CACHE_SIZE)

# Single-flight: a page showing the same company twice (or two visitors on a
# cold cache) fetches each domain once; later callers wait, then read the cache.
_inflight: dict[str, threading.Lock] = {}
_inflight_guard = threading.Lock()


def override_key(logo_url: str) -> str:
    return "url:" + logo_url


def _cached(key: str, fetch: Callable[[], tuple[bytes, str] | None]) -> tuple[bytes, str] | None:
    found, value = cache.get(key)
    if found:
        return value
    with _inflight_guard:
        lock = _inflight.setdefault(key, threading.Lock())
    with lock:
        found, value = cache.get(key)
        if not found:
            value = fetch()
            cache.put(key, value)
    with _inflight_guard:
        _inflight.pop(key, None)
    return value


def logo_for(website: str | None, logo_url: str | None = None) -> tuple[bytes, str] | None:
    """Cached logo lookup: the admin-set logo_url first, else the site's icon
    keyed by domain (many companies share one site)."""
    if logo_url:
        hit = _cached(override_key(logo_url), lambda: fetch_image(logo_url))
        if hit:
            return hit
    domain = domain_of(website)
    if domain is None:
        return None
    return _cached(domain, lambda: fetch_logo(domain))
