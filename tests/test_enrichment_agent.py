"""Unit tests for the enrichment agent loop using a fake LLMClient."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from warn_v2.enrichment.agent import EnrichmentContext, run_enrichment

# ---------------------------------------------------------------------------
# Fake LLM infrastructure
# ---------------------------------------------------------------------------

@dataclass
class _Block:
    type: str
    id: str = "tu_001"
    name: str = ""
    input: dict = None  # type: ignore[assignment]
    text: str = ""

    def __post_init__(self):
        if self.input is None:
            self.input = {}


@dataclass
class _Response:
    content: list[_Block]


class _FakeClient:
    """Returns scripted responses in order, then raises if exhausted."""

    def __init__(self, responses: list[_Response]) -> None:
        self._q = list(responses)

    def create(self, **_: Any) -> _Response:
        if not self._q:
            raise AssertionError("FakeClient exhausted — more turns than expected")
        return self._q.pop(0)


def _ctx(**kw) -> EnrichmentContext:
    defaults = dict(
        company_id=1,
        company_name="Acme Robotics Inc",
        notices=[
            {
                "state": "CA",
                "city": "Oakland",
                "layoff_count": 250,
                "notice_date": "2026-01-15",
            }
        ],
    )
    defaults.update(kw)
    return EnrichmentContext(**defaults)


def _web_search_use() -> _Block:
    return _Block(
        type="tool_use",
        id="tu_ws",
        name="web_search",
        input={"query": "Acme Robotics Inc CA"},
    )


def _fetch_use(url: str = "https://acme.com/about") -> _Block:
    return _Block(type="tool_use", id="tu_fu", name="fetch_url", input={"url": url})


def _finalize_use(**kw) -> _Block:
    defaults = dict(
        website="https://acme.com",
        sic_code="3559",
        sic_desc="Special Industry Machinery, NEC",
        duns=None,
        confidence=0.85,
        sources=["https://acme.com", "https://opencorporates.com/companies/us_ca/12345"],
    )
    defaults.update(kw)
    return _Block(type="tool_use", id="tu_fin", name="finalize", input=defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_happy_path_web_search_then_finalize():
    """web_search → finalize → EnrichmentResult populated."""
    responses = [
        _Response(content=[_web_search_use(), _finalize_use()]),
    ]
    result = run_enrichment(_ctx(), _FakeClient(responses))

    assert result.proposed is True
    assert result.website == "https://acme.com"
    assert result.sic_code == "3559"
    assert result.sic_desc == "Special Industry Machinery, NEC"
    assert result.duns is None
    assert result.confidence == 0.85
    assert len(result.sources) == 2
    assert result.turns == 1


def test_multi_turn_fetch_then_finalize():
    """web_search → fetch_url → finalize across three turns."""
    responses = [
        _Response(content=[_web_search_use()]),
        _Response(content=[_fetch_use()]),
        _Response(content=[_finalize_use(confidence=0.9)]),
    ]
    result = run_enrichment(_ctx(), _FakeClient(responses))

    assert result.proposed is True
    assert result.confidence == 0.9
    assert result.turns == 3


def test_no_finalize_returns_not_proposed():
    """Agent gives up without calling finalize → proposed=False."""
    responses = [
        _Response(content=[_Block(type="text", text="I cannot identify this company.")]),
    ]
    result = run_enrichment(_ctx(), _FakeClient(responses))

    assert result.proposed is False
    assert result.last_message == "I cannot identify this company."
    assert result.turns == 1


def test_max_turns_guard():
    """Loop exits cleanly at max_turns even without finalize."""
    responses = [_Response(content=[_web_search_use()]) for _ in range(3)]
    result = run_enrichment(_ctx(), _FakeClient(responses), max_turns=3)

    assert result.proposed is False
    assert result.turns == 3
    assert "max_turns" in (result.last_message or "")


def test_finalize_with_duns():
    """DUNS is passed through when the agent finds it."""
    responses = [_Response(content=[_finalize_use(duns="123456789", confidence=0.95)])]
    result = run_enrichment(_ctx(), _FakeClient(responses))

    assert result.proposed is True
    assert result.duns == "123456789"


def test_finalize_null_fields():
    """Agent can finalize with all nullable fields set to None."""
    responses = [
        _Response(content=[
            _finalize_use(
                website=None, sic_code=None, sic_desc=None,
                duns=None, confidence=0.3, sources=[],
            ),
        ]),
    ]
    result = run_enrichment(_ctx(), _FakeClient(responses))

    assert result.proposed is True
    assert result.website is None
    assert result.sic_code is None
    assert result.confidence == 0.3


def test_company_name_in_brief():
    """The initial brief includes the company name and notice context."""
    captured: list[dict] = []

    class _CapturingClient:
        def create(self, *, messages, **_: Any) -> _Response:
            captured.extend(messages)
            return _Response(content=[_finalize_use()])

    run_enrichment(
        _ctx(
            company_name="Widget Corp",
            notices=[
                {"state": "TX", "layoff_count": 100, "notice_date": "2026-03-01"},
            ],
        ),
        _CapturingClient(),
    )

    brief = captured[0]["content"][0]["text"]
    assert "Widget Corp" in brief
    assert "TX" in brief
    assert "100" in brief
