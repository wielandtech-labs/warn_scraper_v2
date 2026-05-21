"""Tools the self-heal agent can call.

Each tool is a pure-ish function and has a JSON schema describing its inputs
suitable for Anthropic's tool-use API. The agent loop in `heal/agent.py`
dispatches to these by name.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from warn_v2.heal.sandbox import SandboxResult, run_candidate

# Where state scrapers live in the source tree.
STATES_DIR = Path(__file__).resolve().parent.parent / "scrapers" / "states"
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "scrapers" / "fixtures"


@dataclass(slots=True)
class HealContext:
    """All the per-state inputs the agent needs to do its job."""

    state: str
    snapshot_path: Path
    error: str  # the original parser's traceback or validation reason
    expected_row_range: tuple[int, int]
    required_fields: frozenset[str]


def state_module_path(state: str) -> Path:
    return STATES_DIR / f"{state.lower()}.py"


def fixture_dir(state: str) -> Path:
    return FIXTURES_DIR / state.lower()


def read_parser(state: str) -> str:
    """Return the current source code of the scraper for `state`."""
    return state_module_path(state).read_text(encoding="utf-8")


def read_snapshot(snapshot_path: Path) -> dict:
    """Return the raw failing input, base64-encoded so the agent can read it as text.

    Also includes a UTF-8 decoded preview for HTML/text inputs.
    """
    raw = snapshot_path.read_bytes()
    preview: str
    try:
        preview = raw.decode("utf-8", errors="replace")[:20_000]
    except UnicodeDecodeError:
        preview = "<binary content; use the base64 field>"
    return {
        "bytes_b64": base64.b64encode(raw).decode("ascii"),
        "size": len(raw),
        "preview_utf8": preview,
    }


def read_golden_fixture(state: str) -> dict:
    """Return any committed fixture for `state` (sample bytes + metadata)."""
    d = fixture_dir(state)
    if not d.exists():
        return {"present": False}

    out: dict[str, Any] = {"present": True, "files": []}
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        data = f.read_bytes()
        entry: dict[str, Any] = {
            "name": f.name,
            "size": len(data),
            "bytes_b64": base64.b64encode(data).decode("ascii"),
        }
        if f.suffix.lower() in {".json", ".html", ".txt", ".csv", ".md"}:
            entry["text"] = data.decode("utf-8", errors="replace")
        out["files"].append(entry)
    return out


def run_parser_candidate(
    code: str, snapshot_path: Path, state: str, *, timeout_s: int = 30
) -> dict:
    """Compile + run the candidate module against the snapshot, return rows or traceback."""
    raw = snapshot_path.read_bytes()
    result: SandboxResult = run_candidate(code, raw, state, timeout_s=timeout_s)
    return {
        "ok": result.ok,
        "row_count": result.row_count,
        "rows_sample": (result.rows or [])[:3],
        "traceback": result.traceback,
        "timed_out": result.timed_out,
    }


# ----- Tool definitions (Anthropic tool-use shape) -----

TOOL_DEFS: list[dict] = [
    {
        "name": "read_parser",
        "description": (
            "Read the current source of the state's scraper module. Use this "
            "first to understand the existing implementation before proposing changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"state": {"type": "string"}},
            "required": ["state"],
        },
    },
    {
        "name": "read_snapshot",
        "description": (
            "Read the raw bytes that the current parser failed on. Returns "
            "size, a UTF-8 preview, and a base64 encoding."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_golden_fixture",
        "description": (
            "Read the committed test fixture for the state. Returns sample "
            "bytes and any expected.json metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"state": {"type": "string"}},
            "required": ["state"],
        },
    },
    {
        "name": "run_parser_candidate",
        "description": (
            "Run a complete candidate scraper module against the failing "
            "snapshot. The candidate must call `register(...)` and produce a "
            "scraper whose `parse(raw_bytes)` returns a list[NoticeRow]. "
            "Returns row_count, a 3-row sample, and a traceback on failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Full Python source for the replacement module.",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "propose_patch",
        "description": (
            "Finalize the fix: the supplied `code` will replace the state's "
            "scraper module and a PR will be opened. Only call this once you "
            "have verified the candidate works via run_parser_candidate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "summary": {
                    "type": "string",
                    "description": "1-2 sentence explanation for the PR body.",
                },
            },
            "required": ["code", "summary"],
        },
    },
]


def dispatch(
    name: str, args: dict, ctx: HealContext
) -> tuple[Any, dict | None]:
    """Run a tool by name with the given args.

    Returns (json_serializable_result, propose_patch_args_if_terminal).
    """
    if name == "read_parser":
        return read_parser(args["state"]), None
    if name == "read_snapshot":
        return read_snapshot(ctx.snapshot_path), None
    if name == "read_golden_fixture":
        return read_golden_fixture(args["state"]), None
    if name == "run_parser_candidate":
        return run_parser_candidate(args["code"], ctx.snapshot_path, ctx.state), None
    if name == "propose_patch":
        # Returning the propose_patch args signals the agent loop to terminate.
        return {"accepted": True}, args
    raise ValueError(f"unknown tool: {name}")


def to_text(value: Any) -> str:
    """Stringify a tool result for the Anthropic API (it expects text content)."""
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str, indent=2)
