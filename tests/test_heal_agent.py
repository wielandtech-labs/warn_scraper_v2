"""End-to-end heal loop with a scripted FakeClient.

Simulates a broken CA scraper, runs the agent loop, and verifies it produces
a working patch by exercising every tool: read_parser → read_snapshot →
run_parser_candidate → propose_patch.

No network calls. Substitutes a FakeClient for the real Anthropic SDK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from warn_v2.heal.agent import HealResult, run_heal
from warn_v2.heal.tools import HealContext, read_parser


# ----- Fakes that mimic the Anthropic SDK response shape -----

@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class _Message:
    content: list[Any] = field(default_factory=list)
    role: str = "assistant"


class ScriptedClient:
    """Yields one pre-built assistant Message per `.create()` call."""

    def __init__(self, script: list[_Message]):
        self._script = list(script)
        self.calls: list[dict] = []

    def create(self, **kwargs: Any) -> _Message:
        self.calls.append(kwargs)
        if not self._script:
            raise RuntimeError("ScriptedClient: script exhausted")
        return self._script.pop(0)


# ----- Helpers -----

def _patched_ca_source(broken: bool) -> str:
    """Return either the real CA source or a deliberately broken variant."""
    src = read_parser("CA")
    if not broken:
        return src
    # Break it: flip the header-detection loop to never find the header.
    return src.replace(
        'if any(k in cells for k in _COMPANY_KEYS):',
        'if False:  # injected break',
    )


# ----- Tests -----

def test_agent_drives_full_loop_and_proposes_patch(
    tmp_path: Path, ca_golden_xlsx_bytes
) -> None:
    snap = tmp_path / "snap.xlsx"
    snap.write_bytes(ca_golden_xlsx_bytes)

    good_code = _patched_ca_source(broken=False)
    bad_code = _patched_ca_source(broken=True)

    ctx = HealContext(
        state="CA",
        snapshot_path=snap,
        error="ParseFailed: could not locate header row containing 'Company'",
        expected_row_range=(1, 100),
        required_fields=frozenset({"employer", "notice_date"}),
    )

    # Scripted assistant turns. Each Message carries either tool_uses or text.
    script = [
        _Message(content=[
            _TextBlock(text="Reading the current CA parser first."),
            _ToolUseBlock(id="t1", name="read_parser", input={"state": "CA"}),
        ]),
        _Message(content=[
            _TextBlock(text="Now inspecting the failing snapshot."),
            _ToolUseBlock(id="t2", name="read_snapshot", input={}),
        ]),
        # Trial a deliberately broken candidate first (simulates the agent
        # iterating). Sandbox will fail; agent should retry with the real fix.
        _Message(content=[
            _ToolUseBlock(
                id="t3",
                name="run_parser_candidate",
                input={"code": bad_code},
            ),
        ]),
        _Message(content=[
            _ToolUseBlock(
                id="t4",
                name="run_parser_candidate",
                input={"code": good_code},
            ),
        ]),
        _Message(content=[
            _TextBlock(text="Working candidate confirmed. Proposing patch."),
            _ToolUseBlock(
                id="t5",
                name="propose_patch",
                input={
                    "code": good_code,
                    "summary": "restore header-row detection (test)",
                },
            ),
        ]),
    ]

    client = ScriptedClient(script)
    result: HealResult = run_heal(ctx, client, max_turns=10)

    assert result.proposed is True
    assert result.code == good_code
    assert result.summary.startswith("restore header-row")
    assert result.rows_after == 11
    # Client was called once per assistant turn (5 turns).
    assert len(client.calls) == 5


def test_agent_returns_no_patch_when_text_only(tmp_path: Path) -> None:
    """If the LLM gives up and replies with text only, run_heal must report it."""
    snap = tmp_path / "snap.xlsx"
    snap.write_bytes(b"")

    ctx = HealContext(
        state="CA",
        snapshot_path=snap,
        error="source went 404",
        expected_row_range=(1, 100),
        required_fields=frozenset({"employer"}),
    )

    script = [
        _Message(content=[
            _TextBlock(text="Upstream URL is dead; needs a human."),
        ])
    ]
    client = ScriptedClient(script)
    result = run_heal(ctx, client, max_turns=5)

    assert result.proposed is False
    assert "Upstream" in result.last_message
    assert result.turns == 1


def test_agent_respects_max_turns(tmp_path: Path) -> None:
    snap = tmp_path / "snap.xlsx"
    snap.write_bytes(b"")
    ctx = HealContext(
        state="CA",
        snapshot_path=snap,
        error="",
        expected_row_range=(1, 100),
        required_fields=frozenset(),
    )

    looping_turn = _Message(content=[
        _ToolUseBlock(id="t", name="read_parser", input={"state": "CA"}),
    ])
    # 6 identical turns; cap is 3 → loop exits without a patch.
    client = ScriptedClient([looping_turn] * 6)
    result = run_heal(ctx, client, max_turns=3)

    assert result.proposed is False
    assert result.turns == 3
    assert "max_turns" in (result.last_message or "")
