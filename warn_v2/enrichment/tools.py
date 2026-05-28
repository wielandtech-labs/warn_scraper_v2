"""Tool definitions and dispatch for the enrichment agent.

Three tools:
- web_search  — Anthropic built-in; no extra API key required.
- fetch_url   — httpx GET → plain text (BeautifulSoup); 10 s timeout, 50 KB cap.
- finalize    — terminal tool; returns structured enrichment result and ends the loop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_MAX_BYTES = 50_000
_TIMEOUT_S = 10


# ---------------------------------------------------------------------------
# Result type returned by the terminal tool
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class FinalizeArgs:
    website: str | None
    sic_code: str | None
    sic_desc: str | None
    duns: str | None
    confidence: float
    sources: list[str]


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TOOL_DEFS: list[dict] = [
    {
        "type": "web_search_20250305",
        "name": "web_search",
    },
    {
        "name": "fetch_url",
        "description": (
            "Fetch a URL and return its text content (HTML stripped to readable text). "
            "Good for reading company websites, SEC EDGAR search results, "
            "OpenCorporates pages, and state business registry pages. "
            "Returns up to 50 KB of text. Fails gracefully on non-HTML or errors."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "finalize",
        "description": (
            "Submit your enrichment findings. Call this once you have gathered "
            "enough evidence. Set fields to null if not found — never guess. "
            "confidence should reflect overall certainty (0.0-1.0). "
            "sources must list every URL you actually retrieved information from."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "website": {
                    "type": ["string", "null"],
                    "description": "Primary company website URL, e.g. https://acme.com",
                },
                "sic_code": {
                    "type": ["string", "null"],
                    "description": "4-digit SIC code, e.g. '3559'",
                },
                "sic_desc": {
                    "type": ["string", "null"],
                    "description": "SIC description, e.g. 'Special Industry Machinery, NEC'",
                },
                "duns": {
                    "type": ["string", "null"],
                    "description": (
                        "9-digit D-U-N-S number if found in a public source "
                        "(SEC EDGAR, OpenCorporates). Null if not found — do not guess."
                    ),
                },
                "confidence": {
                    "type": "number",
                    "description": "Overall confidence in findings, 0.0 (none) to 1.0 (certain).",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of URLs you retrieved information from.",
                },
            },
            "required": ["website", "sic_code", "sic_desc", "duns", "confidence", "sources"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def dispatch(name: str, args: dict[str, Any]) -> tuple[Any, FinalizeArgs | None]:
    """Execute a tool call. Returns (result, terminal_args).

    terminal_args is non-None only when `finalize` is called — the caller
    should stop the loop when it is set.
    """
    if name == "finalize":
        fin = FinalizeArgs(
            website=args.get("website"),
            sic_code=args.get("sic_code"),
            sic_desc=args.get("sic_desc"),
            duns=args.get("duns"),
            confidence=float(args.get("confidence", 0.0)),
            sources=args.get("sources") or [],
        )
        return {"ok": True, "message": "Enrichment recorded."}, fin

    if name == "fetch_url":
        return _fetch_url(args["url"]), None

    # web_search is handled natively by the API; we should never dispatch it.
    raise ValueError(f"unknown tool: {name!r}")


def _fetch_url(url: str) -> dict[str, Any]:
    try:
        r = httpx.get(
            url,
            follow_redirects=True,
            timeout=_TIMEOUT_S,
            headers={"User-Agent": "warn-v2/0.1 (research bot; contact raphael@wielandtech.com)"},
        )
        r.raise_for_status()
        content_type = r.headers.get("content-type", "")
        if "html" in content_type or not content_type:
            soup = BeautifulSoup(r.content[:_MAX_BYTES], "lxml")
            # Remove script/style noise
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = soup.get_text(" ", strip=True)
            # Normalise whitespace
            text = " ".join(text.split())
            return {"url": url, "text": text[:_MAX_BYTES]}
        # Non-HTML (PDF, JSON, etc.) — return raw truncated text
        return {"url": url, "text": r.text[:_MAX_BYTES]}
    except httpx.HTTPStatusError as e:
        return {"url": url, "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        log.debug("fetch_url %s failed: %s", url, e)
        return {"url": url, "error": str(e)}


def to_text(value: Any) -> str:
    """Stringify a tool result for the Anthropic API tool_result content."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "error" in value:
            return f"Error: {value['error']}"
        if "text" in value:
            return value["text"]
        return str(value)
    return str(value)
