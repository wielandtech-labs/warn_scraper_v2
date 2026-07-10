# BigQuery dataset: `warn_notices`

The published, fully-attributed slice of the WARN Tracker dataset: layoff
notices whose company has been resolved and industry-classified. Refreshed
daily from the scraper's Postgres by `warn-v2 export-bigquery`
(`warn_v2/scripts/bq_export.py` — the schema constants there are the source
of truth; this file is the human-readable copy for the Analytics Hub listing).

**Not included, by design:** raw DUNS identifiers (licensing), and notices
whose company has no enrichment yet (the export grows as enrichment coverage
does — the full raw feed is available via the website and API).

## Tables

### `notices` — current state

One denormalized row per notice (notice + worksite location + canonical
company). Month-partitioned on `notice_date`, clustered by `state,
naics_code`. Amendments update rows in place; superseded duplicates stay,
flagged. Use the **`notices_active`** view (`WHERE NOT is_superseded`) for
the clean cut.

### `notices_snapshots` — point-in-time history

The same rows appended daily under `snapshot_date` (day-partitioned).
Amendments rewrite `notices` but never history, so "what was known on date X"
is always answerable:

```sql
SELECT * FROM `PROJECT.warn_notices.notices_snapshots`
WHERE snapshot_date = "2026-07-01" AND state = "CA" AND NOT is_superseded
```

## Columns

| Column | Type | Description |
|---|---|---|
| `notice_id` | STRING | Stable content-hash id (`state\|employer\|notice_date\|city\|zip`). Survives refreshes; join key across snapshots. |
| `state` | STRING | Two-letter filing jurisdiction. |
| `employer` | STRING | Employer name as published by the state. |
| `notice_date` | DATE | Date the notice was filed/published. |
| `effective_date` | DATE | Layoff/closure effective date (60-day WARN default when the source omits it). |
| `layoff_count` | INTEGER | Workers affected; summed across worksites of one filing. |
| `closure_type` | STRING | Raw source wording (e.g. "Layoff Permanent"). |
| `closure_category` | STRING | Normalized bucket: `Closure` \| `Layoff` \| `Non-WARN` (MS Rapid Response events, not statutory notices) \| NULL. |
| `address` | STRING | Worksite street address as filed. |
| `city`, `county`, `zip` | STRING | Worksite locality. |
| `lat`, `lon` | FLOAT | Worksite coordinates (see `geocode_source`). |
| `geocode_source` | STRING | Precision tier: `census` (street) > `zip` > `city` > `county`. |
| `company_name` | STRING | Canonical (deduplicated) company name. |
| `naics_code`, `naics_desc` | STRING | NAICS industry classification of the canonical company. |
| `sic_code`, `sic_desc` | STRING | SIC industry classification. |
| `company_website` | STRING | Company website. |
| `employee_count` | INTEGER | Company total employee count (enrichment). |
| `parent_company_name` | STRING | Direct parent company name, when known. |
| `global_ultimate_name` | STRING | Top of the corporate tree, when known. |
| `enrichment_source` | STRING | Primary source of company attributes: `provider` \| `edgar` \| `claude`. |
| `enrichment_confidence` | FLOAT | Company match confidence, 0–1. |
| `source_url` | STRING | State listing page the notice was scraped from. |
| `raw_notice_url` | STRING | Detail page or PDF for this notice (may rot). |
| `is_superseded` | BOOLEAN | A later amendment/duplicate replaces this row; kept for auditability. |
| `scraped_at` | TIMESTAMP | First seen by the scraper (UTC). |
| `exported_at` | TIMESTAMP | Export run start (UTC) — the dataset's freshness stamp. |

`notices_snapshots` adds a leading `snapshot_date DATE` column.

## Sample queries

Layoffs by industry sector, trailing 12 months:

```sql
SELECT SUBSTR(naics_code, 1, 2) AS sector, SUM(layoff_count) AS workers
FROM `PROJECT.warn_notices.notices_active`
WHERE notice_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH)
GROUP BY sector ORDER BY workers DESC
```

Amendment history for one notice (how the count evolved):

```sql
SELECT snapshot_date, layoff_count, effective_date
FROM `PROJECT.warn_notices.notices_snapshots`
WHERE notice_id = "abc123..." ORDER BY snapshot_date
```

Corporate-family exposure (all notices under one global ultimate):

```sql
SELECT global_ultimate_name, COUNT(*) notices, SUM(layoff_count) workers
FROM `PROJECT.warn_notices.notices_active`
WHERE global_ultimate_name IS NOT NULL
GROUP BY 1 ORDER BY workers DESC LIMIT 25
```

## Caveats

- Coverage per state varies with what states publish; see
  [STATE_AUDIT.md](../STATE_AUDIT.md) for per-state field fill rates and
  known gaps. `layoff_count` is NULL where the source never publishes it.
- Geocoding is best-effort — filter on `geocode_source = 'census'` when you
  need street-level precision.
- `effective_date` is estimated (notice_date + 60 days) for sources that omit
  it, per the WARN Act default notice period.
- Provided as-is; underlying records are public state filings.
