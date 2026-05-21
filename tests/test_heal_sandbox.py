"""Sandbox round-trips: load a candidate module, parse a snapshot, get rows back."""
from __future__ import annotations

from pathlib import Path

import pytest

from warn_v2.heal.sandbox import run_candidate
from warn_v2.scrapers.states.ca import CAScraper


CA_PATH = Path(CAScraper.__module__.replace(".", "/") + ".py")


@pytest.fixture
def ca_module_src() -> str:
    """Read the current CA scraper source — a known-good candidate."""
    from warn_v2.scrapers import states

    src = (Path(states.__file__).parent / "ca.py").read_text(encoding="utf-8")
    return src


def test_known_good_candidate_returns_rows(ca_module_src, ca_golden_xlsx_bytes) -> None:
    result = run_candidate(ca_module_src, ca_golden_xlsx_bytes, "CA")
    assert result.ok, result.traceback
    assert result.row_count == 11


def test_broken_candidate_returns_traceback(ca_golden_xlsx_bytes) -> None:
    bad = "raise RuntimeError('boom')\n"
    result = run_candidate(bad, ca_golden_xlsx_bytes, "CA")
    assert not result.ok
    assert "RuntimeError: boom" in (result.traceback or "")


def test_candidate_without_registration_returns_error(ca_golden_xlsx_bytes) -> None:
    """A candidate that imports cleanly but never calls register() must fail clearly."""
    src = "x = 1\n"  # valid Python; does nothing
    result = run_candidate(src, ca_golden_xlsx_bytes, "CA")
    assert not result.ok
    assert "did not register" in (result.traceback or "")


def test_candidate_timeout(ca_golden_xlsx_bytes) -> None:
    src = (
        "import time\n"
        "from warn_v2.scrapers.registry import register\n"
        "class S:\n"
        "    state = 'CA'\n"
        "    source_url = 'http://x'\n"
        "    expected_row_range = (1, 10)\n"
        "    required_fields = frozenset()\n"
        "    def fetch(self): return b''\n"
        "    def parse(self, raw):\n"
        "        time.sleep(60)\n"
        "        return []\n"
        "register(S())\n"
    )
    result = run_candidate(src, ca_golden_xlsx_bytes, "CA", timeout_s=2)
    assert not result.ok
    assert result.timed_out is True
