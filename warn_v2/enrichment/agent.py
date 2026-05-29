"""Enrichment agent loop.

A multi-turn tool-use loop over the Anthropic Messages API. Given a company
name and its WARN notice context, the agent searches the web and fetches
public sources to determine the company's website, SIC code, and DUNS number,
then calls `finalize` to return a structured result.

The `LLMClient` Protocol lets tests inject a fake client so we exercise the
full loop without making real API calls.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from warn_v2.enrichment import tools
from warn_v2.enrichment.tools import FinalizeArgs

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TURNS = 4
DEFAULT_MAX_TOKENS = 2048


SYSTEM_PROMPT = """\
You are a company research agent for warn-v2 (US WARN layoff notices).
Find the company's primary website URL. SIC/NAICS/DUNS were already tried elsewhere.

BUDGET: 3 tool calls total (web_search + fetch_url combined). Use them wisely.
Call finalize as soon as you have enough evidence — do not keep searching.

Steps:
1. web_search the company name + state.
2. Optionally fetch_url one candidate page to confirm it is the right company.
3. Call finalize with the website (or null if not found), confidence 0.0–1.0,
   and any DUNS you found in a public source (never guess).

Do not call finalize if confidence < 0.4. If nothing is found, finalize with
null website and confidence 0.3.
"""



class LLMClient(Protocol):
    """Minimal slice of the Anthropic client used by the agent loop."""

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        tools: list[dict],
        messages: list[dict],
    ) -> Any: ...


@dataclass(slots=True)
class EnrichmentContext:
    """Everything we know about a company before enrichment."""

    company_id: int
    company_name: str
    # Snapshot of recent notices for disambiguation
    notices: list[dict] = field(default_factory=list)
    # e.g. [{"state":"CA","city":"Oakland","layoff_count":250,"notice_date":"2026-01-15"}]


@dataclass(slots=True)
class EnrichmentResult:
    proposed: bool
    website: str | None = None
    sic_code: str | None = None
    sic_desc: str | None = None
    duns: str | None = None
    confidence: float = 0.0
    sources: list[str] = field(default_factory=list)
    last_message: str | None = None
    turns: int = 0



def _build_brief(ctx: EnrichmentContext) -> str:
    lines = [f'Company: "{ctx.company_name}"']
    if ctx.notices:
        n = ctx.notices[0]
        parts = [f"State: {n.get('state', '?')}"]
        if n.get("city"):
            parts.append(f"City: {n['city']}")
        lines.append(", ".join(parts))
        for notice in ctx.notices[:3]:
            date = notice.get("notice_date", "unknown date")
            count = notice.get("layoff_count")
            count_str = f"{count} employees" if count else "unknown employees"
            lines.append(f"WARN notice: {count_str} affected, {date}")
    return "\n".join(lines)


def run_enrichment(
    ctx: EnrichmentContext,
    client: LLMClient,
    *,
    model: str = DEFAULT_MODEL,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> EnrichmentResult:
    """Run the enrichment agent loop. Returns the enrichment result."""
    messages: list[dict] = [
        {
            "role": "user",
            "content": [{"type": "text", "text": _build_brief(ctx)}],
        }
    ]

    last_text: str | None = None

    for turn in range(1, max_turns + 1):
        log.info("enrich[%s] turn %d", ctx.company_name[:40], turn)
        resp = client.create(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            tools=tools.TOOL_DEFS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": resp.content})

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        texts = [b for b in resp.content if getattr(b, "type", None) == "text"]
        if texts:
            last_text = texts[-1].text

        if not tool_uses:
            # Agent gave up without finalizing.
            return EnrichmentResult(proposed=False, last_message=last_text, turns=turn)

        tool_results: list[dict] = []
        finalize_args: FinalizeArgs | None = None

        for use in tool_uses:
            # web_search is handled server-side; its results appear as
            # tool_result blocks that the API injects automatically. We only
            # need to dispatch our custom tools.
            if use.name == "web_search":
                # The API already ran the search; no client-side dispatch needed.
                # We still need to acknowledge it so the protocol stays clean.
                # The actual results are already appended to resp.content by
                # the API as server_tool_use / web_search_tool_result blocks.
                continue

            try:
                value, fin = tools.dispatch(use.name, use.input)
            except Exception as e:
                log.exception("tool %s raised", use.name)
                value = {"error": f"{type(e).__name__}: {e}"}
                fin = None

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": use.id,
                    "content": tools.to_text(value),
                }
            )

            if fin is not None:
                finalize_args = fin

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

        if finalize_args is not None:
            return EnrichmentResult(
                proposed=True,
                website=finalize_args.website,
                sic_code=finalize_args.sic_code,
                sic_desc=finalize_args.sic_desc,
                duns=finalize_args.duns,
                confidence=finalize_args.confidence,
                sources=finalize_args.sources,
                last_message=last_text,
                turns=turn,
            )

    return EnrichmentResult(
        proposed=False,
        last_message=last_text or f"hit max_turns={max_turns} without finalizing",
        turns=max_turns,
    )


def result_to_confidence_decimal(result: EnrichmentResult) -> Decimal:
    """Convert float confidence to Decimal(3,2) for the DB column."""
    return Decimal(str(round(result.confidence, 2)))


def build_anthropic_client() -> LLMClient:
    """Construct the real Anthropic client. Imported lazily so tests don't need the SDK."""
    import anthropic

    client = anthropic.Anthropic()
    return _AnthropicAdapter(client)


class _AnthropicAdapter:
    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, *, system: str, **kwargs: Any) -> Any:
        # Wrap the system prompt in the cache_control format so Anthropic caches
        # it for 5 minutes.  The system prompt + tool definitions are resent on
        # every turn; caching them gives a 90 % discount on those tokens.
        # Tests pass system as a plain string and never reach this adapter, so
        # the LLMClient Protocol signature stays as `system: str`.
        system_with_cache = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        return self._client.messages.create(system=system_with_cache, **kwargs)
