"""Public dataset mirror: every non-superseded notice, public columns only.

Writes ``warn_dataset.parquet``, ``warn_dataset.csv.gz`` and a Hugging Face
dataset card (``README.md``) to an output directory, and optionally uploads
the folder to a Hugging Face dataset repo and/or pushes a new version of a
Kaggle dataset (``warn-v2 export-public-mirror``).

Exactly the public export columns (``NOTICE_PUBLIC_COLS``, built by the
same statement as /api/notices/export) plus a ``detail_url``: filing data, our
geocoding and industry codes. Licensed provider company fields (employee
counts, parent companies, unique ids) never leave here.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pandas as pd
from sqlalchemy.orm import Session

from warn_v2.api.routes.exports import NOTICE_PUBLIC_COLS, notice_export_stmt
from warn_v2.api.seo import site_base_url

log = logging.getLogger(__name__)

COLUMNS = [*NOTICE_PUBLIC_COLS, "detail_url"]
PARQUET = "warn_dataset.parquet"
CSV_GZ = "warn_dataset.csv.gz"
CARD = "README.md"
# Zenodo concept DOI: resolves to the newest archived snapshot.
ZENODO_DOI = "10.5281/zenodo.23902958"

HF_DATASET = "warn-index/us-warn-layoffs"
KAGGLE_DATASET = "warnindex/us-warn-act-layoff-notices-1989-2026"

KAGGLE_API = "https://api.kaggle.com/v1"
KAGGLE_SUBTITLE = "US WARN Act layoff notices from state labor agencies, refreshed weekly"
# Must be existing Kaggle tags; unknown ones are skipped by Kaggle, not errors.
KAGGLE_KEYWORDS = [
    "employment", "economics", "business", "united states", "government",
    "tabular", "time series analysis", "geospatial analysis",
]
WARN_ACT_YEAR = 1988  # the WARN Act was signed in 1988; earlier dates are source typos
# 1120x560 cover (2:1 header); everything sits in the centre square, the thumbnail.
KAGGLE_COVER = Path(__file__).parent / "assets" / "kaggle-cover.png"
COVER_CROPS = [
    {"title": "cover image", "top": 0, "left": 0, "width": 1120, "height": 560},
    {"title": "thumbnail", "top": 0, "left": 280, "width": 560, "height": 560},
]

# column -> (Kaggle data type, description). One entry per COLUMNS, in order.
COLUMN_DOCS: dict[str, tuple[str, str]] = {
    "notice_id": ("id", "Stable WARN Index id for the notice (a hash of state, employer, "
                  "notice date, city and ZIP). Same id across snapshots: use it to join versions."),
    "state": ("province", "Two-letter code of the state whose labor agency published the "
              "notice."),
    "employer": ("string", "Employer name exactly as published by the state."),
    "notice_date": ("datetime", "Date the notice was filed or published by the state."),
    "effective_date": ("datetime", "Date the layoff or closure takes effect (the 60-day WARN "
                       "default when the state omits it). Empty when the state's date is more "
                       "than 2 years before or 5 years after notice_date (a source typo)."),
    "layoff_count": ("integer", "Number of workers affected, summed across the worksites of one "
                     "filing. Empty when the state does not publish a count, or publishes a "
                     "negative one."),
    "closure_category": ("string", "Normalized type: Closure, Layoff, or Non-WARN (Mississippi "
                         "Rapid Response events that are not statutory notices). Empty when "
                         "the source does not say."),
    "company_name": ("string", "Canonical company name from WARN Index's employer matching "
                     "(spelling variants of one employer share a name)."),
    "naics_code": ("string", "NAICS industry code of the matched company. Empty when the "
                   "industry is unknown or the company match is not exact."),
    "naics_desc": ("string", "NAICS industry title for naics_code."),
    "city": ("city", "Worksite city."),
    "county": ("string", "Worksite county."),
    "zip": ("postalcode", "Worksite ZIP code."),
    "lat": ("latitude", "Worksite latitude from WARN Index geocoding (street, ZIP, city or "
            "county precision, best available)."),
    "lon": ("longitude", "Worksite longitude, see lat."),
    "source_url": ("url", "State web page the notice was collected from."),
    "raw_notice_url": ("url", "The notice's own detail page or PDF on the state site, when "
                       "there is one (state links can go stale)."),
    "detail_url": ("url", "The notice's page on WARN Index."),
}
# Kaggle unpacks the uploaded .csv.gz and stores it as plain .csv.
KAGGLE_CSV = "warn_dataset.csv"
# Keyed by the file name as stored on Kaggle.
FILE_DOCS = {
    PARQUET: "U.S. WARN Act layoff notices, one row per notice, with only the latest version "
             "of each. Column types are built in: dates are real dates and layoff_count is "
             "a nullable integer. The best choice for pandas, polars, DuckDB and Spark.",
    KAGGLE_CSV: "The same notices and columns as warn_dataset.parquet, as plain text for "
                "Excel, R or any other tool. CSV doesn't store column types, so parse the "
                "date columns on load; pandas will read layoff_count as a float because "
                "some values are blank. A blank means no usable count.",
}


def kaggle_name(name: str) -> str:
    """The name an uploaded file gets on Kaggle."""
    return KAGGLE_CSV if name == CSV_GZ else name


# Public-export sanity window for effective_date relative to notice_date.
# 99.9% of notices fall within -1 to +1.4 years; outside -2/+5 years the value
# is a source typo (years 0001-3030, decade slips, one stale date reused on
# dozens of later notices), so the public files leave it empty.
EFFECTIVE_BEFORE_DAYS = 2 * 365
EFFECTIVE_AFTER_DAYS = 5 * 365


def blank_implausible(df: pd.DataFrame) -> pd.DataFrame:
    """Empty values that cannot be right, in the public files only.

    The database, site and API keep what the state published; these files are
    for analysis, where a -3 worker count or a year-3030 date only misleads.
    Blanks negative layoff_count and effective_date outside the window above.
    """
    neg = df["layoff_count"].notna() & (df["layoff_count"] < 0)
    df.loc[neg, "layoff_count"] = pd.NA

    def implausible(eff: object, notice: object) -> bool:
        if not isinstance(eff, date) or not isinstance(notice, date):
            return False
        days = (eff - notice).days
        return days < -EFFECTIVE_BEFORE_DAYS or days > EFFECTIVE_AFTER_DAYS

    bad = [implausible(e, n) for e, n in zip(df["effective_date"], df["notice_date"], strict=True)]
    df.loc[bad, "effective_date"] = None
    if neg.any() or any(bad):
        log.info("public mirror: blanked %d negative counts, %d implausible effective dates",
                 int(neg.sum()), sum(bad))
    return df


def fetch_frame(db: Session) -> pd.DataFrame:
    base = site_base_url()
    rows = db.execute(notice_export_stmt().execution_options(yield_per=1_000))
    df = pd.DataFrame.from_records(
        (tuple(r._mapping[c] for c in NOTICE_PUBLIC_COLS) for r in rows),
        columns=NOTICE_PUBLIC_COLS,
    )
    df["detail_url"] = base + "/notices/" + df["notice_id"]
    for col in ("lat", "lon"):
        df[col] = pd.to_numeric(df[col]).astype("float64")
    df["layoff_count"] = df["layoff_count"].astype("Int64")
    # Dates stay datetime.date objects (pyarrow writes them as date32): going
    # through pd.to_datetime would raise on any source typo outside 1677-2262.
    return blank_implausible(df)[COLUMNS]


def _size_category(n: int) -> str:
    for upper, label in ((1_000, "n<1K"), (10_000, "1K<n<10K"), (100_000, "10K<n<100K")):
        if n < upper:
            return label
    return "100K<n<1M" if n < 1_000_000 else "1M<n<10M"


def render_card(df: pd.DataFrame, generated: datetime) -> str:
    base = site_base_url()
    dates = df["notice_date"].dropna()
    span = f"{min(dates).isoformat()} to {max(dates).isoformat()}" if len(dates) else "n/a"
    fields = "\n".join(f"| `{c}` | {COLUMN_DOCS[c][1]} |" for c in COLUMNS)
    return f"""---
