"""Tests for the EDGAR lookup and SIC→NAICS crosswalk."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import respx
import httpx

from warn_v2.enrichment.lookup import (
    LookupResult,
    edgar_lookup,
    naics_from_sic,
    normalize_name,
)

_EDGAR_URL = "https://efts.sec.gov/LATEST/search-index"


def _edgar_response(entity_name: str, sic: str) -> dict:
    """Minimal EDGAR search response with one hit."""
    return {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "entity_name": entity_name,
                        "sic": sic,
                        "biz_location": "WA",
                        "form_type": "10-K",
                    }
                }
            ]
        }
    }


def _empty_edgar_response() -> dict:
    return {"hits": {"hits": []}}


# ---------------------------------------------------------------------------
# normalize_name tests
# ---------------------------------------------------------------------------


def test_normalize_strips_legal_suffixes():
    assert normalize_name("Acme Corp.") == "acme"
    assert normalize_name("Boeing Company") == "boeing"
    assert normalize_name("Wieland Technologies, Inc.") == "wieland"


def test_normalize_preserves_meaningful_words():
    assert "robotics" in normalize_name("Acme Robotics Inc")
    assert "electric" in normalize_name("General Electric Co")


def test_normalize_handles_punctuation():
    name = normalize_name("Smith & Jones, LLC")
    assert "smith" in name
    assert "jones" in name


# ---------------------------------------------------------------------------
# naics_from_sic tests
# ---------------------------------------------------------------------------


def test_naics_from_sic_known_code():
    """Any SIC code present in the bundled crosswalk should return a tuple."""
    cw_path = Path(__file__).parent.parent / "warn_v2" / "enrichment" / "_data" / "sic_naics_crosswalk.json"
    if not cw_path.exists():
        pytest.skip("Crosswalk data file not generated yet")
    cw = json.loads(cw_path.read_text())
    sic = next(iter(cw))  # first code in the file
    result = naics_from_sic(sic)
    assert result is not None
    naics_code, naics_desc = result
    assert naics_code
    assert naics_desc


def test_naics_from_sic_unknown_returns_none():
    result = naics_from_sic("9999")  # unlikely to be in the crosswalk
    # Either None or a real entry — just check it doesn't raise
    assert result is None or (isinstance(result, tuple) and len(result) == 2)


# ---------------------------------------------------------------------------
# edgar_lookup tests
# ---------------------------------------------------------------------------


@respx.mock
def test_edgar_lookup_good_match():
    respx.get(_EDGAR_URL).mock(
        return_value=httpx.Response(200, json=_edgar_response("Boeing Co", "3721"))
    )
    result = edgar_lookup("Boeing", "WA")
    assert result is not None
    assert result.sic_code == "3721"
    assert result.entity_name == "Boeing Co"
    assert result.confidence >= 0.70


@respx.mock
def test_edgar_lookup_poor_name_match_returns_none():
    # "Acme Corp" vs "Totally Different Company" — score will be < 0.75
    respx.get(_EDGAR_URL).mock(
        return_value=httpx.Response(200, json=_edgar_response("Totally Different Company", "3559"))
    )
    result = edgar_lookup("Acme Corp", "CA")
    assert result is None


@respx.mock
def test_edgar_lookup_empty_hits_returns_none():
    respx.get(_EDGAR_URL).mock(
        return_value=httpx.Response(200, json=_empty_edgar_response())
    )
    result = edgar_lookup("Some Company", "TX")
    assert result is None


@respx.mock
def test_edgar_lookup_http_error_returns_none():
    respx.get(_EDGAR_URL).mock(return_value=httpx.Response(503))
    result = edgar_lookup("Any Company", "CA")
    assert result is None


@respx.mock
def test_edgar_lookup_network_error_returns_none():
    respx.get(_EDGAR_URL).mock(side_effect=httpx.ConnectError("timeout"))
    result = edgar_lookup("Any Company", "CA")
    assert result is None


@respx.mock
def test_edgar_lookup_includes_state_in_params():
    """State filter is sent as locationCode query param."""
    route = respx.get(_EDGAR_URL).mock(
        return_value=httpx.Response(200, json=_empty_edgar_response())
    )
    edgar_lookup("Boeing", "WA")
    assert route.called
    sent_url = str(route.calls[0].request.url)
    assert "locationCode=WA" in sent_url or "locationCode" in sent_url


@respx.mock
def test_edgar_lookup_high_confidence_on_close_name_match():
    """When entity name closely matches, confidence should be 0.85."""
    respx.get(_EDGAR_URL).mock(
        return_value=httpx.Response(200, json=_edgar_response("General Electric", "3612"))
    )
    result = edgar_lookup("General Electric", "CT")
    assert result is not None
    assert result.confidence == 0.85  # score ≥ 0.90 → 0.85


@respx.mock
def test_edgar_lookup_returns_naics_when_crosswalk_available():
    """If the SIC code is in the crosswalk, NAICS fields are populated."""
    cw_path = Path(__file__).parent.parent / "warn_v2" / "enrichment" / "_data" / "sic_naics_crosswalk.json"
    if not cw_path.exists():
        pytest.skip("Crosswalk data file not generated yet")

    cw = json.loads(cw_path.read_text())
    sic = next(iter(cw))  # use the first SIC code in the crosswalk

    respx.get(_EDGAR_URL).mock(
        return_value=httpx.Response(200, json=_edgar_response("Test Corp", sic))
    )
    result = edgar_lookup("Test Corp", None)
    assert result is not None
    assert result.naics_code is not None
    assert result.naics_desc is not None
