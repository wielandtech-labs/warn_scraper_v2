"""Tests for the /api/reports routes."""
from __future__ import annotations

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
