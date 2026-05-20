"""Shared test fixtures: in-memory SQLite DB + golden CA xlsx."""
from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import date

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import warn_v2.db.session as db_session
from warn_v2.db.models import Base


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session_factory(db_engine, monkeypatch: pytest.MonkeyPatch) -> sessionmaker[Session]:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", db_engine)
    monkeypatch.setattr(db_session, "_session_factory", factory)
    return factory


@pytest.fixture
def db(db_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = db_session_factory()
    try:
        yield session
    finally:
        session.close()


# ----- CA golden fixture -----

_CA_GOLDEN_ROWS = [
    ("Acme Robotics Inc", "Alameda", date(2026, 1, 15), date(2026, 3, 15),
     "Layoff", 250, "1 Main St, Oakland, CA 94607"),
    ("Beta Foods LLC", "Los Angeles", date(2026, 2, 1), date(2026, 4, 1),
     "Closure", 75, "200 Sunset Blvd, Los Angeles, CA 90028"),
    ("Cascade Logistics", "San Diego", date(2026, 2, 10), date(2026, 4, 10),
     "Layoff", 120, "500 Harbor Dr, San Diego, CA 92101"),
    ("Delta Semi Corp", "Santa Clara", date(2026, 3, 5), date(2026, 5, 4),
     "Layoff", 800, "1100 Tech Pkwy, San Jose, CA 95110"),
    ("Echo Retail Stores", "Orange", date(2026, 3, 20), date(2026, 5, 19),
     "Closure", 45, "75 Fashion Way, Anaheim, CA 92802"),
    ("Foxtrot Media", "San Francisco", date(2026, 4, 1), date(2026, 5, 31),
     "Layoff", 60, "300 Market St, San Francisco, CA 94103"),
    ("Gamma BioTech", "San Mateo", date(2026, 4, 10), date(2026, 6, 9),
     "Layoff", 30, "12 Genome Ct, Foster City, CA 94404"),
    ("Helios Solar Manufacturing", "Riverside", date(2026, 4, 22), date(2026, 6, 21),
     "Layoff", 410, "9000 Sunrise Rd, Riverside, CA 92501"),
    ("Indigo Apparel Co", "Sacramento", date(2026, 5, 1), date(2026, 6, 30),
     "Closure", 22, "1 Capitol Ave, Sacramento, CA 95814"),
    ("Juno Restaurants Group", "San Bernardino", date(2026, 5, 5), date(2026, 7, 4),
     "Layoff", 180, "450 Citrus St, Ontario, CA 91761"),
    ("Krypton Cloud Services", "Santa Clara", date(2026, 5, 10), date(2026, 7, 9),
     "Layoff", 95, "10 Datacenter Way, Sunnyvale, CA 94089"),
]


@pytest.fixture
def ca_golden_xlsx_bytes() -> bytes:
    """Build a CA-shaped XLSX in memory, mimicking the EDD report.

    The real file has two preamble rows before the header; we replicate that so
    the scraper's header-detection logic is exercised.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "WARN Report"
    ws.append(["State of California - EDD - WARN Report"])
    ws.append(["Generated for testing"])
    ws.append([
        "Company",
        "County/Parish",
        "Notice Date",
        "Effective Date",
        "Layoff/Closure",
        "No. Of Employees",
        "Address",
    ])
    for r in _CA_GOLDEN_ROWS:
        ws.append(list(r))
    ws.append(["", "", "", "", "", "", ""])
    ws.append(["Total notices: 11", "", "", "", "", "", ""])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def ca_golden_expected() -> dict:
    return {
        "row_count": len(_CA_GOLDEN_ROWS),
        "first_employer": "Acme Robotics Inc",
        "first_notice_date": "2026-01-15",
        "first_zip": "94607",
        "total_layoffs": sum(r[5] for r in _CA_GOLDEN_ROWS),
    }
