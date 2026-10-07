from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states.mn import _parse_pdf

FIXTURES = Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "mn"
# Trimmed live capture of DEED's Layoff Resources page (2026-10-07).
PAGE = FIXTURES / "layoff_resources_2026-10.html"
# Monthly-report payload (May 2025 PDF) — the historical backfill's 2025+ parser.
MONTHLY = FIXTURES / "sample.json"


@pytest.fixture
def mn_rows():
    return get_scraper("MN").parse(PAGE.read_bytes())


def test_mn_parses_warn_notice_list(mn_rows) -> None:
    assert all(r.state == "MN" for r in mn_rows)
    assert all(r.employer and r.notice_date for r in mn_rows)
    # 31 list entries minus 3 "(Revision)" re-filings of listed originals.
    assert len(mn_rows) == 28
    newest = max(mn_rows, key=lambda r: r.notice_date)
    assert (newest.employer, newest.notice_date) == ("Newport Healthcare", date(2026, 9, 30))


def test_mn_reaches_past_the_stale_monthly_reports(mn_rows) -> None:
    """Regression: the monthly-report source topped out at 2026-04-23 in prod."""
    by_name = {r.employer: r for r in mn_rows}
    assert by_name["Heliene USA, Inc."].notice_date == date(2026, 8, 5)
    assert by_name["UCare"].notice_date == date(2026, 8, 3)
    assert by_name["Medtronic, Inc."].notice_date == date(2026, 9, 25)
    assert sum(r.notice_date > date(2026, 4, 23) for r in mn_rows) == 20


def test_mn_links_the_notice_pdf(mn_rows) -> None:
    ucare = next(r for r in mn_rows if r.employer == "UCare")
    assert ucare.raw_notice_url == (
        "https://mn.gov/deed/assets/warn-2026-ucare_tcm1045-762701.pdf"
    )
    assert ucare.source_url == "https://mn.gov/deed/business/layoff-resources/"
    # Only the WARN Notices accordion: no monthly reports or sample letters.
    assert not any("plant-closing" in r.raw_notice_url for r in mn_rows)
    assert not any("sample-warn" in r.raw_notice_url for r in mn_rows)


def test_mn_dates_and_nbsp_cleanup(mn_rows) -> None:
    by_name = {r.employer: r for r in mn_rows}
    # Two-digit years ("2/24/26") and NBSP-padded names/dates.
    assert by_name["Estee Lauder Companies, Inc."].notice_date == date(2026, 2, 24)
    assert by_name["Chartwells - Southwest Minnesota State"].notice_date == date(2026, 4, 24)


def test_mn_revisions_collapse_onto_the_original(mn_rows) -> None:
    pearsons = [r for r in mn_rows if r.employer.startswith("Pearson's")]
    assert [(r.employer, r.notice_date) for r in pearsons] == [
        ("Pearson's Candy Company", date(2026, 7, 30))
    ]
    assert not any("Revision" in r.employer for r in mn_rows)
    # A revision with no listed original ("3/24/26 Revised") is the only record.
    nilfisk = next(r for r in mn_rows if r.employer == "Nilfisk Inc.")
    assert nilfisk.notice_date == date(2026, 3, 24)


def test_mn_validation_passes(mn_rows) -> None:
    result = validate(get_scraper("MN"), mn_rows)
    assert result.ok, result.reason


def test_mn_raises_without_warn_section() -> None:
    """A bot-challenge page (or a redesign) must fail loudly, not parse to 0 rows."""
    with pytest.raises(ParseFailed):
        get_scraper("MN").parse(b"<html><body>Please verify you are human</body></html>")


def test_mn_monthly_report_parser_still_works() -> None:
    """The monthly-PDF chain is kept for backfill-historical (2025+ files)."""
    payload = json.loads(MONTHLY.read_bytes())
    rows = [
        row
        for entry in payload["pdfs"]
        for row in _parse_pdf(base64.b64decode(entry["pdf_b64"]), entry["url"])
    ]
    assert rows
    assert all(r.employer and r.notice_date for r in rows)
    assert any(r.layoff_count is not None for r in rows)
