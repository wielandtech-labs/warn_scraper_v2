"""Tests for the share-card renderer (warn_v2.api.og_cards) and /og routes."""
from __future__ import annotations

import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from warn_v2.api import og_cards
from warn_v2.api.routes import og as og_route
from warn_v2.api.seo import page_meta_for_path, render_index
from warn_v2.db.models import Notice


def _png(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    assert img.format == "PNG"
    return img


# ----- path parser -----

def test_parse_relative_and_absolute_commands():
    polys = og_cards.parse_path("m 10,10 h 5 v 5 l -5,0 z M 100,100 L 110,100 110,110 Z")
    assert polys == [
        [(10, 10), (15, 10), (15, 15), (10, 15)],
        # Implicit lineto after the L: "110,110" continues the line.
        [(100, 100), (110, 100), (110, 110)],
    ]


def test_implicit_lineto_after_moveto():
    # Numbers after an m continue as relative linetos.
    assert og_cards.parse_path("m 0,0 10,0 0,10 z") == [[(0, 0), (10, 0), (10, 10)]]


def test_every_state_path_parses_to_polygons():
    for code, d in og_cards.state_paths().items():
        polys = og_cards.parse_path(d)
        assert polys and all(len(p) >= 3 for p in polys), code


# ----- rendering -----

def test_state_card_is_1200x630_png():
    yearly = [("2020", 10), ("2021", 5)]
    img = _png(og_cards.render_state_card("TX", "Texas", 513_883, 5_468, yearly))
    assert img.size == (1200, 630)


def test_state_card_without_counts_or_history():
    img = _png(og_cards.render_state_card("OK", "Oklahoma", None, 40, []))
    assert img.size == (1200, 630)


def test_default_card_and_touch_icon():
    assert _png(og_cards.render_default_card()).size == (1200, 630)
    assert _png(og_cards.render_touch_icon()).size == (180, 180)


def test_font_fallback_when_webfont_unloadable(monkeypatch):
    monkeypatch.setattr(og_cards, "_FONT", og_cards._ASSETS / "missing.woff2")
    assert _png(og_cards.render_default_card()).size == (1200, 630)


# ----- route -----

@pytest.fixture()
def api_client(db):
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    og_route._cache.clear()
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()
    og_route._cache.clear()


def _notice(nid: str, state: str, d: date, count: int | None) -> Notice:
    return Notice(
        notice_id=nid,
        state=state,
        employer="Acme",
        notice_date=d,
        layoff_count=count,
        source_url="https://example.com",
    )


def test_state_card_route(api_client, db, monkeypatch):
    calls = []
    real = og_cards.render_state_card

    def spy(*args):
        calls.append(args)
        return real(*args)

    monkeypatch.setattr(og_cards, "render_state_card", spy)
    monkeypatch.setattr(og_route, "_today", lambda: date(2026, 10, 12))
    db.add_all(
        [
            _notice("TX-1", "TX", date(2024, 3, 1), 100),
            _notice("TX-2", "TX", date(2025, 3, 1), 50),
            _notice("TX-3", "TX", date(2026, 3, 1), 7),  # current year: not in the trend
        ]
    )
    db.commit()

    r = api_client.get("/og/states/tx.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert "max-age=86400" in r.headers["cache-control"]
    assert _png(r.content).size == (1200, 630)
    code, name, workers, notices, yearly = calls[0]
    assert (code, name, workers, notices) == ("TX", "Texas", 157, 3)
    assert yearly == [("2024", 100), ("2025", 50)]

    api_client.get("/og/states/TX.png")
    assert len(calls) == 1  # served from the in-process cache


def test_state_without_published_counts_gets_no_zero(api_client, db, monkeypatch):
    calls = []
    monkeypatch.setattr(og_cards, "render_state_card", lambda *a: calls.append(a) or b"png")
    db.add(_notice("OK-1", "OK", date(2025, 1, 1), None))
    db.commit()
    api_client.get("/og/states/OK.png")
    assert calls[0][2] is None


def test_state_with_no_notices_shows_zero_not_unpublished(api_client, monkeypatch):
    calls = []
    monkeypatch.setattr(og_cards, "render_state_card", lambda *a: calls.append(a) or b"png")
    api_client.get("/og/states/AR.png")
    assert calls[0][2] == 0 and calls[0][3] == 0


def test_long_name_and_dc_render():
    img = _png(og_cards.render_state_card("DC", "District of Columbia", 1_234, 9, []))
    assert img.size == (1200, 630)


def test_unknown_state_404(api_client):
    assert api_client.get("/og/states/ZZ.png").status_code == 404


# ----- SEO wiring -----

def test_state_pages_point_og_image_at_their_card():
    meta = page_meta_for_path("/states/tx")
    assert meta.image == "/og/states/TX.png"
    html = render_index("<html><head><title>x</title></head></html>", meta)
    assert 'property="og:image" content="https://warnindex.com/og/states/TX.png"' in html
    assert 'name="twitter:image" content="https://warnindex.com/og/states/TX.png"' in html


def test_other_pages_keep_the_site_card():
    html = render_index("<html><head><title>x</title></head></html>", page_meta_for_path("/about"))
    assert 'property="og:image" content="https://warnindex.com/og-image.png"' in html
