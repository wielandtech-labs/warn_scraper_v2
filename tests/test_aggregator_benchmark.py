"""Tests for the aggregator coverage benchmark (scripts/aggregator_benchmark.py).

Only the pure parse and diff helpers are covered; fetching is thin httpx glue.
"""
from __future__ import annotations

import pytest

from warn_v2.scripts.aggregator_benchmark import (
    Gap,
    find_gaps,
    parse_trend_chart,
    reference_slug,
)

# Trimmed from a real laborcurrent.com/layoffs/ohio page: quarterly buckets
# then monthly ones, with the "WARN Notices" dataset first.
_PAGE = """<canvas id="state-ohio-trend"></canvas><script>
new Chart(document.getElementById('state-ohio-trend'), {
  type: 'line',
  data: {
    labels: ["Q3 2024", "Q4 2024", "Nov 2024", "Dec 2024", "Jan 2025"],
    datasets: [{"label": "WARN Notices", "data": [20, 10, 7, 5, 9], "fill": true},
               {"label": "Workers Affected", "data": [900, 400, 300, 200, 500]}]
  },
});
</script>"""


def test_parse_trend_chart_sums_quarters_and_months_by_year():
    assert parse_trend_chart(_PAGE, "ohio") == {2024: 42, 2025: 9}


def test_parse_trend_chart_none_without_chart():
    assert parse_trend_chart("<main>no data</main>", "wyoming") is None


def test_parse_trend_chart_rejects_mismatched_lengths():
    broken = _PAGE.replace('[20, 10, 7, 5, 9]', "[20, 10]")
    with pytest.raises(ValueError, match="labels vs"):
        parse_trend_chart(broken, "ohio")


def test_reference_slug_multiword():
    assert reference_slug("DC") == "district-of-columbia"
    assert reference_slug("NH") == "new-hampshire"


def test_find_gaps_threshold_and_zero_years():
    ours = {"OH": {2024: 93, 2025: 0}, "PA": {2023: 70}}
    reference = {"OH": {2024: 103, 2025: 97, 2026: 4}, "PA": {2023: 73}, "GA": {2001: 216}}
    gaps = find_gaps(ours, reference, min_gap=10)
    assert gaps == [
        Gap("GA", 2001, 0, 216),
        Gap("OH", 2024, 93, 103),
        Gap("OH", 2025, 0, 97),
        Gap("OH", 2026, 0, 4),  # zero year: listed despite the small shortfall
    ]
    assert gaps[0].shortfall == 216


def test_get_waits_out_429(monkeypatch):
    import httpx

    from warn_v2.scripts import aggregator_benchmark as ab

    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json=[])

    slept = []
    monkeypatch.setattr(ab.time, "sleep", slept.append)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert ab._get(client, "https://example.test/x").status_code == 200
    assert slept == [3.0]
    assert len(calls) == 2
