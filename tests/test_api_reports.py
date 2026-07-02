"""Tests for the /api/reports routes."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from warn_v2.api.routes import reports as reports_mod


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from warn_v2.api import app

    monkeypatch.setattr(reports_mod, "_REPORTS_DIR", tmp_path)
    return TestClient(app, raise_server_exceptions=True)


def test_get_report_ok(client, tmp_path):
    (tmp_path / "CA.md").write_text("# California report\n", encoding="utf-8")
    resp = client.get("/api/reports/ca")  # case-insensitive
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.text == "# California report\n"


def test_get_report_missing_file(client):
    resp = client.get("/api/reports/CA")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Report not available"


def test_get_report_unknown_state_and_traversal(client, tmp_path):
    (tmp_path / "CA.md").write_text("x", encoding="utf-8")
    assert client.get("/api/reports/ZZ").status_code == 404
    assert client.get("/api/reports/..").status_code == 404
    assert client.get("/api/reports/%2e%2e%2fCA").status_code == 404


def test_list_reports(client, tmp_path):
    (tmp_path / "CA.md").write_text("x", encoding="utf-8")
    (tmp_path / "TX.md").write_text("x", encoding="utf-8")
    (tmp_path / "README.md").write_text("not a state", encoding="utf-8")
    (tmp_path / "CA.md.tmp").write_text("in-flight write", encoding="utf-8")

    resp = client.get("/api/reports")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["state"] for r in body] == ["CA", "TX"]
    assert body[0]["state_name"] == "California"
    assert body[0]["generated_at"]


def test_list_reports_empty_or_missing_dir(client, tmp_path, monkeypatch):
    resp = client.get("/api/reports")  # dir exists but is empty
    assert resp.status_code == 200
    assert resp.json() == []

    monkeypatch.setattr(reports_mod, "_REPORTS_DIR", tmp_path / "nope")
    resp = client.get("/api/reports")  # dir doesn't exist (job never ran)
    assert resp.status_code == 200
    assert resp.json() == []


def test_national_report_listed_and_served(client, tmp_path):
    (tmp_path / "US.md").write_text("# United States report\n", encoding="utf-8")
    (tmp_path / "CA.md").write_text("x", encoding="utf-8")

    resp = client.get("/api/reports")
    body = resp.json()
    assert [r["state"] for r in body] == ["CA", "US"]
    assert body[1]["state_name"] == "United States"

    resp = client.get("/api/reports/us")  # case-insensitive like states
    assert resp.status_code == 200
    assert resp.text == "# United States report\n"


def test_industry_files_not_in_state_listing(client, tmp_path):
    (tmp_path / "CA.md").write_text("x", encoding="utf-8")
    (tmp_path / "industry_31-33.md").write_text("x", encoding="utf-8")
    body = client.get("/api/reports").json()
    assert [r["state"] for r in body] == ["CA"]


_SCORECARDS = [
    {
        "sector": "31-33",
        "sector_name": "Manufacturing",
        "score": 12,
        "grade": "F",
        "cur_layoffs": 500,
        "prior_layoffs": 200,
        "cur_notices": 10,
        "delta_pct": 150.0,
    },
    {
        "sector": "92",
        "sector_name": "Public Administration",
        "score": None,
        "grade": "N/A",
        "cur_layoffs": 0,
        "prior_layoffs": 0,
        "cur_notices": 0,
        "delta_pct": None,
    },
]


def test_industry_scorecard_listing(client, tmp_path):
    (tmp_path / "industries.json").write_text(json.dumps(_SCORECARDS), encoding="utf-8")
    resp = client.get("/api/reports/industries")
    assert resp.status_code == 200  # would be 404 "Unknown state" if /{state} swallowed it
    body = resp.json()
    assert [r["sector"] for r in body] == ["31-33", "92"]
    assert body[0]["grade"] == "F"
    assert body[1]["score"] is None
    assert body[0]["generated_at"]


def test_industry_scorecard_listing_missing_file(client):
    resp = client.get("/api/reports/industries")
    assert resp.status_code == 200
    assert resp.json() == []


def test_industry_scorecard_listing_tolerates_stale_rows(client, tmp_path):
    # The PVC file can be a week older than the running code — rows the
    # current model can't parse are skipped, never a 500.
    rows = [_SCORECARDS[0], {"sector": "92"}]  # second row missing required keys
    (tmp_path / "industries.json").write_text(json.dumps(rows), encoding="utf-8")
    resp = client.get("/api/reports/industries")
    assert resp.status_code == 200
    assert [r["sector"] for r in resp.json()] == ["31-33"]


def test_industry_scorecard_listing_corrupt_json(client, tmp_path):
    (tmp_path / "industries.json").write_text("not json", encoding="utf-8")
    resp = client.get("/api/reports/industries")
    assert resp.status_code == 200
    assert resp.json() == []


def test_industry_report_served(client, tmp_path):
    (tmp_path / "industry_31-33.md").write_text("# Manufacturing scorecard\n", encoding="utf-8")
    resp = client.get("/api/reports/industries/31-33")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.text == "# Manufacturing scorecard\n"


def test_industry_report_unknown_sector_and_traversal(client, tmp_path):
    (tmp_path / "industry_31-33.md").write_text("x", encoding="utf-8")
    assert client.get("/api/reports/industries/ZZ").status_code == 404
    # A bare ".." is path-normalized away by clients before routing; the
    # encoded form reaches the handler as a path param and must be rejected.
    assert client.get("/api/reports/industries/%2e%2e%2f31-33").status_code == 404
