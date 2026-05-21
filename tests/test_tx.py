from datetime import date

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.registry import get_scraper


def test_tx_parses_golden_fixture(tx_golden_xlsx_bytes, tx_golden_expected) -> None:
    scraper = get_scraper("TX")
    rows = scraper.parse(tx_golden_xlsx_bytes)

    assert len(rows) == tx_golden_expected["row_count"]
    first = rows[0]
    assert first.state == "TX"
    assert first.employer == tx_golden_expected["first_employer"]
    assert first.notice_date == date.fromisoformat(tx_golden_expected["first_notice_date"])
    assert first.city == tx_golden_expected["first_city"]
    assert first.county == "Harris"
    assert first.layoff_count == 145

    total = sum(r.layoff_count or 0 for r in rows)
    assert total == tx_golden_expected["total_layoffs"]


def test_tx_validation_passes(tx_golden_xlsx_bytes) -> None:
    scraper = get_scraper("TX")
    rows = scraper.parse(tx_golden_xlsx_bytes)
    result = validate(scraper, rows)
    assert result.ok, result.reason
