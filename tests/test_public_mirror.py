"""Tests for the public dataset mirror (warn_v2.scripts.export_public_mirror)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
from click.testing import CliRunner

from warn_v2 import cli
from warn_v2.api.routes.exports import NOTICE_PUBLIC_COLS
from warn_v2.db.models import Company, Location, Notice
from warn_v2.scripts import export_public_mirror as mirror

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
# Provider-licensed fields: display only, never redistributed.
ENRICHED = {
    "employee_count", "parent_company_name", "global_ultimate_name", "unique_id",
    "company_unique_id", "hq_address",
}


def _seed(db) -> None:
    co = Company(
        name="Acme Corp", naics_code="334111", naics_desc="Computer Manufacturing",
        employee_count=12_000, parent_company_name="Acme Holdings", unique_id="123456789",
    )
    loc = Location(city="Austin", county="Travis", state="TX", zip="78701",
                   lat=Decimal("30.267153"), lon=Decimal("-97.743057"))
    db.add_all([co, loc])
    db.flush()
    db.add_all(
        [
            Notice(notice_id="a1", state="TX", employer="ACME CORP", notice_date=date(2026, 9, 1),
                   layoff_count=300, company_id=co.id, location_id=loc.id,
                   source_url="https://twc.texas.gov/warn"),
            Notice(notice_id="b2", state="CA", employer="Beta LLC", notice_date=date(2019, 1, 5),
                   layoff_count=None, source_url="https://edd.ca.gov/warn"),
            Notice(notice_id="old", state="CA", employer="Beta LLC", notice_date=date(2019, 1, 5),
                   layoff_count=10, is_superseded=True, source_url="https://edd.ca.gov/warn"),
        ]
    )
    db.commit()


def test_frame_is_public_columns_only(db):
    _seed(db)
    df = mirror.fetch_frame(db)
    assert list(df.columns) == [*NOTICE_PUBLIC_COLS, "detail_url"]
    assert not ENRICHED & set(df.columns)
    assert sorted(df["notice_id"]) == ["a1", "b2"]  # superseded excluded
    row = df.set_index("notice_id").loc["a1"]
    assert row["company_name"] == "Acme Corp" and row["city"] == "Austin"
    assert row["detail_url"] == "https://warnindex.com/notices/a1"
    assert row["lat"] == 30.267153
    assert pd.isna(df.set_index("notice_id").loc["b2", "layoff_count"])  # stays null, not 0


def test_write_mirror_files_and_card(db, tmp_path):
    _seed(db)
    mirror.write_mirror(db, tmp_path, now=NOW)
    parquet = pd.read_parquet(tmp_path / mirror.PARQUET)
    assert len(parquet) == 2 and not ENRICHED & set(parquet.columns)
    assert len(pd.read_csv(tmp_path / mirror.CSV_GZ)) == 2
    card = (tmp_path / mirror.CARD).read_text(encoding="utf-8")
    assert card.startswith("---\nlanguage:")
    assert "license: cc-by-4.0" in card
    assert "- n<1K" in card
    assert "**Notices:** 2" in card
    assert "2019-01-05 to 2026-09-01" in card
    assert "from 2 state" in card
    assert "author = {{WARN Index}}" in card
    assert "howpublished = {\\url{https://warnindex.com}}," in card
    assert "doi = {10.5281/zenodo.23902958}" in card
    assert "](https://doi.org/10.5281/zenodo.23902958)" in card
    assert "employee_count" not in card
    assert "| `layoff_count` | Number of workers affected" in card
    assert f"](https://www.kaggle.com/datasets/{mirror.KAGGLE_DATASET})" in card
    assert "](https://huggingface.co/datasets/warn-index/us-warn-layoffs)" in card


def test_out_of_range_source_dates_do_not_break_the_export(db, tmp_path):
    # A source typo far outside pandas' nanosecond range must not fail the run;
    # the public files leave it empty.
    db.add(Notice(notice_id="typo", state="TX", employer="X", notice_date=date(2026, 1, 2),
                  effective_date=date(3026, 1, 2), source_url="https://example.com"))
    db.commit()
    mirror.write_mirror(db, tmp_path, now=NOW)
    parquet = pd.read_parquet(tmp_path / mirror.PARQUET)
    assert pd.isna(parquet.loc[0, "effective_date"])


def test_blank_implausible_values():
    nd = date(2020, 6, 1)
    df = pd.DataFrame({
        "notice_id": ["neg", "ok", "zero", "early", "late", "edge", "nodate", "year1"],
        "notice_date": [nd, nd, nd, nd, nd, nd, None, nd],
        "effective_date": [nd, date(2020, 8, 1), nd, date(2017, 1, 1), date(2030, 1, 1),
                           date(2025, 5, 30), date(2020, 1, 1), date(1, 1, 1)],
        "layoff_count": pd.array([-3, 81, 0, 5, 5, 5, 5, 5], dtype="Int64"),
    })
    out = mirror.blank_implausible(df).set_index("notice_id")
    assert pd.isna(out.loc["neg", "layoff_count"])
    assert out.loc["zero", "layoff_count"] == 0 and out.loc["ok", "layoff_count"] == 81
    assert out.loc["ok", "effective_date"] == date(2020, 8, 1)
    assert out.loc["early", "effective_date"] is None  # > 2 years before
    assert out.loc["late", "effective_date"] is None  # > 5 years after
    assert out.loc["year1", "effective_date"] is None
    assert out.loc["edge", "effective_date"] == date(2025, 5, 30)  # inside +5 years
    assert out.loc["nodate", "effective_date"] == date(2020, 1, 1)  # no notice_date: keep


def test_empty_database_still_writes(db, tmp_path):
    df = mirror.write_mirror(db, tmp_path, now=NOW)
    assert df.empty and (tmp_path / mirror.CARD).exists()


def test_size_categories():
    assert mirror._size_category(999) == "n<1K"
    assert mirror._size_category(150_000) == "100K<n<1M"


def test_cli_push_uploads(db, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mirror, "push_mirror", lambda out, repo, token: calls.append((repo, token)))
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    result = CliRunner().invoke(
        cli.main, ["export-public-mirror", "--out", str(tmp_path), "--push", "--repo", "o/r"]
    )
    assert result.exit_code == 0, result.output
    assert calls == [("o/r", "hf_test")]


def test_cli_push_without_token_fails(db, tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    args = ["export-public-mirror", "--out", str(tmp_path), "--push"]
    result = CliRunner().invoke(cli.main, args)
    assert result.exit_code != 0 and "HF_TOKEN" in result.output


KAGGLE_ENV = ("KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY")


def _clear_kaggle_env(monkeypatch):
    for var in KAGGLE_ENV:
        monkeypatch.delenv(var, raising=False)


def test_card_body_strips_front_matter():
    card = mirror.render_card(pd.DataFrame(columns=mirror.COLUMNS), NOW)
    body = mirror.card_body(card)
    assert body.startswith("# WARN Index: US WARN Act Layoff Dataset")
    assert "configs:" not in body and "license: cc-by-4.0" not in body
    assert mirror.card_body("# no front matter") == "# no front matter"


def test_push_kaggle_uploads_files_then_versions(tmp_path, monkeypatch):
    import json

    import respx
    from httpx import Response

    _clear_kaggle_env(monkeypatch)
    monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_test")
    dates = [date(1901, 1, 1), date(1990, 5, 1), date(2026, 9, 1)]
    pd.DataFrame({"notice_date": dates}).to_parquet(tmp_path / mirror.PARQUET, index=False)
    pq_bytes = (tmp_path / mirror.PARQUET).read_bytes()
    (tmp_path / mirror.CSV_GZ).write_bytes(b"csvgz")
    card = "---\nlicense: cc-by-4.0\n---\n\n# Card\n"
    (tmp_path / mirror.CARD).write_text(card, encoding="utf-8")

    with respx.mock(assert_all_called=True) as rx:
        start = rx.post(f"{mirror.KAGGLE_API}/blobs.BlobApiService/StartBlobUpload").mock(
            side_effect=[
                Response(200, json={"token": "t1", "createUrl": "https://upload.test/1"}),
                Response(200, json={"token": "t2", "createUrl": "https://upload.test/2"}),
            ]
        )
        put1 = rx.put("https://upload.test/1").mock(return_value=Response(200))
        put2 = rx.put("https://upload.test/2").mock(return_value=Response(200))
        version_url = f"{mirror.KAGGLE_API}/datasets.DatasetApiService/CreateDatasetVersion"
        version = rx.post(version_url).mock(
            return_value=Response(200, json={"url": "https://www.kaggle.com/datasets/o/s"})
        )
        current = {"title": "old", "isPrivate": False, "keywords": ["x"],
                   "licenses": [{"name": "CC BY 4.0", "url": "https://example"}],
                   "collaborators": [{"username": "friend", "role": "writer"}]}
        rx.post(f"{mirror.KAGGLE_API}/datasets.DatasetApiService/GetDatasetMetadata").mock(
            return_value=Response(200, json={"info": current}))
        rx.post(f"{mirror.KAGGLE_API}/datasets.DatasetApiService/ListDatasetFiles").mock(
            return_value=Response(200, json={"datasetFiles": []}))
        meta_url = f"{mirror.KAGGLE_API}/datasets.DatasetApiService/UpdateDatasetMetadata"
        meta = rx.post(meta_url).mock(return_value=Response(200, json={}))
        url = mirror.push_kaggle(tmp_path, "o/s", now=NOW)

    assert url == "https://www.kaggle.com/datasets/o/s"
    first = json.loads(start.calls[0].request.content)
    assert first["type"] == "DATASET" and first["name"] == mirror.PARQUET
    assert first["contentLength"] == len(pq_bytes)
    assert start.calls[0].request.headers["Authorization"] == "Bearer KGAT_test"
    assert put1.calls[0].request.content == pq_bytes and put2.calls[0].request.content == b"csvgz"
    # The pre-signed upload URL must not receive Kaggle credentials.
    assert "Authorization" not in put1.calls[0].request.headers
    body = json.loads(version.calls[0].request.content)
    assert body["ownerSlug"] == "o" and body["datasetSlug"] == "s"
    files = body["body"]["files"]
    assert [f["token"] for f in files] == ["t1", "t2"]
    assert files[0]["description"] == mirror.FILE_DOCS[mirror.PARQUET]
    assert files[1]["description"] == mirror.FILE_DOCS[mirror.KAGGLE_CSV]
    assert [c["name"] for c in files[0]["columns"]] == mirror.COLUMNS
    assert files[0]["columns"][1] == {"order": 1, "name": "state", "type": "province",
                                      "description": mirror.COLUMN_DOCS["state"][1]}
    assert body["body"]["versionNotes"] == "Weekly snapshot 2026-10-16"
    assert body["body"]["description"] == "# Card\n"
    settings = json.loads(meta.calls[0].request.content)["settings"]
    assert settings["title"] == "US WARN Act Layoff Notices 1990-2026"  # 1901 typo ignored
    assert settings["isPrivate"] is False
    assert settings["collaborators"] == current["collaborators"]
    assert settings["licenses"] == [{"name": "CC BY 4.0"}]  # Kaggle's own name, echoed back
    assert settings["expectedUpdateFrequency"] == "weekly"
    assert settings["keywords"] == mirror.KAGGLE_KEYWORDS
    assert settings["description"] == "# Card\n" and settings["subtitle"] == mirror.KAGGLE_SUBTITLE
    assert "https://warnindex.com/methodology" in settings["userSpecifiedSources"]
    # Nothing listed yet (new version processing): fall back to the known names.
    assert [f["name"] for f in settings["data"]] == [mirror.PARQUET, mirror.KAGGLE_CSV]


def test_push_kaggle_surfaces_api_error(tmp_path, monkeypatch):
    import pytest
    import respx
    from httpx import Response

    _clear_kaggle_env(monkeypatch)
    monkeypatch.setenv("KAGGLE_USERNAME", "u")
    monkeypatch.setenv("KAGGLE_KEY", "k")
    for name in (mirror.PARQUET, mirror.CSV_GZ, mirror.CARD):
        (tmp_path / name).write_text("x", encoding="utf-8")
    with respx.mock:
        respx.post(f"{mirror.KAGGLE_API}/blobs.BlobApiService/StartBlobUpload").mock(
            return_value=Response(200, json={"token": "t", "createUrl": "https://upload.test/x"})
        )
        respx.put("https://upload.test/x").mock(return_value=Response(200))
        respx.post(f"{mirror.KAGGLE_API}/datasets.DatasetApiService/CreateDatasetVersion").mock(
            return_value=Response(200, json={"error": "Dataset not found"})
        )
        with pytest.raises(RuntimeError, match="Dataset not found"):
            mirror.push_kaggle(tmp_path, "o/s", now=NOW)


def test_push_kaggle_rejects_bad_handle(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="owner/slug"):
        mirror.push_kaggle(tmp_path, "just-a-slug")


def test_cli_kaggle_pushes(db, tmp_path, monkeypatch):
    calls = []
    _clear_kaggle_env(monkeypatch)
    monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_test")
    monkeypatch.setattr(mirror, "push_kaggle", lambda out, handle: calls.append(handle) or "u")
    result = CliRunner().invoke(
        cli.main, ["export-public-mirror", "--out", str(tmp_path), "--kaggle", "o/s"]
    )
    assert result.exit_code == 0, result.output
    assert calls == ["o/s"]


def test_cli_kaggle_without_credentials_fails_before_export(db, tmp_path, monkeypatch):
    _clear_kaggle_env(monkeypatch)
    result = CliRunner().invoke(
        cli.main, ["export-public-mirror", "--out", str(tmp_path / "d"), "--kaggle", "o/s"]
    )
    assert result.exit_code != 0 and "KAGGLE_API_TOKEN" in result.output
    assert not (tmp_path / "d").exists()


def test_cli_kaggle_still_runs_when_hf_fails(db, tmp_path, monkeypatch):
    kaggle = []

    def hf_fails(out, repo, token):
        raise RuntimeError("hub down")

    _clear_kaggle_env(monkeypatch)
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_test")
    monkeypatch.setattr(mirror, "push_mirror", hf_fails)
    monkeypatch.setattr(mirror, "push_kaggle", lambda out, handle: kaggle.append(handle) or "u")
    result = CliRunner().invoke(
        cli.main, ["export-public-mirror", "--out", str(tmp_path), "--push", "--kaggle", "o/s"]
    )
    assert kaggle == ["o/s"]
    assert result.exit_code != 0 and "hub down" in result.output


def test_column_docs_cover_every_column():
    assert list(mirror.COLUMN_DOCS) == mirror.COLUMNS
    assert set(mirror.FILE_DOCS) == {mirror.PARQUET, mirror.KAGGLE_CSV}
    assert mirror.kaggle_name(mirror.CSV_GZ) == "warn_dataset.csv"  # Kaggle unpacks .gz
    assert not any("|" in desc for _, desc in mirror.COLUMN_DOCS.values())  # card table
    assert 20 <= len(mirror.KAGGLE_SUBTITLE) <= 80  # Kaggle's subtitle limits


def test_kaggle_settings_never_changes_visibility(monkeypatch):
    settings = mirror.kaggle_settings({"isPrivate": True, "title": "x"}, "T", "D")
    assert settings["isPrivate"] is True  # carried over, never forced
    bare = mirror.kaggle_settings({}, "T", "D")
    assert "collaborators" not in bare
    assert "licenses" not in bare  # never invent a license id Kaggle may reject


def test_metadata_failure_does_not_fail_the_push(tmp_path, monkeypatch):
    import respx
    from httpx import Response

    _clear_kaggle_env(monkeypatch)
    monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_test")
    pd.DataFrame({"notice_date": [date(2026, 1, 1)]}).to_parquet(tmp_path / mirror.PARQUET)
    (tmp_path / mirror.CSV_GZ).write_bytes(b"x")
    (tmp_path / mirror.CARD).write_text("# Card", encoding="utf-8")
    with respx.mock:
        respx.post(f"{mirror.KAGGLE_API}/blobs.BlobApiService/StartBlobUpload").mock(
            return_value=Response(200, json={"token": "t", "createUrl": "https://upload.test/x"}))
        respx.put("https://upload.test/x").mock(return_value=Response(200))
        respx.post(f"{mirror.KAGGLE_API}/datasets.DatasetApiService/CreateDatasetVersion").mock(
            return_value=Response(200, json={}))
        get = respx.post(f"{mirror.KAGGLE_API}/datasets.DatasetApiService/GetDatasetMetadata").mock(
            return_value=Response(500))
        update = respx.post(
            f"{mirror.KAGGLE_API}/datasets.DatasetApiService/UpdateDatasetMetadata")
        assert mirror.push_kaggle(tmp_path, "o/s", now=NOW).endswith("/o/s")
    assert get.called and not update.called  # no blind write when the read fails


def test_apply_kaggle_metadata_docs_existing_files_and_cover(tmp_path, monkeypatch):
    import json

    import respx
    from httpx import Response

    _clear_kaggle_env(monkeypatch)
    monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_test")
    pd.DataFrame({"notice_date": [date(1989, 3, 1), date(2026, 9, 1)]}).to_parquet(
        tmp_path / mirror.PARQUET)
    (tmp_path / mirror.CARD).write_text("---\nx: y\n---\n# Card\n", encoding="utf-8")
    info = {"isPrivate": False, "data": []}  # what Kaggle really returns
    api = mirror.KAGGLE_API
    with respx.mock(assert_all_called=True) as rx:
        rx.post(f"{api}/datasets.DatasetApiService/GetDatasetMetadata").mock(
            return_value=Response(200, json={"info": info}))
        listed = [{"name": "warn_dataset.csv"}, {"name": "warn_dataset.parquet"},
                  {"name": "other.txt"}]
        rx.post(f"{api}/datasets.DatasetApiService/ListDatasetFiles").mock(
            return_value=Response(200, json={"datasetFiles": listed}))
        start = rx.post(f"{api}/blobs.BlobApiService/StartBlobUpload").mock(
            return_value=Response(200, json={"token": "img", "createUrl": "https://upload.test/c"}))
        rx.put("https://upload.test/c").mock(return_value=Response(200))
        meta = rx.post(f"{api}/datasets.DatasetApiService/UpdateDatasetMetadata").mock(
            return_value=Response(200, json={}))
        mirror.apply_kaggle_metadata(tmp_path, "o/s", mirror.KAGGLE_COVER, now=NOW)
    # Metadata only: respx rejects any unmocked call, e.g. CreateDatasetVersion.
    upload = json.loads(start.calls[0].request.content)
    assert upload["type"] == "INBOX" and upload["name"] == "kaggle-cover.png"
    settings = json.loads(meta.calls[0].request.content)["settings"]
    assert settings["title"] == "US WARN Act Layoff Notices 1989-2026"
    assert settings["description"] == "# Card\n"
    assert settings["image"] == {"token": "img", "cropRectangles": mirror.COVER_CROPS}
    # Kaggle's own file names; unknown files untouched.
    assert [f["name"] for f in settings["data"]] == ["warn_dataset.csv", "warn_dataset.parquet"]
    assert settings["data"][0]["description"] == mirror.FILE_DOCS[mirror.KAGGLE_CSV]
    zip_col = next(c for c in settings["data"][0]["columns"] if c["name"] == "zip")
    assert zip_col["type"] == "postalcode"


def test_cover_fits_kaggle_crops():
    from PIL import Image

    with Image.open(mirror.KAGGLE_COVER) as img:
        assert img.size == (1120, 560)  # >= 560x280, 2:1
    for crop in mirror.COVER_CROPS:
        assert crop["left"] + crop["width"] <= 1120 and crop["top"] + crop["height"] <= 560


def test_cli_kaggle_metadata(db, tmp_path, monkeypatch):
    calls = []
    _clear_kaggle_env(monkeypatch)
    monkeypatch.setenv("KAGGLE_API_TOKEN", "KGAT_test")
    monkeypatch.setattr(mirror, "apply_kaggle_metadata",
                        lambda out, handle, cover: calls.append((handle, cover)))
    result = CliRunner().invoke(cli.main, ["kaggle-metadata", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert calls == [(mirror.KAGGLE_DATASET, mirror.KAGGLE_COVER)]
    assert (tmp_path / mirror.CARD).exists()


def test_frame_blanks_unverified_industry(db):
    exact = Company(name="Exact Co", naics_code="334111", naics_desc="Computer Manufacturing",
                    enrichment_confidence=Decimal("1.00"))
    fuzzy = Company(name="Fuzzy Co", naics_code="813211", naics_desc="Grantmaking Foundations",
                    enrichment_confidence=Decimal("0.80"))
    filed = Company(name="Filed Co", naics_code="622110", naics_desc="General Hospitals")
    db.add_all([exact, fuzzy, filed])
    db.flush()
    db.add_all([
        Notice(notice_id=c.name, state="NV", employer=c.name, notice_date=date(2026, 9, 1),
               company_id=c.id, source_url="https://example.gov/warn")
        for c in (exact, fuzzy, filed)
    ])
    db.commit()

    df = mirror.fetch_frame(db).set_index("notice_id")
    assert df.loc["Exact Co", "naics_code"] == "334111"
    assert df.loc["Filed Co", "naics_desc"] == "General Hospitals"  # from the filing
    assert pd.isna(df.loc["Fuzzy Co", "naics_code"])
    assert pd.isna(df.loc["Fuzzy Co", "naics_desc"])
    assert df.loc["Fuzzy Co", "company_name"] == "Fuzzy Co"  # only the industry goes
