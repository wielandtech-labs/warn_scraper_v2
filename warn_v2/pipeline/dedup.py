"""Content-hash IDs for notices.

V1 used `YYMMDD + first3(company) + first3(zip)`, which collided and conflated
distinct notices. V2 uses sha256 over the natural-key fields so identical input
yields a stable ID and any field change produces a different ID.
"""
from __future__ import annotations

import hashlib

from warn_v2.scrapers.base import NoticeRow


def notice_id(row: NoticeRow) -> str:
    """Stable content-hash ID for a notice."""
    parts = [
        row.state.upper(),
        _norm(row.employer),
        row.notice_date.isoformat() if row.notice_date else "",
        _norm(row.city or ""),
        _norm(row.zip or ""),
    ]
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().split())
