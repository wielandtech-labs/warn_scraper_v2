# Roadmap — agent-executable work tracks

Forward plan for the WARN scraper, written so an agent session can pick up any
item self-contained. Companion to [STATE_AUDIT.md](../STATE_AUDIT.md) (current
per-state data quality), [historical-sources.md](historical-sources.md)
(backfill routes + runbook), and [coverage-vs-aggregators.md](coverage-vs-aggregators.md)
(external cross-check). Baseline: the 2026-07-02 prod audit.

**Update discipline**: check items off (`~~strikethrough~~ — DONE date, PR #N`)
in the same PR that completes them, mirroring historical-sources.md's Progress
section. Re-prioritize when a `/refresh-audit` run changes the picture.

## Autonomy legend

Merging to `main` is a production deploy, one-off in-cluster Jobs are
permission-gated, and records requests are outward-facing — so every item ends
at a PR, a prepared Job manifest, or a report, never an unattended apply/send.

| Level | Meaning |
|-------|---------|
| **A** | Agent end-to-end, including opening the PR. |
| **A+gate** | Agent does all the work; a human merges the PR and/or approves the one-off prod Job. |
| **H** | Human decision required before agent work starts. |

## Status snapshot (2026-07-02)

48/51 jurisdictions live (47 states + DC), ~37k active notices. 45 scrapers
`ok`; AZ `fetch_failed`, RI `parse_failed`; CO carries a possibly-stale
row-drift flag. 3 blocked (AR/WY confidential by statute, NH unpublished);
OK re-enabled 2026-07-06 via the Employ Oklahoma guest Aura endpoint. effective_date ~100% everywhere; layoff_count weak only where
counts live inside stored PDFs (CT/HI/WV/PA). Geocoding root causes fixed;
residual low-geo states are un-geocodable historical tails. Enrichment is the
weakest axis (~16% avg; D&B cap doubled to 400 companies/day 2026-07-07).
Largest coverage gap: NY (217 rows vs ~7,100 at aggregators since 2006). 31 records-request drafts in
[foia/](foia/), all unsent.

## Track 1 — Keep it green (recurring)

- ~~**Heal AZ + RI** — `/heal-scraper AZ RI`; classify transient block vs
  real regression before treating as broken (`fetch_failed` is often
  transient). (A+gate: PR)~~ — DONE 2026-07-06, no code change: both were
  transient; live `validate()` passes (AZ 25 rows, RI 122) and prod
  `scraper_runs` show `ok` since 2026-07-02.
