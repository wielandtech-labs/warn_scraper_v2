"""Public dataset mirror: every non-superseded notice, public columns only.

Writes ``warn_dataset.parquet``, ``warn_dataset.csv.gz`` and a Hugging Face
dataset card (``README.md``) to an output directory, and optionally uploads
the folder to a Hugging Face dataset repo (``warn-v2 export-public-mirror``).

Exactly the free tier's export columns (``NOTICE_PUBLIC_COLS``, built by the
same statement as /api/notices/export) plus a ``detail_url``: filing data, our
geocoding and NAICS. Provider-enriched fields (employee counts, parent
companies, unique ids) are licensed for display only and never leave here --
the site's terms forbid redistributing them.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from warn_v2.api.routes.exports import NOTICE_PUBLIC_COLS, notice_export_stmt
from warn_v2.api.seo import site_base_url

log = logging.getLogger(__name__)

COLUMNS = [*NOTICE_PUBLIC_COLS, "detail_url"]
PARQUET = "warn_dataset.parquet"
CSV_GZ = "warn_dataset.csv.gz"
CARD = "README.md"


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
are excluded. Records come from public state filings; `company_name` and the
NAICS fields are WARN Index's own employer matching, and `lat`/`lon` its
geocoding. Provider-enriched company data (employee counts, parent companies)
is not included.

## License and attribution

CC BY 4.0. Please credit **WARN Index** with a link to {base}.

```bibtex
@misc{{warnindex{generated.year},
  author = {{{{WARN Index}}}},
  title = {{US Worker Adjustment and Retraining Notification (WARN) Layoff Dataset}},
  year = {{{generated.year}}},
  howpublished = {{\\url{{{base}}}}}
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
