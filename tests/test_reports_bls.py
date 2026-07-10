"""Tests for the BLS macro-context fetcher (respx-mocked, no network)."""
from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
import respx

from warn_v2.reports.bls import (
    BLS_API_URL,
    NATIONAL_PAYROLL_SERIES,
    UNEMPLOYMENT_SERIES,
    fetch_bls_context,
)

AS_OF = date(2026, 7, 10)


def _series(series_id: str, points: dict[str, str]) -> dict:
    """points: {"YYYY-MM": value} (M13 rows added by the caller if needed)."""
    return {
        "seriesID": series_id,
        "data": [
            {"year": ym[:4], "period": f"M{ym[5:]}", "value": v}
            for ym, v in points.items()
        ],
    }


def _ok_response(series: list[dict]) -> dict:
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": series}}


@respx.mock
def test_fetch_builds_monthly_changes_and_unemployment():
    respx.post(BLS_API_URL).respond(
        json=_ok_response(
            [
                _series(
                    NATIONAL_PAYROLL_SERIES,
                    {"2026-04": "158800", "2026-05": "158900.5", "2026-06": "158984"},
                ),
                _series(UNEMPLOYMENT_SERIES, {"2026-05": "4.1", "2026-06": "4.2"}),
                _series("CES3000000001", {"2026-05": "12600", "2026-06": "12598"}),
            ]
        )
    )
    ctx = fetch_bls_context(["31-33"], as_of=AS_OF)
    assert ctx is not None
    national = ctx["national"]
    # Change needs a prior month: 2026-04 has none in the fetched span.
    assert national["payroll_change_thousands_by_month"] == {
        "2026-05": 100.5,
        "2026-06": 83.5,
    }
    assert national["unemployment_rate"] == {"month": "2026-06", "value": 4.2}
    mfg = ctx["sectors"]["31-33"]
    assert mfg["industry"] == "Manufacturing"
    assert mfg["payroll_change_thousands_by_month"] == {"2026-06": -2.0}


@respx.mock
def test_fetch_skips_annual_m13_rows():
    respx.post(BLS_API_URL).respond(
        json=_ok_response(
            [
                {
                    "seriesID": NATIONAL_PAYROLL_SERIES,
                    "data": [
                        {"year": "2026", "period": "M13", "value": "999999"},
                        {"year": "2026", "period": "M05", "value": "158900"},
                        {"year": "2026", "period": "M06", "value": "158984"},
                    ],
                },
            ]
        )
    )
    ctx = fetch_bls_context([], as_of=AS_OF)
    assert ctx["national"]["payroll_change_thousands_by_month"] == {"2026-06": 84.0}
    assert "unemployment_rate" not in ctx["national"]


@respx.mock
def test_fetch_skips_placeholder_values():
    # The live API returns "-" for months without data yet (seen 2026-07-10).
    respx.post(BLS_API_URL).respond(
        json=_ok_response(
            [
                _series(
                    NATIONAL_PAYROLL_SERIES,
                    {"2026-05": "158900", "2026-06": "158984", "2026-07": "-"},
                ),
            ]
        )
    )
    ctx = fetch_bls_context([], as_of=AS_OF)
    assert ctx["national"]["payroll_change_thousands_by_month"] == {"2026-06": 84.0}


@respx.mock
def test_fetch_fail_open_on_transport_error():
    respx.post(BLS_API_URL).mock(side_effect=httpx.ConnectError("down"))
    assert fetch_bls_context(["31-33"], as_of=AS_OF) is None


@respx.mock
def test_fetch_fail_open_on_api_error_status():
    respx.post(BLS_API_URL).respond(
        json={"status": "REQUEST_NOT_PROCESSED", "message": ["daily limit"]}
    )
    assert fetch_bls_context(["31-33"], as_of=AS_OF) is None


@respx.mock
def test_fetch_fail_open_when_national_series_missing():
    respx.post(BLS_API_URL).respond(json=_ok_response([]))
    assert fetch_bls_context(["31-33"], as_of=AS_OF) is None


@respx.mock
def test_sector_without_ces_coverage_is_omitted():
    respx.post(BLS_API_URL).respond(
        json=_ok_response(
            [_series(NATIONAL_PAYROLL_SERIES, {"2026-05": "158900", "2026-06": "158984"})]
        )
    )
    ctx = fetch_bls_context(["11"], as_of=AS_OF)  # Agriculture: no CES series
    assert ctx is not None
    assert ctx["sectors"] == {}


@respx.mock
def test_unkeyed_requests_chunk_to_ten_series(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BLS_API_KEY", raising=False)
    route = respx.post(BLS_API_URL).respond(
        json=_ok_response(
            [_series(NATIONAL_PAYROLL_SERIES, {"2026-05": "158900", "2026-06": "158984"})]
        )
    )
    # All sectors -> 14 unique CES series + 2 national = 16 -> two chunks.
    all_sectors = ["21", "22", "23", "31-33", "42", "44-45", "48-49", "51", "52",
                   "53", "54", "55", "56", "61", "62", "71", "72", "81", "92"]
    ctx = fetch_bls_context(all_sectors, as_of=AS_OF)
    assert ctx is not None
    assert route.call_count == 2
    for call in route.calls:
        assert len(json.loads(call.request.content)["seriesid"]) <= 10
