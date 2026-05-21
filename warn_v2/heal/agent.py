"""Self-heal agent loop.

A minimal multi-turn tool-use loop over the Anthropic Messages API. The agent
inspects the failing snapshot, reads the current parser, optionally consults
the golden fixture, iterates with `run_parser_candidate` until it has working
code, and terminates by calling `propose_patch`.

The `LLMClient` Protocol lets tests inject a fake client that returns scripted
responses, so we exercise the full loop without making real API calls.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from warn_v2.heal import tools
from warn_v2.heal.tools import HealContext

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TURNS = 12
DEFAULT_MAX_TOKENS = 8192


SYSTEM_PROMPT = """\
You are the self-heal agent for warn-v2, a system that scrapes US state WARN
layoff notices into a normalized database.

A state's scraper just failed on a real input. Your job:
1. Use `read_parser` to read the current scraper code for the failing state.
2. Use `read_snapshot` to see the raw input the parser choked on.
3. Optionally use `read_golden_fixture` to see the last-known-good shape.
4. Iterate: write a candidate replacement module and run it via
   `run_parser_candidate`. The candidate must register itself with the project
   registry (`from warn_v2.scrapers.registry import register; register(MyScraper())`).
   The class must expose `state`, `source_url`, `expected_row_range`,
   `required_fields`, `fetch()`, and `parse(raw: bytes) -> list[NoticeRow]`.
5. When the candidate returns a row count inside the state's
   `expected_row_range` with required fields populated, call `propose_patch`
   with the final code and a 1-sentence summary. That ends the loop.

Constraints:
- Keep changes minimal and targeted at the observed failure. Do not rewrite
  the whole scraper if a single column rename or header detection tweak fixes
  it.
- Preserve the scraper's class name, `state`, and `source_url`.
- Match the existing project's style: use helpers from
  `warn_v2.scrapers._helpers` (as_date/as_int/as_str/ColumnMap) and dataclasses
  in `warn_v2.scrapers.base` (NoticeRow, ParseFailed, ScrapeFailed).
- Don't fetch the network from inside `parse()` — it must be a pure function
  of `raw: bytes`.
- If you genuinely cannot fix it (e.g. source went 404, content is encrypted,
  page is a CAPTCHA), do NOT call `propose_patch` — just respond with a final
  message explaining why, and the orchestrator will surface that to a human.
"""


class LLMClient(Protocol):
    """Minimal slice of the Anthropic Python client used by the agent loop."""

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        tools: list[dict],
        messages: list[dict],
    ) -> Any:
        ...


@dataclass(slots=True)
class HealResult:
    proposed: bool
    code: str | None = None
    summary: str | None = None
    rows_after: int = 0
    last_message: str | None = None
    turns: int = 0


def run_heal(
    ctx: HealContext,
    client: LLMClient,
    *,
    model: str = DEFAULT_MODEL,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> HealResult:
    """Run the self-heal loop. Returns the proposed patch (or None)."""
    user_brief = (
        f"State: {ctx.state}\n"
        f"Expected row range: {ctx.expected_row_range}\n"
        f"Required fields: {sorted(ctx.required_fields)}\n\n"
        f"Original failure:\n{ctx.error[:4000]}\n"
    )
    messages: list[dict] = [
        {
            "role": "user",
            "content": [{"type": "text", "text": user_brief}],
        }
    ]

    last_text: str | None = None
    last_run_rows = 0

    for turn in range(1, max_turns + 1):
        log.info("heal[%s] turn %d", ctx.state, turn)
        resp = client.create(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            tools=tools.TOOL_DEFS,
            messages=messages,
        )

        # Echo the assistant turn into the conversation history.
        messages.append({"role": "assistant", "content": resp.content})

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        texts = [b for b in resp.content if getattr(b, "type", None) == "text"]
        if texts:
            last_text = texts[-1].text

        if not tool_uses:
            # No more tool calls — agent decided it can't (or won't) patch.
            return HealResult(
                proposed=False, last_message=last_text, turns=turn
            )

        tool_results: list[dict] = []
        for use in tool_uses:
            try:
                value, terminal_args = tools.dispatch(use.name, use.input, ctx)
            except Exception as e:  # noqa: BLE001
                log.exception("tool %s raised", use.name)
                value = {"error": f"{type(e).__name__}: {e}"}
                terminal_args = None

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": use.id,
                    "content": tools.to_text(value),
                }
            )

            if use.name == "run_parser_candidate" and isinstance(value, dict):
                last_run_rows = int(value.get("row_count") or 0)

            if terminal_args is not None:
                # propose_patch was called — finalize and exit.
                # We still send back a tool_result so the protocol is clean.
                messages.append({"role": "user", "content": tool_results})
                return HealResult(
                    proposed=True,
                    code=terminal_args["code"],
                    summary=terminal_args["summary"],
                    rows_after=last_run_rows,
                    last_message=last_text,
                    turns=turn,
                )

        messages.append({"role": "user", "content": tool_results})

    return HealResult(
        proposed=False,
        last_message=last_text or f"hit max_turns={max_turns} without proposing a patch",
        turns=max_turns,
    )


def build_anthropic_client() -> LLMClient:
    """Construct the real Anthropic client. Imported lazily so tests don't need the SDK."""
    import anthropic  # noqa: PLC0415  (lazy import on purpose)

    client = anthropic.Anthropic()
    return _AnthropicAdapter(client)


class _AnthropicAdapter:
    """Wraps anthropic.Anthropic().messages.create with the LLMClient signature."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def create(self, **kwargs: Any) -> Any:
        return self._client.messages.create(**kwargs)
