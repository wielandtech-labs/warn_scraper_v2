# Analytics: indicators, reports and outlook

The layers built on top of the notice data. Moved out of the README.

## Economic indicators

WARN notices count *announced* layoffs at larger employers. On their own they
can't say whether a spike is a loosening labour market or noise against a
strong one, so each layoff time series carries a companion card of official
BLS context on the same period span — `/stats`, every state page, and the
industry reports.

Three datasets, all monthly and seasonally adjusted, stored in `bls_series`
keyed by raw BLS series id:

| Dataset | Series | Coverage |
|---|---|---|
| `unemployment` | CPS U-3 + U-6 nationally, LAUS rates per state | 50 states + DC + PR. BLS publishes no monthly **state U-6** |
| `payrolls` | CES all-employees levels, total nonfarm or by NAICS sector | National. Sector figures use the closest CES supersector, broader than NAICS where several sectors share one |
| `jolts` | Layoffs & discharges, job openings, quits | National + 50 states and DC. **State estimates are modelled and republished annually**, so they run ~9 months behind the national series |

`warn-v2 fetch-bls` refreshes them (default: a rolling three-year window, which
picks up BLS revisions; `--start-year 2000` backfills). Series ids are built in
`warn_v2/labor/catalog.py` — the only module that knows their layouts, because
**a malformed id is not an error**: it comes back inside `Results.series` with
an empty `data` list, indistinguishable from a real series with no data in the
requested span. The job therefore fails on *coverage* rather than on status, and
`tests/test_labor_catalog.py` pins each layout.

`BLS_API_KEY` (free registration) is effectively required: unregistered callers
get 10 series and 10 years per request and 25 requests a day, and the catalogue
is ~225 series. With a key it is 50 series, 20 years and 500 requests. Supply it
via the `warn-v2-bls` SealedSecret; the key is scoped to this CronJob, not to
the API pods.

Not included: LISEP's True Rate of Unemployment. Their terms of use forbid
redistributing it, and it ships only as a monthly spreadsheet on a rotating CDN
path. U-6 is the closest public-domain equivalent.

## Sentiment reports & industry scorecards

Markdown reports — one per state, a national roll-up (`US.md`), and a scorecard
per NAICS sector — committed to `warn_v2/reports/published/`, served at
`/api/reports/*`, and rendered on the SPA's state pages (below the hardest-hit
counties) and `/reports` page. Claude writes them on demand with the
`/layoff-sentiment` skill (`.claude/skills/layoff-sentiment/`) from figures the
weekly CronJob computes; they ship in the image, so a report PR is a deploy.

**Pipeline** (`sentiment-report` CLI; CronJob Mon 02:07 UTC):

1. **Deterministic aggregates** (`aggregate.py`, `industry.py`) — every number in
   a report comes from SQL over non-superseded notices. Time axes: current 90
   days vs the prior 90 (momentum), the same 90-day window one year earlier
   (seasonal baseline), trailing 12 months vs the 12 before (long run), and a
   12-month monthly series where each month carries the same month a year
   earlier. Percent changes are pre-computed into the payload; the sector
   scorecards add a 0-100 score + grade from a documented formula.
2. **BLS macro context** (`bls.py`) — official CES payroll month-over-month
   changes (total nonfarm + closest supersector per sector) and the unemployment
   rate, aligned to the same months, injected as `bls_context` into the national
   and industry payloads. Strictly fail-open: any API problem and the reports
   render without it. Shares its HTTP client and series ids with the
   `fetch-bls` ingester (see [Economic indicators](#economic-indicators)),
   which is *not* fail-open.
3. **Export** (`generate.py`) — `payloads.json` (every report's figures:
   aggregates + forecast + BLS context, served at `/api/reports/payloads`),
   `industries.json` (the `/reports` scorecard grid), and `forecasts.json`
   (the forecast charts), atomically written to the reports PVC
   (`/var/reports`). No LLM runs in-cluster.
4. **Write + publish** (`/layoff-sentiment` skill) — Claude reads the payloads,
   writes the reports to the template in its SKILL.md, and opens a PR. Its
   `validate.py` is the gate: every number and date must appear in the
   payload, growth vocabulary ("added/grew/gained") is banned — every figure
   is workers losing jobs — and only the markdown subset the SPA renders is
   allowed.

```powershell
uv run warn-v2 sentiment-report --dry-run   # offline smoke test of the export
```

## Outlook

`warn_v2/outlook/` turns the WARN panel into forward-looking findings that
must pass a statistical test before they are published. The same weekly
`sentiment-report` run writes `outlook.json` (fail-open, like
`forecasts.json`). It is served raw at `/api/reports/outlook` and rendered on
the SPA's `/outlook` page.

- **Trends** (`trends.py`): per-state monthly notice counts over the last 36
  settled months, fitted with a quasi-Poisson GLM using month-of-year dummies.
  The standard errors are inflated for AR(1) autocorrelation. Newey-West SEs
  rejected 19-25% of null series at nominal 5% in simulation, so they were
  dropped. Results are reported as Benjamini-Hochberg q-values per family,
  with DerSimonian-Laird pooling plus empirical-Bayes shrinkage across states.
- **Sectors**: the trend in each NAICS sector's *share* of classified notices,
  not its count, because enrichment coverage drifts over time.
- **Coverage** (`coverage.py`): per-state month masks treat these as missing
  data, not zeros:
  - months before a state's first notice;
  - a series' improbably low trailing edge (publication lag or a stale
    scraper);
  - improbable interior zero-runs.
- **Unemployment link**: the effect of the lagged 12-month change in state
  unemployment (LAUS, from `bls_series`) on monthly filings, pooled across
  states and re-fitted without 2020-21.
- **Claims** (`claims.py`): templated statements gated on q < 0.05 (or a 95%
  CI excluding zero). Weaker signals (q < 0.20) appear as a clearly labelled
  watch list. Templates obey the job-losses wording rule, and a test enforces
  it.
