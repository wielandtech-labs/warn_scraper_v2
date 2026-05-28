from datetime import date

from warn_v2.pipeline.storage import upsert_notices
from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.registry import get_scraper


def test_ca_parses_golden_fixture(ca_golden_xlsx_bytes, ca_golden_expected) -> None:
    scraper = get_scraper("CA")
    rows = scraper.parse(ca_golden_xlsx_bytes)

    assert len(rows) == ca_golden_expected["row_count"]

    first = rows[0]
    assert first.state == "CA"
    assert first.employer == ca_golden_expected["first_employer"]
    assert first.notice_date == date.fromisoformat(
        ca_golden_expected["first_notice_date"]
    )
    assert first.zip == ca_golden_expected["first_zip"]
    # Address from the source spreadsheet should be promoted to first-class field.
    assert first.address == "1 Main St, Oakland, CA 94607"

    total_layoffs = sum(r.layoff_count or 0 for r in rows)
    assert total_layoffs == ca_golden_expected["total_layoffs"]


def test_ca_golden_fixture_passes_validation(ca_golden_xlsx_bytes) -> None:
    scraper = get_scraper("CA")
    rows = scraper.parse(ca_golden_xlsx_bytes)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ca_end_to_end_persists(ca_golden_xlsx_bytes, db) -> None:
    scraper = get_scraper("CA")
    rows = scraper.parse(ca_golden_xlsx_bytes)
    seen, new = upsert_notices(db, rows)
    db.commit()
    assert seen == new == len(rows)

    # Idempotent re-run
    seen2, new2 = upsert_notices(db, rows)
    db.commit()
    assert (seen2, new2) == (len(rows), 0)