language:
- en
license: cc-by-4.0
tags:
- economics
- labor-market
- layoffs
- warn-act
- employment
size_categories:
- {_size_category(len(df))}
pretty_name: "WARN Index: US WARN Act Layoff Dataset"
configs:
- config_name: default
  data_files: {PARQUET}
---

# WARN Index: US WARN Act Layoff Dataset

Worker Adjustment and Retraining Notification (WARN) Act notices filed with
US state labor agencies, collected daily from {df["state"].nunique()} state
sources and normalized into one table.

- **Notices:** {len(df):,}
- **Notice dates:** {span}
- **Snapshot:** {generated.strftime("%Y-%m-%d %H:%M UTC")} (refreshed weekly)

## Live tracker and API

For real-time filings, maps, alerts and the REST API, visit
**[WARN Index]({base})**. API docs: {base}/api-docs

The same weekly snapshot is published on
[Hugging Face](https://huggingface.co/datasets/{HF_DATASET}) and
[Kaggle](https://www.kaggle.com/datasets/{KAGGLE_DATASET}).

## Fields

| Column | Description |
|---|---|
{fields}

`detail_url` links each notice to its page on WARN Index. Superseded duplicates
are excluded. Records come from public state filings; `company_name` is WARN
Index's employer matching, the NAICS fields its industry classification (left
empty unless the employer match is exact), and `lat`/`lon` its geocoding.
Values that cannot be right are left empty here (a negative `layoff_count`,
or an `effective_date` more than 2 years before or 5 years after
`notice_date`); the notice page on WARN Index shows the state's original value.

## License and attribution

CC BY 4.0. Please credit **WARN Index** with a link to {base}.

Archived snapshots with a citable DOI are on Zenodo:
[{ZENODO_DOI}](https://doi.org/{ZENODO_DOI}) (always the newest version).

```bibtex
@misc{{warnindex{generated.year},
  author = {{{{WARN Index}}}},
  title = {{US Worker Adjustment and Retraining Notification (WARN) Layoff Dataset}},
  year = {{{generated.year}}},
  howpublished = {{\\url{{{base}}}}},
  doi = {{{ZENODO_DOI}}}
}}
```
"""


def write_mirror(db: Session, out_dir: Path, now: datetime | None = None) -> pd.DataFrame:
    now = now or datetime.now(UTC)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = fetch_frame(db)
    df.to_parquet(out_dir / PARQUET, index=False)
    df.to_csv(out_dir / CSV_GZ, index=False, compression="gzip")
    (out_dir / CARD).write_text(render_card(df, now), encoding="utf-8")
    log.info("public mirror: %d notices written to %s", len(df), out_dir)
    return df


def push_mirror(out_dir: Path, repo_id: str, token: str) -> None:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo_id, repo_type="dataset", exist_ok=True)
    api.upload_folder(
        folder_path=str(out_dir),
        repo_id=repo_id,
        repo_type="dataset",
        allow_patterns=[PARQUET, CSV_GZ, CARD],
        commit_message=f"Weekly snapshot {datetime.now(UTC):%Y-%m-%d}",
    )


def card_body(card: str) -> str:
    """The card without its Hugging Face YAML front matter (Kaggle description)."""
    if card.startswith("---\n"):
        end = card.find("\n---\n", 4)
        if end != -1:
            return card[end + 5 :].lstrip()
    return card


def kaggle_auth() -> httpx.Auth | dict[str, str]:
    """KAGGLE_API_TOKEN (bearer), else legacy KAGGLE_USERNAME + KAGGLE_KEY (basic)."""
    token = os.environ.get("KAGGLE_API_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}
    user, key = os.environ.get("KAGGLE_USERNAME"), os.environ.get("KAGGLE_KEY")
    if user and key:
        return httpx.BasicAuth(user, key)
    raise RuntimeError("Kaggle push needs KAGGLE_API_TOKEN or KAGGLE_USERNAME + KAGGLE_KEY")


def _kaggle_call(client: httpx.Client, method: str, body: dict) -> dict:
    r = client.post(f"{KAGGLE_API}/{method}", json=body)
    r.raise_for_status()
    return r.json()


def push_kaggle(out_dir: Path, handle: str, now: datetime | None = None) -> str:
    """Upload the parquet + csv.gz as a new version of an existing Kaggle dataset.

    The dataset must already exist (create it once on kaggle.com: public,
    CC BY 4.0). Each run replaces the files and refreshes the description
    from the dataset card. Returns the dataset URL.
    """
    owner, _, slug = handle.partition("/")
    if not owner or not slug or "/" in slug:
        raise ValueError(f"Kaggle dataset must be owner/slug, got {handle!r}")
    now = now or datetime.now(UTC)
    auth = kaggle_auth()
    headers = auth if isinstance(auth, dict) else {}
    basic = auth if isinstance(auth, httpx.BasicAuth) else None
    with httpx.Client(headers=headers, auth=basic, timeout=300) as client:
        tokens = []
        for name in (PARQUET, CSV_GZ):
            path = out_dir / name
            data = path.read_bytes()
            start = _kaggle_call(client, "blobs.BlobApiService/StartBlobUpload", {
                "type": "DATASET",
                "name": name,
                "contentLength": len(data),
                "lastModifiedEpochSeconds": int(path.stat().st_mtime),
            })
            # The upload URL is pre-signed: no Kaggle credentials on this PUT.
            put = httpx.put(start["createUrl"], content=data, timeout=300,
                            headers={"Content-Type": "application/octet-stream"})
            put.raise_for_status()
            tokens.append({"token": start["token"], **kaggle_file_doc(kaggle_name(name))})
        description = card_body((out_dir / CARD).read_text(encoding="utf-8"))
        resp = _kaggle_call(client, "datasets.DatasetApiService/CreateDatasetVersion", {
            "ownerSlug": owner,
            "datasetSlug": slug,
            "body": {
                "versionNotes": f"Weekly snapshot {now:%Y-%m-%d}",
                "deleteOldVersions": False,
                "files": tokens,
                "subtitle": KAGGLE_SUBTITLE,
                "description": description,
            },
        })
        if resp.get("error"):
            raise RuntimeError(f"Kaggle rejected the version: {resp['error']}")
        # Cosmetic: the version is already in, so a metadata failure only logs.
        try:
            update_kaggle_metadata(client, owner, slug, kaggle_title(out_dir, now), description,
                                   file_docs=True)
        except Exception:
            log.exception("Kaggle metadata update failed (the new version is uploaded)")
    return resp.get("url") or f"https://www.kaggle.com/datasets/{owner}/{slug}"


def kaggle_file_doc(name: str) -> dict:
    """File description + column docs, sent with each uploaded file."""
    return {
        "description": FILE_DOCS[name],
        "columns": [
            {"order": i, "name": c, "type": COLUMN_DOCS[c][0], "description": COLUMN_DOCS[c][1]}
            for i, c in enumerate(COLUMNS)
        ],
    }


def kaggle_title(out_dir: Path, now: datetime) -> str:
    """"US WARN Act Layoff Notices 1989-2026": first and last plausible notice year."""
    dates = pd.read_parquet(out_dir / PARQUET, columns=["notice_date"])["notice_date"].dropna()
    years = [d.year for d in dates if WARN_ACT_YEAR <= d.year <= now.year]
    span = f" {min(years)}-{max(years)}" if years else ""
    return f"US WARN Act Layoff Notices{span}"


def kaggle_sources(base: str) -> str:
    return (
        "WARN Act notices published by US state workforce agencies, one public listing per "
        "state; each row's `source_url` is the page it came from. Collected daily, "
        f"deduplicated, geocoded and industry-coded by [WARN Index]({base}). "
        f"Methodology: {base}/methodology. Coverage by state: {base}/states."
    )


def kaggle_settings(current: dict, title: str, description: str) -> dict:
    """Settings for UpdateDatasetMetadata: the fields we own, over the current ones.

    Keeps visibility and collaborators exactly as they are (an omitted field
    must never flip the dataset private or drop a collaborator). Subtitle and
    description are sent again, not copied from `current`: the new version may
    still be processing, and copying would write last week's text back. File
    and column docs travel with the version itself.

    The license is carried over as Kaggle reports it (set to CC BY 4.0 on
    kaggle.com when the dataset was created). The update API rejects the
    documented id "CC-BY-4.0" with "You've specified an invalid license", and
    a rejected field fails the whole update.
    """
    keep = {k: current[k] for k in ("isPrivate", "collaborators") if k in current}
    licenses = [{"name": lic["name"]} for lic in current.get("licenses") or [] if lic.get("name")]
    if licenses:
        keep["licenses"] = licenses
    else:
        log.warning("Kaggle dataset has no license; set CC BY 4.0 on kaggle.com")
    return {
        **keep,
        "title": title,
        "subtitle": KAGGLE_SUBTITLE,
        "description": description,
        "keywords": KAGGLE_KEYWORDS,
        "expectedUpdateFrequency": "weekly",
        "userSpecifiedSources": kaggle_sources(site_base_url()),
    }


def _upload_cover(client: httpx.Client, cover: Path) -> dict:
    data = cover.read_bytes()
    start = _kaggle_call(client, "blobs.BlobApiService/StartBlobUpload", {
        "type": "INBOX",
        "name": cover.name,
        "contentType": "image/png",
        "contentLength": len(data),
        "lastModifiedEpochSeconds": int(cover.stat().st_mtime),
    })
    put = httpx.put(start["createUrl"], content=data, timeout=120,
                    headers={"Content-Type": "application/octet-stream"})
    put.raise_for_status()
    return {"token": start["token"], "cropRectangles": COVER_CROPS}


def update_kaggle_metadata(
    client: httpx.Client, owner: str, slug: str, title: str, description: str,
    *, file_docs: bool = False, cover: Path | None = None,
) -> dict:
    """Read the current metadata, then write ours over it. Returns the old info.

    file_docs: also describe the files on Kaggle, by the names Kaggle lists
    them under (GetDatasetMetadata's `data` comes back empty). cover: also
    upload this image as the cover and thumbnail.
    """
    ids = {"ownerSlug": owner, "datasetSlug": slug}
    got = _kaggle_call(client, "datasets.DatasetApiService/GetDatasetMetadata", ids)
    if got.get("errorMessage") or "info" not in got:
        raise RuntimeError(f"Kaggle metadata read failed: {got.get('errorMessage')}")
    settings = kaggle_settings(got["info"], title, description)
    if file_docs:
        listed = _kaggle_call(client, "datasets.DatasetApiService/ListDatasetFiles", ids)
        names = [f["name"] for f in listed.get("datasetFiles") or []
                 if f.get("name") in FILE_DOCS] or list(FILE_DOCS)
        settings["data"] = [
            {"name": n, "description": FILE_DOCS[n],
             "columns": [{"name": c, "description": COLUMN_DOCS[c][1], "type": COLUMN_DOCS[c][0]}
                         for c in COLUMNS]}
            for n in names
        ]
    if cover is not None:
        settings["image"] = _upload_cover(client, cover)
    resp = _kaggle_call(client, "datasets.DatasetApiService/UpdateDatasetMetadata",
                        {**ids, "settings": settings})
    if resp.get("errors"):
        raise RuntimeError(f"Kaggle metadata update errors: {resp['errors']}")
    log.info("Kaggle metadata updated for %s/%s", owner, slug)
    return got["info"]


def apply_kaggle_metadata(out_dir: Path, handle: str, cover: Path | None,
                          now: datetime | None = None) -> None:
    """One-off: metadata + existing-file docs (+ cover) without a new version."""
    owner, _, slug = handle.partition("/")
    now = now or datetime.now(UTC)
    auth = kaggle_auth()
    headers = auth if isinstance(auth, dict) else {}
    basic = auth if isinstance(auth, httpx.BasicAuth) else None
    description = card_body((out_dir / CARD).read_text(encoding="utf-8"))
    with httpx.Client(headers=headers, auth=basic, timeout=120) as client:
        update_kaggle_metadata(client, owner, slug, kaggle_title(out_dir, now), description,
                               file_docs=True, cover=cover)
