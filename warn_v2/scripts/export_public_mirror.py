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
from datetime import UTC, datetime
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

KAGGLE_API = "https://api.kaggle.com/v1"
KAGGLE_SUBTITLE = "US WARN Act layoff notices from state labor agencies, refreshed weekly"


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
    return df[COLUMNS]


def _size_category(n: int) -> str:
    for upper, label in ((1_000, "n<1K"), (10_000, "1K<n<10K"), (100_000, "10K<n<100K")):
        if n < upper:
            return label
    return "100K<n<1M" if n < 1_000_000 else "1M<n<10M"


def render_card(df: pd.DataFrame, generated: datetime) -> str:
    base = site_base_url()
    dates = df["notice_date"].dropna()
    span = f"{min(dates).isoformat()} to {max(dates).isoformat()}" if len(dates) else "n/a"
    fields = "\n".join(f"- `{c}`" for c in COLUMNS)
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

## Fields

{fields}

`detail_url` links each notice to its page on WARN Index. Superseded duplicates
are excluded. Records come from public state filings; `company_name` is WARN
Index's employer matching, the NAICS fields its industry classification, and
`lat`/`lon` its geocoding.

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
            tokens.append({"token": start["token"]})
        resp = _kaggle_call(client, "datasets.DatasetApiService/CreateDatasetVersion", {
            "ownerSlug": owner,
            "datasetSlug": slug,
            "body": {
                "versionNotes": f"Weekly snapshot {now:%Y-%m-%d}",
                "deleteOldVersions": False,
                "files": tokens,
                "subtitle": KAGGLE_SUBTITLE,
                "description": card_body((out_dir / CARD).read_text(encoding="utf-8")),
            },
        })
    if resp.get("error"):
        raise RuntimeError(f"Kaggle rejected the version: {resp['error']}")
    return resp.get("url") or f"https://www.kaggle.com/datasets/{owner}/{slug}"
