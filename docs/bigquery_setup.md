# BigQuery + Analytics Hub setup (one-time, manual)

Console work for publishing the `warn_notices` dataset. The pipeline itself
is `warn-v2 export-bigquery` (see `docs/bigquery_dataset.md` for the schema);
the K8s CronJob ships in the chart behind `bqExport.enabled`.

## 1. GCP project

1. Create a project (e.g. `wielandtech-warn`), attach billing.
2. Enable APIs: `bigquery.googleapis.com`, `analyticshub.googleapis.com`.

## 2. Dataset

Create dataset `warn_notices`, location **US (multi-region)**.
Location is immutable and the Analytics Hub exchange must be in the same
region — US is the right call for a US-audience listing. Paste the intro of
`docs/bigquery_dataset.md` as the dataset description.

## 3. Service account (exporter credentials)

1. Create SA `warn-bq-exporter@<project>.iam.gserviceaccount.com`.
2. Grants — keep the blast radius to this one dataset:
   - `roles/bigquery.jobUser` on the **project** (run load jobs)
   - `roles/bigquery.dataEditor` on the **dataset only** (dataset → Sharing →
     add the SA principal)
3. Create a JSON key, then immediately:
   - `kubeseal` it (WSL) into SealedSecret `warn-v2-gcp`, key
     `credentials.json`, committed to w_homelab `clusters/prod/apps/warn-v2/`
   - delete the local copy
4. **Rotation:** long-lived key — set a quarterly reminder (mint new key →
   reseal → delete old key in the console).

## 4. First load (workstation validation)

Before enabling the CronJob, run one export from the workstation against the
prod DB (read-only) into the real project:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json   # pre-seal copy
export DATABASE_URL=...                                    # read-only is fine
warn-v2 export-bigquery --project <project> --dry-run      # sanity: row count
warn-v2 export-bigquery --project <project>                # real load
```

Eyeball in the BQ console: row count matches the dry run, partitioning shows
on `notices` (MONTH/notice_date) and `notices_snapshots` (DAY/snapshot_date),
`notices_active` view exists, and the sample queries in the data dictionary
run.

## 5. CronJob (chart)

w_homelab HelmRelease values:

```yaml
bqExport:
  enabled: true
  project: <project>
```

Schedule defaults to 10:17 UTC — after the daily scrape (07:17), notice
enrichment (08:15), geocoding (08:47), and cross-check (09:17), so the day's
data is settled. Watch 2–3 nightly Jobs (status + `exported_at` freshness)
before listing.

## 6. Analytics Hub listing (freemium)

1. BigQuery → Analytics Hub → **Create exchange**: name "WielandTech Labs",
   region US.
2. **Create listing** on `warn_notices`:
   - Display name: "US WARN Act Layoff Notices (enriched)"
   - Description + documentation: paste from `docs/bigquery_dataset.md`
   - Categories: Public Sector / Economics; contact email
   - 2–3 sample queries from the data dictionary
3. Start **public (free subscription)** to validate demand. Flip to
   request-access later for lead capture — a listing setting, not a pipeline
   change. Paid Cloud Marketplace listings need producer onboarding (org,
   payment/tax profile); do that only once free-tier demand is proven.

Costs: publisher pays storage (~15 MB + ~5.5 GB/yr of snapshots ≈ cents/mo).
Subscribers query a linked dataset in their own project and pay their own
query costs — no egress charge to the publisher.
