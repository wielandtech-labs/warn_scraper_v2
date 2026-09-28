"""Thin client for the BLS public timeseries API.

Extracted from ``warn_v2.reports.bls`` so the weekly narrative generator and
the ``fetch-bls`` ingestion job share one fetcher. Handles the two limits that
shape every caller: how many series fit in a request, and how many years.

``BLS_API_KEY`` (free registration) lifts the v2 limits from 10 series / 10
years / 25 queries per day to 50 / 20 / 500. The key is read from the
environment on every call rather than at import, so tests can set and clear it.
"""
from __future__ import annotations

import os

import httpx

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# Per-request caps, unkeyed and keyed.
_MAX_SERIES_UNKEYED = 10
_MAX_SERIES_KEYED = 50
_MAX_YEARS_UNKEYED = 10
_MAX_YEARS_KEYED = 20


def max_series_per_query() -> int:
    """Series that fit in one request, given the current key state."""
    return _MAX_SERIES_KEYED if os.getenv("BLS_API_KEY") else _MAX_SERIES_UNKEYED


def max_years_per_query() -> int:
    """Years that fit in one request, given the current key state."""
    return _MAX_YEARS_KEYED if os.getenv("BLS_API_KEY") else _MAX_YEARS_UNKEYED


def year_windows(start_year: int, end_year: int) -> list[tuple[int, int]]:
    """Split an inclusive year range into windows the API will accept."""
    span = max_years_per_query()
    return [
        (y, min(y + span - 1, end_year))
        for y in range(start_year, end_year + 1, span)
    ]


def fetch_series(
    client: httpx.Client, series_ids: list[str], start_year: int, end_year: int
) -> dict[str, dict[str, float]]:
    """Return {series_id: {"YYYY-MM": value}} for the requested span."""
    out: dict[str, dict[str, float]] = {}
    key = os.getenv("BLS_API_KEY")
    chunk_size = max_series_per_query()
    for i in range(0, len(series_ids), chunk_size):
        body: dict = {
            "seriesid": series_ids[i : i + chunk_size],
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        if key:
            body["registrationkey"] = key
        resp = client.post(BLS_API_URL, json=body)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS API status {payload.get('status')}: "
                               f"{payload.get('message')}")
        for series in payload.get("Results", {}).get("series", []):
            points: dict[str, float] = {}
            for row in series.get("data", []):
                period = row.get("period", "")
                if not period.startswith("M") or period == "M13":  # M13 = annual
                    continue
                try:
                    value = float(row["value"])
                except ValueError:  # BLS placeholder for unavailable, e.g. "-"
                    continue
                points[f"{row['year']}-{period[1:]}"] = value
            out[series["seriesID"]] = points
    return out
