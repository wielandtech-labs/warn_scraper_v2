"""Shared test fixtures: in-memory SQLite DB + golden CA xlsx."""
from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import date

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import warn_v2.db.session as db_session
from warn_v2.db.models import Base


@pytest.fixture
def db_engine():
    # StaticPool + check_same_thread=False lets TestClient (which runs the ASGI
    # app in a worker thread) share the same in-memory SQLite connection.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


# ----- TX golden fixture -----
# TX schema: JOB_SITE_NAME, COUNTY_NAME, CITY_NAME, NOTICE_DATE, LayOff_Date,
# WFDD_RECEIVED_DATE, TOTAL_LAYOFF_NUMBER, WDA_NAME

_TX_GOLDEN_ROWS = [
    ("Lone Star Refrigeration", "Harris", "Houston",
     date(2026, 1, 12), date(2026, 3, 13), date(2026, 1, 10), 145, "Gulf Coast WDA"),
    ("Bayou Marine Logistics", "Galveston", "Galveston",
     date(2026, 1, 22), date(2026, 3, 23), date(2026, 1, 20), 60, "Gulf Coast WDA"),
    ("Sundown Energy Holdings", "Midland", "Midland",
     date(2026, 2, 5), date(2026, 4, 6), date(2026, 2, 3), 220, "Permian Basin WDA"),
    ("Capitol Construction Corp", "Travis", "Austin",
     date(2026, 2, 18), date(2026, 4, 19), date(2026, 2, 17), 95, "Capital Area WDA"),
    ("Pecos Plant Foods", "Reeves", "Pecos",
     date(2026, 3, 3), date(2026, 5, 2), date(2026, 3, 1), 38, "Permian Basin WDA"),
    ("Brazos Apparel Manufacturing", "McLennan", "Waco",
     date(2026, 3, 20), date(2026, 5, 19), date(2026, 3, 18), 410, "Heart of Texas WDA"),
    ("Dallas Forklift Services", "Dallas", "Dallas",
     date(2026, 4, 4), date(2026, 6, 3), date(2026, 4, 2), 75, "Dallas WDA"),
    ("San Antonio Hospitality Group", "Bexar", "San Antonio",
     date(2026, 4, 15), date(2026, 6, 14), date(2026, 4, 13), 180, "Alamo WDA"),
    ("Tyler Manufacturing Inc", "Smith", "Tyler",
     date(2026, 4, 28), date(2026, 6, 27), date(2026, 4, 26), 64, "East Texas WDA"),
    ("Lubbock Logistics Partners", "Lubbock", "Lubbock",
     date(2026, 5, 7), date(2026, 7, 6), date(2026, 5, 5), 50, "South Plains WDA"),
    ("Houston Retail Holdings", "Harris", "Houston",
     date(2026, 5, 15), date(2026, 7, 14), date(2026, 5, 13), 290, "Gulf Coast WDA"),
    ("El Paso Distribution Center", "El Paso", "El Paso",
     date(2026, 5, 18), date(2026, 7, 17), date(2026, 5, 16), 132, "Borderplex WDA"),
]


@pytest.fixture
def tx_golden_xlsx_bytes() -> bytes:
    """A TX-shaped XLSX, with header on row 0 (TWC publishes a clean sheet)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "WARN_Act_Listings"
    ws.append([
        "JOB_SITE_NAME",
        "COUNTY_NAME",
        "CITY_NAME",
        "NOTICE_DATE",
        "LayOff_Date",
        "WFDD_RECEIVED_DATE",
        "TOTAL_LAYOFF_NUMBER",
        "WDA_NAME",
    ])
    for r in _TX_GOLDEN_ROWS:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def tx_golden_expected() -> dict:
    return {
        "row_count": len(_TX_GOLDEN_ROWS),
        "first_employer": "Lone Star Refrigeration",
        "first_notice_date": "2026-01-12",
        "first_city": "Houston",
        "total_layoffs": sum(r[6] for r in _TX_GOLDEN_ROWS),
    }
