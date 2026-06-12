"""Ingest a local WARN-notice file (e.g. a public-records response) for one state.

Records-request responses (see docs/foia/) arrive as one-off CSV/XLSX/PDF files.
This command parses such a file and upserts the rows through the same path as
the scrapers, recording a ScraperRun labeled with the filename.

Parsers
-------
scraper (default)
    Parse with the state's regular ``scraper.parse()`` — many responses are
    just older copies of the format the live source publishes.
tabular
    Generic CSV/XLSX with a header row; common WARN column names (employer /
    notice date / effective date / employees affected / city / county / zip /
    address / type) are matched case-insensitively via ``ColumnMap``.
anything else
    Write a small ``parse_<st>_foia(raw)`` in the state module when the
    response arrives and register it in ``_PARSERS`` here.

Usage::

    warn-v2 ingest-file --state IA --file response.xlsx --dry-run
    warn-v2 ingest-file --state SC --file notices.csv --parser tabular
"""
from __future__ import annotations

import io
import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from warn_v2.scrapers._helpers import ColumnMap, as_date, as_int, as_str, zip_from
from warn_v2.scrapers.base import NoticeRow, ParseFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scripts.backfill_historical import _ingest_raw

log = logging.getLogger(__name__)

# Bespoke per-state parsers for records-request response formats, added as
# responses arrive: {"XX": parse_xx_foia}.
_PARSERS: dict[str, Callable[[bytes], list[NoticeRow]]] = {}

_EMPLOYER_KEYS = (
    "company", "company name", "employer", "employer name", "business name",
    "organization name", "job site name",
)
_NOTICE_DATE_KEYS = (
    "notice date", "date of notice", "date received", "received date",
    "warn received date", "wfdd received date", "warn date", "date",
)
_EFFECTIVE_DATE_KEYS = (
    "effective date", "layoff date", "effective layoff date", "closure date",
    "layoff/closure date", "first date of separation", "separation date",
)
_COUNT_KEYS = (
    "number of employees affected", "employees affected", "no. of employees",
    "affected workers", "total layoff number", "number affected",
    "workers affected", "employees",
)
_CITY_KEYS = ("city", "city name", "worksite city", "location city")
_COUNTY_KEYS = ("county", "county name", "county/parish")
_ZIP_KEYS = ("zip", "zip code", "postal code")
_ADDRESS_KEYS = ("address", "worksite address", "location address", "company address")
_TYPE_KEYS = (
    "warn type", "closure type", "layoff/closure", "notice type", "layoff type",
    "type of action", "type",
)


def _parse_tabular(raw: bytes, *, state: str, source_url: str | None) -> list[NoticeRow]:
    """Generic CSV/XLSX parser keyed on common WARN column-name synonyms."""
    try:
        df = pd.read_excel(io.BytesIO(raw))
    except Exception:
        try:
            df = pd.read_csv(io.BytesIO(raw))
        except Exception as e:
            raise ParseFailed(f"could not read file as XLSX or CSV: {e}") from e

    cols = ColumnMap(df.columns)
    if not any(cols.has(k) for k in _EMPLOYER_KEYS):
        raise ParseFailed(
            f"no employer column found (looked for {', '.join(_EMPLOYER_KEYS)}); "
            "columns: " + ", ".join(str(c) for c in df.columns)
        )

    rows: list[NoticeRow] = []
    for _, r in df.iterrows():
        employer = as_str(cols.get(r, _EMPLOYER_KEYS))
        if not employer:
            continue
        notice_date = as_date(cols.get(r, _NOTICE_DATE_KEYS))
        if notice_date is None:
            continue
        address = as_str(cols.get(r, _ADDRESS_KEYS))
        rows.append(
            NoticeRow(
                state=state,
                employer=employer,
                notice_date=notice_date,
                effective_date=as_date(cols.get(r, _EFFECTIVE_DATE_KEYS)),
                layoff_count=as_int(cols.get(r, _COUNT_KEYS)),
                closure_type=as_str(cols.get(r, _TYPE_KEYS)),
                city=as_str(cols.get(r, _CITY_KEYS)),
                county=as_str(cols.get(r, _COUNTY_KEYS)),
                zip=zip_from(cols.get(r, _ZIP_KEYS), address),
                address=address,
                source_url=source_url,
            )
        )
    return rows


def ingest_file(
    state: str,
    path: str,
    *,
    parser: str = "scraper",
    source_url: str | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Parse ``path`` with the chosen parser and upsert the rows for ``state``.

    Returns the same stats shape as backfill-historical (one "year" = this file).
    """
    state = state.upper()
    scraper = get_scraper(state)
    file = Path(path)
    raw = file.read_bytes()
    src = source_url or f"file://{file.name}"

    if parser == "scraper":
        parse_fn = None  # _ingest_raw falls back to scraper.parse
    elif parser == "tabular":
        parse_fn = lambda b: _parse_tabular(b, state=state, source_url=src)  # noqa: E731
    elif parser in _PARSERS:
        parse_fn = _PARSERS[parser]
    else:
        known = ", ".join(["scraper", "tabular", *sorted(_PARSERS)])
        raise ValueError(f"unknown parser {parser!r}; known parsers: {known}")

    stats: dict[str, int] = {
        "years_attempted": 1,
        "years_ok": 0,
        "rows_seen": 0,
        "rows_new": 0,
    }
    _ingest_raw(scraper, raw, label=file.name, stats=stats, dry_run=dry_run, parse_fn=parse_fn)
    return stats
