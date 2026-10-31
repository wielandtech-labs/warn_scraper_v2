"""Closure-type sources found by the 2026-10-31 categorization audit, and the
``recategorize-closures`` repair for rows ingested before them."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd

from warn_v2.db.models import Notice
from warn_v2.scrapers.states.ca import _parse_df
from warn_v2.scrapers.states.nc import _parse_nc_ssrs_grid
from warn_v2.scrapers.states.tn import parse_tn_pre2017, tn_pre2017_files
from warn_v2.scripts.recategorize_closures import recategorize_closures


def test_ca_fiscal_year_pdf_type_header():
    """The FY PDFs head the column "Layoff/Closure\\nType"."""
    df = pd.DataFrame(
        [["04/25/2023", "07/03/2023", "Acme", "29", "Layoff Permanent",
          "1 Main St Pinole CA 94564"]],
        columns=["Notice\nDate", "Effective\nDate", "Company", "No. Of\nEmployees",
                 "Layoff/Closure\nType", "Address"],
    )
    assert _parse_df(df)[0].closure_type == "Layoff Permanent"


def test_nc_ssrs_2020_wrapped_type_header():
    """2020-2021 wrap the header as "Layoff/\\nClosure"."""
    header = ["County/Parish", "WARN\nNo.", "Notice\nDate", "Received\nDate",
              "Effective\nDate", "Company", "Layoff/\nClosure", "No. Of\nEmployees", "Address"]
    row = ["Randolph County", "202000001", "01/06/2020", "01/06/2020", "01/31/2020",
           "Mas US Holdings Inc", "Closure\nPermanent", "124",
           "601 E Pritchard St Asheboro NC\n27203"]
    pdf = SimpleNamespace(pages=[SimpleNamespace(extract_table=lambda: [header, row])])
    (parsed,) = _parse_nc_ssrs_grid(pdf, "http://x/2020")
    assert parsed.closure_type == "Closure Permanent"


def test_tn_archive_takes_type_from_overlapping_shtml():
    files = dict(tn_pre2017_files())
    name = "warn-report-archive_20160713151608.html"
    rows = parse_tn_pre2017(files[name], name)
    typed = [r for r in rows if r.closure_type]
    assert {r.closure_type for r in typed} == {"Closure", "Layoff"}
    assert len(typed) >= 130
    # The warnnotices capture (2014-09-15) has nothing to lend later rows.
    assert max(r.notice_date for r in typed) < date(2014, 9, 15)


def _notice(nid: str, state: str, closure_type: str | None, category: str | None = None):
    return Notice(
        notice_id=nid, state=state, employer="Acme", notice_date=date(2020, 1, 1),
        closure_type=closure_type, closure_category=category,
    )


def test_recategorize_fills_only_null_categories(db):
    db.add_all([
        _notice("a", "IL", "Shut Down"),
        _notice("b", "MD", "1"),
        _notice("c", "MD", "2 "),
        _notice("d", "DC", "1"),  # DC's codes mean the opposite; never mapped here
        _notice("e", "MS", "Layoff", "Non-WARN"),
        _notice("f", "CO", "Other"),
        _notice("g", "TX", None),
    ])
    db.commit()

    filled = recategorize_closures(db)
    db.commit()

    assert dict(filled) == {"IL": 1, "MD": 2}
    got = {n.notice_id: n.closure_category for n in db.query(Notice)}
    assert got == {
        "a": "Closure", "b": "Closure", "c": "Layoff", "d": None,
        "e": "Non-WARN", "f": None, "g": None,
    }
    assert db.get(Notice, "b").closure_type == "1"  # raw value kept
    assert not recategorize_closures(db)
