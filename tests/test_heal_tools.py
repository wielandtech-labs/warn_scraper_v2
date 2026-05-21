from __future__ import annotations

import base64
from pathlib import Path

import pytest

from warn_v2.heal.tools import (
    HealContext,
    dispatch,
    read_golden_fixture,
    read_parser,
    read_snapshot,
)


def test_read_parser_returns_ca_module() -> None:
    src = read_parser("CA")
    assert "class CAScraper" in src
    assert "register(CAScraper())" in src


def test_read_snapshot(tmp_path: Path) -> None:
    p = tmp_path / "snap.bin"
    p.write_bytes(b"<html>hi</html>")
    out = read_snapshot(p)
    assert out["size"] == 15
    assert out["preview_utf8"] == "<html>hi</html>"
    assert base64.b64decode(out["bytes_b64"]) == b"<html>hi</html>"


def test_read_golden_fixture_ca_present() -> None:
    # CA fixture isn't committed (it's built programmatically in conftest), so the
    # tool returns present=False for it. AZ has a real fixture file we can use.
    out = read_golden_fixture("AZ")
    assert out["present"] is True
    names = {f["name"] for f in out["files"]}
    assert "sample.html" in names


def test_dispatch_run_parser_candidate(ca_golden_xlsx_bytes, tmp_path: Path) -> None:
    snap = tmp_path / "snap.xlsx"
    snap.write_bytes(ca_golden_xlsx_bytes)
    ctx = HealContext(
        state="CA",
        snapshot_path=snap,
        error="",
        expected_row_range=(1, 100),
        required_fields=frozenset({"employer"}),
    )
    code = read_parser("CA")
    result, terminal = dispatch("run_parser_candidate", {"code": code}, ctx)
    assert terminal is None
    assert result["ok"] is True
    assert result["row_count"] == 11


def test_dispatch_propose_patch_is_terminal() -> None:
    ctx = HealContext(
        state="CA",
        snapshot_path=Path("ignored"),
        error="",
        expected_row_range=(1, 100),
        required_fields=frozenset(),
    )
    result, terminal = dispatch(
        "propose_patch", {"code": "x = 1", "summary": "test"}, ctx
    )
    assert terminal == {"code": "x = 1", "summary": "test"}
    assert result == {"accepted": True}


def test_dispatch_unknown_tool_raises() -> None:
    ctx = HealContext(
        state="CA",
        snapshot_path=Path("ignored"),
        error="",
        expected_row_range=(1, 100),
        required_fields=frozenset(),
    )
    with pytest.raises(ValueError, match="unknown tool"):
        dispatch("not_a_tool", {}, ctx)