- ~~**Verify CO row-drift flag** — the audit's `broken` status predates the
  full-sheet sweep (PR #110, +768 rows); confirm the next trusted audit clears
  it, else investigate `expected_row_range` vs the new two-sheet regular
  scrape. (A)~~ — DONE 2026-07-06, stale flag: the 2026-07-02 audit image
  carried the revert-era `(100, 10_000)` range (PR #120) against a 43-row
  two-sheet scrape; main is back to `(5, 10_000)` (PR #127) and prod scrapes
  91 rows `ok` daily, so the next trusted audit clears it.
- ~~**Recurring heal loop** — `/loop /heal-scraper` (self-paced) or a
  scheduled headless run after the daily 07:17 scrape window. (A+gate per
  PR)~~ — DONE 2026-07-06 via a Claude desktop-app scheduled task
  (`daily-heal-scraper`, daily 08:30; the skill's Task Scheduler recipe
  doesn't apply — no `claude` CLI on this host). Runs only while the app is
  open; missed runs fire on next launch.
- ~~**Weekly `/refresh-audit`** — keeps STATE_AUDIT.md's generated table
  honest; PR per run. (A+gate)~~ — DONE 2026-07-06 via desktop-app scheduled
  task (`weekly-refresh-audit`, Mondays 09:00), same caveats as above.
- [ ] **Quarterly blocked-source re-verify** — AR / NH / OK / WY per
  [deferred-states.md](deferred-states.md), plus a
  [coverage-vs-aggregators.md](coverage-vs-aggregators.md) refresh (that
  cross-check found the CO freeze and the KY backfill error). (A) —
  *2026-Q3 pass done 2026-07-07* (#204: AR/NH/WY still blocked, OK live;
  coverage refreshed — CO/KY/NV/LA/OK anomalies resolved). Recurring:
  next pass due ~2026-10.

## Track 2 — Prod follow-ups already coded

Code is merged; only the one-off in-cluster run (runbook: one-off Job, image
from the live deployment, `DATABASE_URL` via secretKeyRef `warn-v2-db/url`,
delete Jobs after — see [historical-sources.md](historical-sources.md)) is
outstanding.

- ~~**`backfill-layoff-counts` Job** (PR #113) — dry-run first, then real;
  closes the CT 30% / HI 45% / WV 22% count gaps from stored PDFs.
  (A+gate)~~ — DONE 2026-07-06 (w_homelab #591/#595/#599):
  `considered=465 filled=94 no_count=371 no_text=0 missing=0 errors=0`.
  The 371 kept NULL are letters whose text carries no usable count — the
  conservative extractor's expected residue, not a re-run target.
- ~~**OH historical backfill run** (PR #55, era-dispatch 1996–2024) —
  dry-run pilot on 1–3 early years per the runbook; 2025 is unaccounted for
  at source (investigate or fold into the OH request). (A+gate)~~ — RUN
  2026-07-06: 22/31 years ok, **+2,319 rows** (floor now 1996). One parse
  artifact found and healed (AD-EX 2003 Excel-serial count; parser fix
  PR #153). The 7 gap years (2007–09, 2011, 2013, 2023–24) were discovery
  failures, fixed 2026-07-06 in PR #159; the re-run (w_homelab #611)
  added **+798 rows** after #181 filtered cross-year junk. Six
  wrapped-count artifacts (up to 1.58M "affected") were parser-fixed
  (#183) and healed in place with source-verified values (w_homelab
  #614). OH is complete 1996–2024; 2025 stays with the OH request.
- ~~**`mark-superseded` for IA (479), PA (286), IL (14)** — `--dry-run`
  preview, then commit. (A+gate)~~ — DONE 2026-07-06: those audit numbers
  count rows *already marked* in earlier passes; the sweep found only 3
  residual rows (PA Brinks Home + PA NRG Homer City zip-variance, AZ
  Theranos 2016 locationless), committed.

## Track 3 — Historical depth (Wave 2B/2C parsers)

One agent session per state: implement parser + fixture tests → PR →
post-merge one-off backfill Job per the runbook → re-audit. Routes and probe
notes per state live in [historical-sources.md](historical-sources.md).
Ordered by recoverable rows:

- ~~**NY** (~6,900 rows since 2006 — the largest gap).~~ **DONE 2026-07-08**
  via the dashboard's full **crosstab** export (warn_scraper_v2 #232/#233):
  `dol.ny.gov/warn-dashboard` → Download → Crosstab returns the entire
  2006–2026 history in the live CSV's schema, so `NYScraper.parse` ingests it
  with no new parser — a one-time gzip snapshot bundled in-repo, run via
  `backfill-historical --state NY`. **Prod: 8,708 rows, 2006–2026, 98% with
  counts** (floor 2025→2006). The Wayback `details.asp` detour (#193/#206,
  reverted) was the hard way around — the crosstab has more rows, more years,
  no scrape. Live daily scraper keeps current data fresh; refresh history by
  re-downloading the crosstab + regenerating the .gz.
- ~~**PA 2001–2022** — Wayback snapshots of the old dli.pa.gov pages;
  strict dedup (286 superseded rows already); `--year-end 2022`.
  (A+gate)~~ — DONE 2026-07-07 (parser #166 + hardening #183; Jobs
  w_homelab #600/#605/#614/#616/#617): **3,158 rows across 2001–2022,
  262/262 archived months** verified per-month in prod (2021-10 and
  2022-04 were never captured by Wayback — the only misses). The
  2017–2022 era was purged + re-ingested after #183 (label-variant
  junk removal + ~200 recovered effective dates); Wayback throttle
  drops needed two top-up runs — per-month prod coverage, not
  chunk counts, is the completion check.
- ~~**IL PDF era 1999–2019** — `parse_il_pdf` for the monthly archive PDFs
  (xlsx era 2020+ already ingested). (A+gate)~~ — DONE 2026-07-07 (parser #211
  + column-split fix #217; Jobs w_homelab #635 dry-run → #644 real → #645
  prune): **+2,707 rows, floor 2020 → 1999** (IL 1,017 → **3,732**, verified via
  the public API: pre-2000 = 149 = the 1999 rows). The PDFs are a two-column
  labeled form → each flattened line split at its right-column label
  (x-independent; #217 fixed one compressed-layout month, July 2003, that the
  fixed-x split #211 shipped dropped to 0 rows). `mark-superseded` was a no-op
  (all rows net-new below the old floor, near_miss=0). **January 2019** (the one
  image-only scan — OCR mangles this gridded form's dates, `1/3/19`→`173/19`) was
  hand-transcribed from the legible scan and ingested inline (w_homelab #647,
  +10 rows, 1,223 workers). **IL 1999–2019 is now complete: 3,742 notices.**
- [x] ~~**NC 2014+** — archive-hub discovery (irregular slugs) +
  `parse_nc_pdf`. (A+gate)~~ — DONE 2026-07-07 (parser #213; fixes #215/#220/
  letter-spacing; Jobs w_homelab #631→#650): **+864 rows, floor 2026→2014,
  NC total 913** (verified per-year via `/api/stats/over-time`).
  `_discover_nc_pdf_urls` (hub anchors, three slug families) + a three-era
  `parse_nc_pdf` dispatching on detected content — 2014–~2017 summary-count
  (word-position, wrap-aware, letter-spacing collapse), ~2018–2021 SSRS grid,
  2022–2025 live-schema grid (shares `_row_from_nc_grid` with the live HTML
  parser). Two data-quality bugs surfaced in prod verification and were fixed:
  the SSRS ZIP/city extraction (#215/#220), and — root cause — a storage
  **zip-less location promotion** that let a historical ZIP poison a shared
  city location (corrupted 78 notices incl. live rows); #220 guards it, and
  w_homelab #650 purged 2018–2021 + nulled the poisoned ZIPs + re-ran clean.
- [x] ~~**NJ** — cumulative `WARN_Notice_Archive.xlsx` (year range unknown —
  parse first). (A+gate)~~ — DONE 2026-07-07 (parser #197: one sheet per
  year 2004–2026; prod run w_homelab #627: **+2,203 rows, floor
  2026→2004-01**, near_miss=0, verified per-record).
- ~~**MA FY22–FY25** — mass.gov FY XLSX reports (Playwright fetch, like the
  live scraper). (A+gate)~~ — DONE 2026-07-07 (parser PR #212; Jobs w_homelab
  #638 dry-run → #640 real): **+287 rows, floor FY2025 → 2021-04** (86 → 373
  active). The "Previous WARN reports" section links one XLSX per FY at
  `/doc/fy{NN}-warn-report` (discovered via Playwright — no `.xlsx` in the href,
  Akamai gates the page); `parse_ma_xlsx` handles both layouts (FY22/FY23 one
  sheet per region, FY24+ single CSV-style sheet). Dry-run and real run both
  near_miss=0 / already_exists=0 (FY23 80→79 by in-batch hash dedup);
  `mark-superseded` was a no-op. FY26 stays with the live scraper; pre-FY22 →
  email request.
- ~~**MN multi-era parser** — 2015–16 monthlies, 2018–21 annuals, 2022–24
  wide format; Wayback discovery already implemented. (A+gate)~~ — DONE
  2026-07-10. Parser #202 (one word-position parser for all eras, reaches
  2014 via the Dec-2016 cumulative); prod backfill ran (w_homelab #679).
  Data-quality follow-up #237 fixed three 2023–25 bugs — the year-end
  cumulative roll-ups were ingested alongside monthlies (glued employers +
  2× counts), right-aligned Affected-Workers counts were dropped into the TAA
  column, and the live chain didn't strip DEED's trailing report year. Purge +
  clean re-ingest via w_homelab #685 (Jobs pruned #686), verified in prod:
  **541→482 rows** (59 glued/roll-up strays purged), **2023–25 glued dupes → 0**,
  **missing counts 66→4**, floor 2012.
- ~~**WA `__VIEWSTATE` pagination** — implement ASP.NET postback paging,
  then reassess depth (10+ pages, depth unknown). (A+gate)~~ — DONE 2026-07-07
  (PR #209): `fetch()` now replays the `Page$N` GridView postback for each
  page (carrying the fresh `__VIEWSTATE`/`__EVENTVALIDATION` tokens forward)
  and concatenates the raw pages; `parse()` scans every `ucPSW_gvMain` grid.
  **Depth reassessed: 99 pages / 1,480 rows / floor 2004-01** (was page-1
  only, ~15 rows). No one-off backfill Job needed — WA's source is a single
  cumulative list, so the next daily scrape upserts the full history via the
  normal image-tag chain.
- ~~**CA 2009–2013 probe** — EDD archive search for the interior hole
  (archive currently = 11 PDFs + 1 XLSX, FY2014–2025); fall back to the CA
  records request. (A: spike + report)~~ — DONE 2026-07-07, PR #214:
  **route found, no CPRA needed.** Live EDD = FY2014+ only, but Wayback holds
  EDD's calendar-year reports 2006–2014 (`eddwarncn*.pdf`). Landed the parser
  in the same PR (see the follow-up below), so this became spike **+ build**.
- [x] ~~**CA 2006–2013 Wayback backfill** — parser done 2026-07-07
  (`parse_ca_detail_pdf` + `_discover_ca_historical_urls`, detailed A–Z slices;
  see [historical-sources.md](historical-sources.md) CA row). Remaining: the
  gated prod Job (dry-run → real → re-audit) per the runbook — ~6.8K rows, the
  largest remaining CA gap. (A+gate)~~ — DONE 2026-07-08 (w_homelab real run
  #665, prune #669): **+4,180 rows, CA 15,897 → 20,077, floor 2008 → 2006**
  (verified via the public API). 67/67 files parsed, near_miss=0 (no
  `mark-superseded` pass), 0 parse failures. Two fixes rode along: discovery
  retry hardened against Wayback flaps (PR #222) and the Job bumped to 4Gi after
  a 1Gi OOM on the COVID-era FY2019-20 PDF. **2010 (96) and 2012 (102) are
  light** — partial-year Wayback "latest captures"; a fuller-capture top-up for
  those two years is an optional follow-up.
- [x] ~~**NV 2021** — scanned-image year PDF; extend the archive route through
  the existing tesseract OCR fallback. (A+gate)~~ — DONE 2026-07-07 (parsers
  #210/#216/#219; Jobs w_homelab #634/#641/#646 dry-runs → #648 real → #649
  prune): **+20 rows** (all of `WARN_2021.pdf`), floor for 2021 established,
  verified per-record via the public API (sum 1198, near_miss=0). `parse_nv_archive`
  OCR-falls-back to `pdf_extract.ocr_word_boxes` (points-normalized word boxes)
  and reuses the word-position parser with 2021 bounds; no Notification column.
  Two rasterizer-sensitivity bugs surfaced across dry-runs and were fixed:
  grouping OCR words by a fixed grid / gap-cluster split or chained rows (13→19
  rows, rasterizer-dependent) → **date-anchor rows** (#219, threshold-free); and
  tight gridline column bounds put count digits on the wrong side, silently
  nulling counts → **midpoint bounds**. Validated end-to-end against the real
  pdf2image+poppler+tesseract path reproduced locally. OCR is Docker-only, so a
  synthetic-word test guards the layout and the skip-guarded fixture test asserts
  all 20 rows + the count total. (NV location fields are None DB-wide — a
  pre-existing NV gap, separate follow-up.)
- [x] ~~**MS straggler quarterlies** — 4 files with a third layout variation
  (e.g. `py2024-q4`), known gap from the PY2020+ run. (A+gate)~~ — DONE
  2026-07-07 (parser #196; prod run w_homelab #627: **+18 rows**, 3 glued
  qtr-1 rows purged, verified per-record; MDES's `py2023-qtr-4` file
  actually carries Q1 content — PY2023-Q4 is published nowhere).

## Track 4 — Records-request (FOIA) pipeline

- [ ] **Send the drafts** — 31 ready in [foia/](foia/), tracker in
  [foia/README.md](foia/README.md). Suggested first wave by recoverable rows:
  NY, TX (pre-2020), MI (pre-Nov-2024). CA 2009–2013 dropped — the probe passed
  (Wayback route, 2026-07-07); only CA **pre-2008** might warrant a request, and
  `cn00`–`cn08` are in Wayback too, so spike that before drafting. **Sending is
  a human action.** (H)
- [ ] **Track + follow up** — once any are sent, agents maintain the tracker
  (sent date, statutory deadline, response), draft follow-ups/appeals. (A+gate)
- [ ] **Ingest responses** — `warn-v2 ingest-file --state XX` per the runbook,
  then `mark-superseded --dry-run` + re-audit. (A+gate)

## Track 5 — Enrichment throughput & data quality

- [ ] **Raise enrichment throughput** — ~16% avg coverage means slow
  convergence against the post-backfill backlog. *Cap-raise done 2026-07-07*
  (w_homelab #630: D&B provider **200 → 400 companies/day**; the doc's earlier
  "~100/day" undercounted even the pre-doubling 200/day cap). Still open:
  measure per-company cost by tier (D&B / EDGAR / Claude) and decide batch-mode
  Haiku vs. a further cap-raise with the cost math. (A+gate)
- ~~**GA full-state-name worksites** — `_choose_city_zip` handles the
  2-letter state form; letters spelling out "Georgia" still fall back to the
  entry page (see STATE_AUDIT source notes). (A+gate)~~ — already done by
  PR #87 (spelled-out state names, 2026-06-26); the STATE_AUDIT note predated
  it. Verified 2026-07-06 with a GA-shaped letter ("Dalton, Georgia 30720"
  picked over the Atlanta recipient block).
- ~~**Audit reads `geocode_source`** — the column
  (`census`/`zip`/`city`/`county`) exists; wiring `warn_v2/scripts/audit.py`
  to it makes geo-accuracy reporting exact instead of inferred (STATE_AUDIT
  "Optional enhancement"). (A+gate)~~ — DONE 2026-07-06: markdown audit table
  gains a `Geo src` per-tier breakdown column (JSON already carried
  `geo_by_source`).

## Track 6 — Frontier (investigate, then decide)

- [x] ~~**OK behind the Aura wall** — spike: Playwright + aura.token capture
  against the Salesforce Experience Cloud portal (stub scraper exists);
  report feasibility before building. (A: spike + report)~~ — DONE
  2026-07-06: no wall after all. The guest Aura Apex action
  `OESC_JS_getWARNLayoffNotices.getListofLayoffAccService` accepts
  `aura.token=null` unauthenticated and returns the full record history as
  JSON — plain httpx, **no Playwright**. Live scraper in
  `warn_v2/scrapers/states/ok.py` (floor 2001-03). See deferred-states.md.
- [ ] **Puerto Rico / territories** — scope whether public WARN sources exist
  at all; report, don't build. (A: spike + report)
- ~~**Failure alerting** — page on `scraper_*` failures from `scraper_runs`
  instead of waiting for the daily audit; Grafana + AlertManager are already
  deployed, so this is likely an alert rule PR. (A+gate)~~ — DONE. Most of it
  shipped with #198 (2026-07-07: `WarnMetricsAbsent`, `WarnEnrichmentStalled`,
  `WarnScrapeStale` at 8d for the weekly tier); the remaining gap — a
  daily-tier state waited 8 days to page — closed with `WarnScraperFailing`
  (chart 0.1.28): ≥2 fetch/parse/storage failures in 50h with no success in
  26h, i.e. ~1 day after a real break; transient single flaps never fire, and
  `validation_failed` is excluded (MA's July fiscal-year rollover fails
  row-count validation for weeks — row drift still pages via the 8d stale
  rule + daily heal loop). Routing verified: AlertManager's default receiver
  posts to the ntfy bridge (w_homelab `alertmanager-ntfy.yaml`), so no
  w_homelab change was needed.

## Accepted / not planned

- **Low-geo tails** in KS (14%), DE (21%), VT (30%) etc. — historical rows
  with no geocodable worksite at source; `backfill-geo` is exhausted
  (STATE_AUDIT "Geocoding root cause"). Accepted.
- **`mostly_estimated_dates`** — the notice+60d fallback is expected WARN-Act
  behavior where the source publishes no real date, not a bug.
- **AR / WY** — WARN data confidential by state statute; requests would be
  denied. Re-verify only on the Track-1 quarterly pass.
- **Aggregator ingestion** — Big Local News / layoffdata.com are a
  completeness cross-check only, never a source (project decision; primary
  sources only).
