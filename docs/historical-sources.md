# Historical WARN sources — per-state backfill routes

Companion to [STATE_AUDIT.md](../STATE_AUDIT.md). The audit says *which* states have
shallow year coverage; this doc says *how to get the missing history*: a published
archive we can ingest with code, or a public-records request (drafts in
[docs/foia/](foia/)).

All URLs and contacts below were verified live on **2026-06-12** (WebFetch probes;
year-URL depths found by probing progressively older years). Big Local News /
layoffdata.com hold historical data for nearly every state — by project decision
they are used **only as a completeness cross-check**, never ingested (primary
sources only).

## Progress (update as backfills run)

- **2026-07-10 — Milestone-sweep wave backfilled in prod: +17,714 rows.** The
  sweep's entire 23-item build queue was built (PRs **#258–#281**), merged, and
  run via the Phase-3 one-off Job train (w_homelab **#709–#715**): the bundled
  Mode-3b states back-to-back (+3,295) and the Wayback states as one serial Job
  (+14,419). All inserts + floors verified via the public API.
  - **Bundled batch**: KY +756 (floor 1998-10) · IA +804 (2005-07) · OR +766
    (**1989-03** — the union has NO mid-2000s gap; ~389 date-less 1990s rows
    dropped, dates only in scanned per-notice PDFs → request; OR ~100 → 866) ·
    WV +366 (2011-03) · VA +221 (1999-07: PY1999/PY2002/PY2003) · MA +204
    (2019-07) · NE +102 (2010-02) · SD +60 (1997-07) · ID +16 (2008-02) ·
    GA +0 (31 COALESCE fills of county/address/closure_type/separation-date
    onto existing GA2022 rows; ids 001–070 not publicly recoverable → FOIA).
  - **Wayback batch**: TX +3,192 (2004-01) · FL +3,003 (1998-01; 2012 is a
    real hole — the site itself had dropped the year) · WI +2,693 (1996-01;
    the 13-row 2016 PCML file DWD abandoned in Feb-2016 excluded) · CT +1,210
    (1998-01; complete 1998–2008 monthly + 2010–2018 yearly) · SC +1,153
    (2009-01; the 2022 Apr–Dec hole closed via the still-live 12-15-2022
    edition; 2013–2021 editions print no notice dates → Jan-1-of-year proxy
    dates) · MS +834 (2004-06; 562 are Non-WARN rows kept but tagged per
    #279 — aggregates exclude them, API total 409) · MD +548 (2000-01) ·
    LA +572 (2007-01; Sep–Dec 2024 published nowhere) · IN +496 (2000-11;
    newly-found gap Jan–Oct 2000) · PA +394 (1998-07; the dry-run-throttled
    1999 Oct+Nov healed on the real run) · MO +235 (2012-07; the sweep's
    550–650 estimate was high — mid-PY capture gaps stay Sunshine-Law) ·
    NC +89 (2013-01; 82 from Warn-2013.pdf + 7 hub-drift amendment dupes —
    4 marked superseded 2026-07-11, 3 non-key-matching variants remain).
  - **UT** shipped via the daily scrape instead (parse-all-sections fix
    #260): first full scrape 2026-07-11 took UT 9→280 rows, floor 2009-01.
  - **Post-run cleanups done**: IA `mark-superseded` real run (2 zip-variance
    pairs marked); WV 2 live employer-variant rows superseded (Mylan
    2021-05-24/1,246 and Monongalia County Coal Resources 2021-06-04/None —
    the state log's revised rows kept); a 12-state mark-superseded sweep
    (2026-07-11) found pairs only in NC — 4 zip-variance pairs marked (AAR
    Manufacturing, Bottom Dollar Food Stores, Fluor Federal Solutions, Stanley
    Furniture), every other state zero.
  - **OR dedup done 2026-07-11** (w_homelab #719): the HECC-master-vs-
    Socrata duplicates never key-match (truncated employer strings, date
    drift) — 73 masters superseded via a track-computed notice-id list
    (live crawl + capture union), count sums verified on every pair,
    866→793 non-superseded; tracks 8509/8352 (absent from Socrata) kept.
  - **Pending follow-up**: VA PY2004–06 Wayback refetch (the sweep's
    "unrecoverable" verdict was wrong — the capture generations exist, a
    local cache bug overwrote them).
- **2026-07-10 — Global-milestone Wayback probe sweep** (every remaining state
  without a known route; verdicts + verified capture URLs + ranked build queue
  in [backfill-milestones.md](backfill-milestones.md)): **~15–20k rows are
  recoverable with no FOIA.** New routes: TX 2004–2018 (+Socrata 2019),
  FL 1998–2019, SC 2009–2025 (2020–2025 PDFs still live but unlinked),
  WI 1996–2016, LA 2007–2024, CT 1998–2018 (holes: 2013 + most of 2009),
  KY 1998–2016, IA 2005–2021, MO Jul-2012–2019, MD 2000–2009 (the Tier-3
  "no pre-2010 archive" claim was wrong), IN 2000–2007, MS PY2010–19 +
  2004–06 + the missing PY2023-Q4, WV 2011–2021, PA Jul-1998–Nov-2000,
  OR ~2009–2020 app captures (+Socrata), UT 2009+ (live page already
  cumulative — scraper fix), VA PY1999 + PY2002–04, NC 2013 + Q4-2012,
  NE 2010–2022 (frozen live endpoint — snapshot soon), GA 2022 (live entry
  pages), SD 1997–2005, ID 2008, MA FY2020 + Jul–Aug 2020. Confirmed
  FOIA-only (nothing was ever published/archived): HI pre-2019, NV pre-2017,
  NM pre-2016, CO/ND/MT pre-2015, DC pre-2005, RI pre-2009, GA 2013–2021,
  TX pre-2004, MS Jul-2007–Jun-2010, MO pre-Jul-2012, VA PY2000–01 +
  Jul-2005–Dec-2009, MA Sep-2020–Mar-2021 + pre-FY2020.
- **2026-07-10 — MI 2000-2024 backfilled in prod** (parsers #247; dry-run
  w_homelab #695, real run merged via #696): **+2,063 rows, MI 105 → 2,168,
  floor 2024-11 → 2000** (verified per-year via the public API). milmi.org
  history via Wayback: the /warn/archive capture's 2016-2024 tables (668
  ingested) + 16 annual PDFs 2000-2015 (1,395). Dry-run exact (17/17 files,
  near_miss=0, already_exists=0); per-year parsed count sums had been
  verified against each report's printed "Total Layoffs" (10/10). The
  2024-Q4 overlap review found zero live duplicates — michigan.gov purged
  pre-2025 *filings*, so live cards are all 2025+ filings. 23 parsed rows
  collapsed by in-batch hash dedup (same employer/city/date worksites, e.g.
  the 2007 Yamaha Kentwood 6/184 pair) — accepted granularity, same as
  CA/PA. Job manifest prune pending.
- **2026-07-09 — JobLink page-1 truncation found + fixed** (PR #241): the
  platform paginates at 25 rows and `fetch()` read page 1 only, so every
  JobLink state-year with >25 notices was silently truncated (live scrapes
  AND the 2026-06 backfills — prod pinned at exactly 25 where the source
  holds more). Source-vs-prod audit per year: **AZ 508 missing** (2020:
  188 vs 25; 2010–2015 absent — the earlier "no pre-2016 data" probe result
  was wrong, the source reaches 2010), **KS 344** (2002–2014 + 2020 capped),
  **DE 37** (source reaches 2007, never exceeds a page), **ME 12** (2020:
  34 vs 25), **VT 3**. `fetch()` now walks the `next_page` links; AZ
  `year_start` 2016→2010, DE 2016→2007. **Pending: gated backfill Jobs for
  AZ/KS/DE/ME/VT** after the fix deploys (~900 rows). Lesson: when a source
  paginates, "prod = exactly the page size" for multiple years is the
  truncation fingerprint — compare paginated source totals, not page-1 counts.
- **2026-07-07 — NC 2014+ backfilled in prod** (parser #213; Jobs w_homelab
  #631 dry-run → #632 real → #650 repair): **+864 rows, floor 2026→2014, NC
  total 913** (verified per-year via `/api/stats/over-time`). Three PDF eras,
  `parse_nc_pdf` dispatches on detected content. Prod verification (the
  geocoding log, not the dry-run's near-miss preview, is what exposes
  address/ZIP bugs) caught two issues, both fixed:
  - **SSRS ZIP/city extraction** (#215/#220): `zip_from` grabbed a 5-digit
    *street number* instead of the trailing `NC <zip>` (19 rows); city walk-back
    swallowed unit letters / directions (`Ste A Greensboro`) and dropped cities
    ending in a suffix word (`Indian Trail`); 2014 letter-spaced city cells
    (`S a l i s b u r y`) collapse now. `_ssrs_city_zip` anchors both on
    `NC (\d{5})`.
  - **ZIP poisoning — root cause in storage** (#220): `_get_or_create_location`
    promoted a zip-less city location *in place* when a zip'd row arrived, but a
    city-level zip-less location (NC publishes no ZIP) is shared by many
    worksites — one historical bad ZIP poisoned the shared Charlotte location
    across **78 notices incl. live 2026 rows** (lat/lon stayed correct). #220
    now promotes only a location backing ≤1 notice; w_homelab #650 purged
    2018–2021, nulled the poisoned ZIPs (→ 0), and re-ran clean (no
    re-poisoning). Lesson: a historical ZIP can bleed onto shared city
    locations via zip-less promotion — verify `Location.zip` after a backfill.
- **2026-07-07 — MA FY22–FY25 backfilled in prod** (parser PR #212, image
  `20260707-221659-222d71a`; Jobs w_homelab #638 dry-run → #640 real):
  **+287 rows, floor FY2025 → 2021-04** (86 → 373 active). mass.gov's "Previous
  WARN reports" links one XLSX per fiscal year at `/doc/fy{NN}-warn-report`;
  `_fetch_ma_fy` discovers + downloads via Playwright (Akamai gates the page
  **and** the files — httpx 403s from the cluster, confirmed; the download works
  from the cluster via Playwright). `parse_ma_xlsx` handles two layouts: FY22/
  FY23 are one sheet **per region** (region = sheet name, positional columns
  under a title+header), FY24+ a single CSV-style sheet with a REGION column.
  Both dry-run and real run were clean (near_miss=0, already_exists=0 all four
  years); FY23 went 80→79 by in-batch hash dedup, so `mark-superseded` was a
  no-op. Verified per-record via the public API (total 373, oldest 2021-04-19
  Hilsinger / 2021-07-07 Sodexo@Suffolk). FY26 stays with the live weekly-CSV
  scraper; pre-FY22 is email-request only (eolwdpress@mass.gov). Prune PR for
  both Jobs to follow.
- **2026-07-07/08 — CA 2006–2013 backfilled in prod** (spike + parser + real
  run, w_homelab #665; prune #669): **+4,180 rows, CA 15,897 → 20,077, floor
  2008 → 2006** (verified via the public API; 2009–2013 hole filled — 2009:425,
  2010:96, 2011:522, 2012:102, 2013:351). 67/67 files parsed, near_miss=0, 0
  parse failures. The interior hole is **recovered from the Wayback Machine — no
  CPRA request needed.** Probe findings:
  - The live EDD page (`.../layoff_services_warn/`) lists **FY2014–2025 only**.
    But EDD's calendar-year listings **2006–2014** survive in web.archive.org
    under `edd.ca.gov/Jobs_and_Training/warn/eddwarncn*.pdf`.
  - Three parallel presentations per year. We ingest the **detailed** variants
    `eddwarncn{da,dbd,del,dmr,ds,dtz}{YY}.pdf` (an A–Z alphabet split, 6 files/
    year): unlike the simple `cn{YY}.pdf` they carry the real **Date Notice
    Received** and a **street address**, so every row gets a unique dedup hash.
    The simple consolidations were rejected (no notice_date/zip → collisions).
  - Files are rolling **year-to-date** snapshots, so discovery takes the
    **latest 200 capture per file** (the earlier ones are partial years).
  - New `parse_ca_detail_pdf` (word-position block parser: fixed columns —
    employer/address x0<300, count+effective date 300–425, Local Workforce
    Investment Area x0≥425; strips `(cid:NN)` glyphs that broke the 2009–2010
    captures; rejoins wrapped employer names). `_discover_ca_historical_urls`
    (Wayback CDX) + the CA `BackfillSpec` now dispatch detailed URLs to it and
    keep the live FY2014+ path on `parse_ca_pdf`.
  - **Volume**: dry-run `would_insert=4,927` → real run inserted **4,180** —
    the gap is cross-file in-batch dedup (one notice in overlapping year
    captures collapses per `notice_id`; multi-wave filings likewise, same
    accepted granularity as PA — the ~6.8K aggregator delta counts per-wave
    line-items). The year-agnostic parser also recovered **2006–2008**
    (`cn06`–`cn08` in Wayback), over-delivering vs the 2009–2013 scope.
  - **Infra fixes** that rode along: `_discover_ca_historical_urls` retry
    hardened with escalating 5/15/30/60s backoff (PR #222) after two runs
    no-op'd on a flapping web.archive.org (`Errno 111`); the Job bumped to 4Gi
    after a 1Gi OOM on the large COVID-era FY2019-20 PDF (pdfplumber).
  - **Caveat / follow-up**: 2010 (96) and 2012 (102) are light vs neighbors —
    partial-year Wayback "latest captures". A fuller-capture top-up for those
    two years is optional. Pre-2005 has only stray boundary rows.
- **2026-07-07 — IL PDF era 1999–2019 parser landed** (`parse_il_pdf`, PR #211
  + column-split fix follow-up): the archive's monthly PDFs are a two-column
  labeled *form*, not a table — `extract_text()` glues each left value onto the
  next right label, so the parser splits every flattened line **at its
  right-column label** (x-independent — the geometry compresses between files,
  e.g. July 2003's labels start ~8px left, which the fixed-x split #211 first
  shipped bisected, dropping the whole month; fixed in the follow-up). Validated
  across four format eras (1999 SIC + `PRIMARY EVENT COUNTY` headers; 2005
  `CITY, STATE` no-ZIP; 2010 NAICS + UNION; 2019 `Monthly WARN Report`) plus the
  shifted layout. SIC (1999–2005) → `extra["sic_code"]`, not `naics_code`.
  Discovery bounded to years ≤ 2019 (2020+ is the ingested XLSX era) and skips
  the WARN Act statute PDF. Backfilled in prod (Jobs w_homelab #635 dry-run →
  #644 real → #645 prune): **+2,707 rows, floor 2020 → 1999** (IL 1,017 →
  **3,732**, verified per-record via the public API — pre-2000 = 149 = the 1999
  rows). near_miss=0 throughout (all rows net-new below the old floor), so
  `mark-superseded` was a no-op; 2,739 parsed → 2,707 inserted by in-batch hash
  dedup (amended notices). **January 2019** — the one image-only scan (OCR
  mangles this gridded form's dates, so `parse_il_pdf` skips it) — was
  hand-transcribed from the legible scan (10 primary table notices; the page-5
  "Supplementals" are amendments the parser skips every month) and ingested
  inline via the storage path (w_homelab #647, +10 rows, 1,223 workers). **IL
  1999–2019 is complete: 3,742 notices.**
- **2026-07-07 — NV 2021 OCR route backfilled in prod** (parsers #210/#216/#219,
  image `20260707-230121-6c24205`; Jobs w_homelab #634/#641/#646 dry-runs →
  #648 real → #649 prune): **+20 rows** (all of `Content/Media/WARN_2021.pdf`,
  a single-page **scanned image with no text layer** — 842×387 px, 20-row
  lattice, 7 cols, no Notification column, the 2022 shape). `parse_nv_archive`
  detects the missing text layer and OCR-falls-back via the new
  `pdf_extract.ocr_word_boxes` (pdfplumber-shaped word boxes, x0/top normalized
  pixels→points), then the word-position parser. Verified per-record via the
  public API: 20 notices, counts sum 1198, near_miss=0 (2021 is a brand-new NV
  year; one pre-existing Rawhide Mine row from another source makes 21 total).
  **Two rasterizer-sensitivity bugs, caught by the dry-runs:**
  - **Row grouping (13→19 rows, rasterizer-dependent).** A fixed-grid
    `round(top/_ROW_BUCKET)` splits a row whose word tops straddle a bucket
    boundary; a gap-cluster instead *chains* rows (city/county words at
    in-between tops bridge two rows into one with two date anchors). Fix
    (#219): **date-anchor rows** — one received-date word per row; assign every
    other word to the nearest anchor by top. Threshold-free, robust to the
    ~1pt top-jitter between poppler (cluster) and pdfium.
  - **Silent count loss (20 rows but nulled counts).** The 2021 x-bounds were
    the tight column gridlines, but OCR word x0 shifts ~1pt between rasterizers:
    poppler puts count digits at x0≈238.8, left of the `b_type=239` bound, so
    the count fell into the type column and was nulled while the row survived
    (invisible to a row-count check). Fix (#219): bounds are now **midpoints
    between the observed OCR column x-ranges** (25–50pt margins).
  Validated end-to-end by reproducing the exact `pdf2image`+poppler+tesseract
  path locally (installed tesseract + poppler). OCR is Docker-only, so a
  synthetic-word test guards the layout in CI and the skip-guarded fixture test
  asserts all 20 rows **+ the count total** (a nulled count a row-count misses).
  NV city/county are None DB-wide (live + all archive years) — a pre-existing NV
  location gap, tracked separately, not caused by this backfill.
- **2026-07-07 — MS stragglers + NJ workbook backfilled in prod** (parsers
  #196/#197, image `20260707-202905-5a80b93`; Jobs w_homelab #626 dry-run →
  #627 real → #629 prune): **MS +18** from the 4 stacked-header quarterlies
  (124 → 139 after purging 3 glued-employer qtr-1 rows — the June run had
  ingested "Alan Ritchey, Inc. Southaven (DeSoto)"-style rows with city=None;
  deletes were guarded on the exact glued string + the clean replacement
  existing). **NJ +2,203** from the cumulative `WARN_Notice_Archive.xlsx`
  (floor 2026-01 → **2004-01**, 2,282 total; 2,349 parsed → 2,281 after
  in-batch hash dedupe; dry-run near_miss=0 and every pre-existing prod row
  hashed identical to its workbook copy). Both verified per-record via the
  public API. Note: MDES posted PY2023-Q1 content under the `py2023-qtr-4`
  slug — PY2023-Q4 (Apr–Jun 2024) itself is published nowhere.
- **2026-07-06 — OH first backfill run in prod** (w_homelab #595, one-off Job
  per the runbook): **+2,319 rows, 22/31 years OK** (1996–2024 attempted;
  2025/2026 are expected misses — no source / live-scraper year). The 7 real
  gaps were discovery failures, fixed same day:
  - **2007–09, 2011, 2013 (.stm era)**: the nearest-to-2020 Wayback anchor
    resolved these years to dead 302 captures. Discovery now pins the latest
    200-status capture per year via the CDX index (anchored slug variants
    kept as fallback).
  - **2023/2024 (portal era)**: the June-2026 JFS restructure 404'd the old
    portal deep links. The per-year pages moved under the live scraper's
    `job-workforce-services` section and now link a `dam.assets.ohio.gov`
    CSV (live-CSV shape; parser reused, plus Notice ID column, 2-digit
    layoff-date years, and compound "Date Received" cells). Old-portal
    Wayback captures (2025-06, status 200) kept as fallback.

  **Re-run 2007–2024 pending** (already-ingested years dedupe by
  `notice_id`; upserts are fill-only).
- **2026-07-02 — CO backfilled in prod** (found in the aggregator cross-check,
  PR #103; fixed in PR #110): the scraper had been frozen on CDLE's 2021 sheet,
  reporting "ok" daily with 43 rows since Dec 2021. The nightly scrape on the
  #110 image did the full 12-sheet sweep: **44 → 811 notices (2015–2026,
  +768)**; 811 vs the 842 parsed rows = intra-source duplicates collapsing to
  one content hash. Existing rows hashed identically (no duplicate churn). The
  junk 1957 form-spam row was purged via a one-shot GitOps Job (w_homelab
  #569) and `as_date`'s 1988 floor blocks re-entry. The regular scraper now
  reads only the two newest sheets; history re-runs via
  `backfill-historical --state CO`.
- **2026-07-02 — KY correction + KY/LA/NV backfill routes added** (aggregator
  cross-check follow-up, PR #103):
  - **KY**: the 2026-06-12 run's "+54 (2021+)" was wrong — the 2021–2024
    SharePoint folders hold only `.xls`/`.xlsx` (no CSVs), so `_fetch_ky_year`
    silently skipped them and the +54 rows were all from the 2025 CSV. The DB
    floor never moved below 2025. New route: any recent `.xlsx` workbook in
    the year folders carries **one sheet per year back to 2017** (~356 rows
    2017–2024); `backfill-historical --state KY` now discovers the newest
    workbook by `TimeLastModified` and skips CSV-era (2025+) sheets.
  - **LA**: the cumulative `WarnNotices2025.pdf` uses a different layout
    (no banner, no Address column, employer+address merged) that the old
    parser could not read; parse is now layout-tolerant and
    `backfill-historical --state LA` ingests the still-published years
    (2025+; ~23 more 2025 rows). Pre-2025 files remain pruned → request.
  - **NV**: per-year archive PDFs found (probed live 2026-07-02):
    `Content/Media/{2017..2020}.pdf` (lattice tables), 2022 + 2024 + 2025
    dated "Master" snapshots (word-position layouts, per-era x-bounds), 2023
    via Wayback replay. ~600 rows 2017–2025H1. Gaps: **2021** is a scanned
    image (needs OCR — done 2026-07-07, see below), **Jun–Dec 2025** is
    published nowhere (the master rotated to 2026 before the scraper first
    ran) → keep in the NV request.
  - **Prod runs done same day** (image `963e168`, one-off Jobs per the
    runbook): **LA +23** (2025-01 floor, 28 total), **KY +343** (floor
    2025→2017-01, 427 total), **NV +584** (floor 2025→2017-01, 601 total;
    2020 alone holds 369). All dry-run near-miss previews and
    `mark-superseded --dry-run` passes came back **zero**. The first dry-run
    caught two bugs fixed in PR #122: KY's SharePoint 403s httpx's default
    UA on file downloads (Mode-2 fetch now sends a browser UA), and the NV
    2025 entry pointed at the `05_15.25` snapshot whose page size differs
    from the `06_03.25` file the x-bounds were measured from (0 rows).
    In-batch hash dedup explains seen-vs-inserted deltas (e.g. KY 356→343):
    same employer + date rows collapse to one `notice_id`.
- **2026-06-12 — KS / ME / VT backfilled in prod** (image `2a1a93a`, one-off
  Jobs per the runbook below): KS 7→549 active (1999–2026, +542), ME 3→79
  (2012–2026, +76), VT 4→96 (2003–2026, +91). Dry-run near-miss previews and
  post-run `mark-superseded --dry-run` all came back **zero** — JobLink
  historical rows hash identically to live rows. Expected residue: low geo/PDF
  % on old notices (nightly `backfill-geo` + `download-pdfs` chip at it).
  STATE_AUDIT.md's generated table predates these runs — regenerate it on the
  next trusted audit.
- **2026-06-12 — TX / FL / HI / KY / NM backfilled in prod** (image `8a7f48c`,
  PR #48): TX +2,166 (2020–2026), FL +2,167 (2020–2026, paginated), HI +401
  (2019–2026), KY +54 (2021+), NM +109 (2016–2025). All dry-runs zero
  near-misses; all `mark-superseded --dry-run` passes zero pairs. FL 2026
  page 2 held 15 rows the live scraper had never ingested (it reads page 1
  only) — the backfill picked them up.
- **2026-06-12 — MD / WI / IL / MS backfilled in prod** (images `2b25547` +
  `9394b9d`): MD +1,257 (2010–2025), WI +320 (2016–2019, `--year-end 2019`),
  IL +861 on the rerun after the NAICS-overflow fix (2020–2026; first attempt
  aborted mid-batch and its committed files were skipped idempotently),
  MS +112 (PY2020+; 19 of 23 quarterlies parse — 4 stragglers, e.g.
  `py2024-q4` / `py2023-qtr-4`, have yet another layout variation, left as a
  known gap). All near-miss previews and `mark-superseded --dry-run` passes
  **zero**. Same day: `download-pdfs --prune-non-pdf` removed 420 stored
  non-PDF files + 108 dangling refs, and an uncapped `download-pdfs` drain
  Job re-fetched the real-PDF backlog (1,000+ files).
- **Wave 2A probe outcomes (2026-06-12)** that changed the original design:
  - **WI**: the Google Sheet is cumulative from 2020-01 only (no per-year
    tabs). 2016–2019 live as static pages `/dislocatedworker/warn/{year}/
    default.htm` → dedicated `parse_wi_archive_html`; run with
    `--year-end 2019`.
  - **MN — run deferred to Wave 2B.** mn.gov removes old asset files, so
    discovery now returns Wayback replay URLs; annual summaries (2018–2021,
    no month token in filename) are excluded. The remaining blockers are
    parser eras: 2015–2016 monthlies parse 0 rows, and 2022–2024 wide-format
    monthlies fall into the text fallback that glues employer+city+industry
    into one string (live 2025+ rows are clean) — a proper multi-era parser
    rides with the OH/PA wave.
  - **NY**: the Tableau CSV is current-year only and ignores year-filter
    params → no cheap win; per-year PDF route or FOIA (Wave 2C decision).
  - **IL**: archive page also holds monthly **PDFs back to 1999** (not 2002
    as previously noted) — PDF era still deferred.
- Remaining Wave 2: OH gap-year re-run (2007–2024), PA 2001+ (Wayback-era
  parse, strict dedup), MN multi-era parser, NC PDFs 2014+, NJ cumulative
  xlsx, MA FY xlsx.
- **FOIA drafts in [foia/](foia/) are written but unsent** — tracker in
  foia/README.md; ingest responses with `warn-v2 ingest-file`.

**Runbook per state**: `--dry-run` pilot on 1–3 early years → inspect the
near-miss preview in the Job logs → full run (stop at `--year-end <DB floor>`
when formats differ) → `mark-superseded --state XX --dry-run` → re-audit.
One-off Jobs: image from the live deployment, `args: ["backfill-historical",
"--state", "XX", ...]`, `DATABASE_URL` via secretKeyRef `warn-v2-db/url`,
delete Jobs after.

## Tier 1 — published archive: ingest with code

| State | DB floor | Source / route | Available back to | Backfill route |
|-------|----------|----------------|-------------------|----------------|
| CA | ~~2014~~ **2006 ✅** | Live EDD page publishes **FY2014–2025 only** (verified 2026-07-07). Pre-2014 calendar-year reports survive in **Wayback** at `edd.ca.gov/Jobs_and_Training/warn/eddwarncn*.pdf`. We ingest the **detailed** A–Z slices `eddwarncn{da,dbd,del,dmr,ds,dtz}{YY}.pdf` (6/year, carry notice-received date + street address; the simple `cn{YY}` consolidations lack both → dedup collisions, rejected). Rolling year-to-date snapshots → take the **latest 200 capture per file**. Records are two-column (LWIA name wraps at x0≥425) with `(cid:NN)` glyphs in 2009–2010 | **2000** (Wayback: detailed HTML 7-slice `eddwarncnd*{03,04,05}.htm/.asp` for 2003–2005, simple 2-slice `cnal`/`cnmz` HTML for 2000–2002 under `www.edd.ca.gov/warn/` — verified 2026-07-09; nothing pre-2000) | **done 2026-07-08** (`parse_ca_detail_pdf` + `_discover_ca_historical_urls`, Wayback CDX; real run w_homelab #665, prune #669): **+4,180 rows, CA 15,897→20,077, floor 2008→2006**, near_miss=0, 0 parse failures (verified via public API). 2010/2012 light = partial-year captures. `rows_new` (4,180) < dry-run `would_insert` (4,927) via cross-file dedup |
| CO | ~~2021~~ **2015 ✅** | one Google Sheet per year linked from `cdle.colorado.gov/employers/layoff-separations/layoff-warn-list` (co.py registry + link discovery; regular scraper reads only the two newest sheets) | **2015** | **done 2026-07-02** (+768, via the #110 full sweep); re-runs via year loop (`--state CO`); pre-2015 confirmed never published (sweep 2026-07-10) |
| KS | ~~2026~~ **1999 ✅** | `kansasworks.com/search/warn_lookups?q[notice_on_gteq]=YYYY-01-01` (JobLink date-range search) | **1999** | **done 2026-06-12** (+542) |
| ME | ~~2026~~ **2012 ✅** | `joblink.maine.gov/search/warn_lookups` (JobLink) | **2012** | **done 2026-06-12** (+76) |
| VT | ~~2026~~ **2003 ✅** | `vermontjoblink.com/search/warn_lookups` (JobLink) | **2003** | **done 2026-06-12** (+91) |
| FL | ~~2026~~ ~~2020~~ **1998 ✅** | `reactwarn.floridajobs.org/WarnList/Records?year=Y` — paginated (e.g. 2020 = 1,337 records); page links followed | **1998** (Wayback `warn.asp` year pages 1998–2018 + reactwarn 2019) | **done 2026-06-12** (+2,167, 2020+); **pre-2020 done 2026-07-10** (+3,003, floor 1998-01); **2012 is a real hole** — the site itself had dropped the year (sole capture header-only) → request |
| TX | ~~2026~~ ~~2020~~ **2004 ✅** | `warn-act-listings-{year}-twc.xlsx` — **only 2020+ still resolve** (pre-2020 files removed from twc.texas.gov; the old `/files/news/` era is dead; Socrata `data.texas.gov/dataset/8w53-c4f6` starts 2019-01, 2,363 rows — verified 2026-06-12) | **2004** (Wayback XLS/XLSX 2004–2018, two hosts) | **done 2026-06-12** (+2,166, 2020+); **pre-2020 done 2026-07-10** (+3,192, floor 2004-01: Wayback 2004–2018 + Socrata 2019); pre-2004 → request |
| NC | ~~2026~~ ~~2014~~ **2013 ✅** | archive hub `commerce.nc.gov/...warn-summary-report-archives` → per-year **PDF** documents with irregular slugs (`warn-report-2019/open` etc.); three layout eras — summary-count text 2013–~2017, SSRS grid ~2018–2021, live-schema grid 2022+; 2013 = pinned Wayback capture appended by `_discover_nc_pdf_urls` | **2013** | **done 2026-07-07** (+864, floor 2026→2014; three-era `parse_nc_pdf`); see Progress for the ZIP-poisoning fix; **2013 done 2026-07-10** (+89, floor 2013-01: 82 from Warn-2013.pdf + 7 hub-drift amendment dupes pending mark-superseded); Q4-2012 unrecoverable — no rolling `Warn.pdf` capture for Dec-2012 in CDX |
| NJ | ~~2026~~ **2004 ✅** | cumulative `nj.gov/labor/assets/PDFs/WARN/WARN_Notice_Archive.xlsx` — one sheet per year, same 5 columns as the live PDF (23 sheets 2004–2026, 2,349 rows) | **2004** | **done 2026-07-07** (+2,203, near_miss=0; see Progress) |
| NM | ~~2025~~ **2016 ✅** | per-year PDFs on `dws.nm.gov/Rapid-Response` (filenames vary 2016–2018 → discovered from the hub's anchors) | **2016** | **done 2026-06-12** (+109); pre-2016 → request |
| HI | ~~2026~~ **2019 ✅** | `labor.hawaii.gov/wdc/{year}-warn-notices/`; hub `real-time-warn-updates` lists 2019–2026 | **2019** | **done 2026-06-12** (+401); pre-2019 → UIPA request |
| KY | ~~2025~~ ~~2017~~ **1998 ✅** (the earlier "2021 ✅" claim was wrong) | per-year CSVs exist only for **2025+**; the 2021–2024 folders hold `.xls`/`.xlsx` instead, and any recent `.xlsx` workbook carries **one sheet per year back to 2017** (verified 2026-07-02; see Progress) | **1998** (Wayback kcc.ky.gov year-per-sheet workbooks) | **done 2026-07-02** (+343, workbook route); **pre-2017 done 2026-07-10** (+756, floor 1998-10: Wayback workbooks 1998–2016) |
| MO | ~~2019~~ **2012-07 ✅** | `jobs.mo.gov/warn/{year}` — the regular scraper **already crawls 2019–present every run** | **2012-07** (Wayback consolidated log + PY pages) | **pre-2019 done 2026-07-10** (+235, floor 2012-07 — real recoverable was ~235, not 550–650); mid-PY capture gaps (Sep 2015–Jun 2016, May–Jun 2017, Jan–Jun 2018) have no Wayback coverage; those + pre-Jul-2012 → request |
| OH | ~~2026~~ **1996 ✅** (gap years 2007–09, 2011, 2013, 2023–24 pending re-run) | Four eras (probed 2026-06-12, re-probed 2026-07-06), all via httpx — **no Playwright**: **1996–2006** per-year PDFs (`WARN_{y}.pdf` / `Warn_{y}.pdf`, Wayback replay); **2007–2019** `.stm` files that actually serve Excel-exported PDFs (Wayback replay pinned per year via CDX — the nearest-to-2020 anchor hit dead 302 captures; slug variants as fallback); **2020–2022** `archive.stm?year=Y` HTML (live-table layout, Wayback); **2021–2024** per-year pages on the June-2026 site linking a `dam.assets.ohio.gov` CSV (live-CSV shape; old JSON portal retired — Wayback captures kept as fallback). **2025 unaccounted for** (no live page, nothing in CDX) | **1996** | first run **done 2026-07-06** (+2,319, 22/31 years, w_homelab #595); gap-year discovery fixed same day → **re-run 2007–2024**; 2025 → investigate/FOIA |
| PA | ~~2024~~ ~~2001~~ **1998-07 ✅** | Live AEM page holds accordion sections **2023–2026 only** (probed 2026-06-12). Pre-2023: **archived per-month pages, two hosts, same content template** (probed 2026-07-06) — `portal.state.pa.us/portal/server.pt/community/{yr}/10542/{month}_{year}_warn_notices/{id}` (2001–2015) and SharePoint `dli.pa.gov/.../warn/notices/Pages/{Month}-{Year}.aspx` (2011–2022); CDX-discovered, SharePoint capture preferred on overlap. **262/264 months archived** (missing: 2021-10, 2022-04 — never captured). Month pages carry no per-notice filing date → `notice_date` = first-of-month proxy. 2005 live sample: 256 rows, full city+count | **1998-07** | **done 2026-07-07** (+3,158 rows 2001–2022; 262/262 archived months verified per-month in prod after two throttle top-ups; 2017–2022 purged + re-ingested post-#183). `mark-superseded` not needed — the one flagged row was junk the purge removed; **pre-2001 done 2026-07-10** (+394, floor 1998-07; the dry-run-throttled 1999 Oct+Nov healed on the real run; `dec00` never captured — permanent gap) |
| IL | ~~2025~~ ~~2020~~ **1999 ✅** | `illinoisworknet.com/LayoffRecovery/` archive — monthly XLSX 2020+, monthly **PDFs 1999–2019** (a two-column labeled *form*, not a table — each flattened line split at its right-column label, x-independent) | **1999** (PDF era) | xlsx era **done 2026-06-12** (+861); **PDF era done 2026-07-07** (`parse_il_pdf` #211 + fix #217; Jobs w_homelab #635/#644/#645): **+2,707 rows, floor → 1999**. Jan 2019 (sole image-only scan) hand-transcribed + ingested (#647, +10). **IL 1,017 → 3,742, complete 1999–2019** (API-verified, near_miss=0) |
| NY | ~~2025~~ **2006 (crosstab)** | `dol.ny.gov/warn-dashboard` Tableau CSV is **current-year only and ignores year-filter params** (verified 2026-06-12). **Probed 2026-07-06, three eras**: (1) old ASP portal `labor.ny.gov/app/warn/details.asp?id=N` — **4,294 unique ids archived in Wayback (ids 3–9536, ~2001–2020), each a full record**: street address, county/WIB/region, business type, **Number Affected**, layoff + closing dates, reason. Enumerate straight from CDX (`details.asp*`, status 200); per-year `default.asp?warnYr=Y` listing snapshots are too sparse to drive discovery. (2) Year-summary PDFs `{Y}-nys-warn-notices.pdf` 2016–2020 — index-style (posted/notice dates, employer, region; **no counts/addresses**; 2020 = 160 pp, clean text layer); live URLs 403, Wayback replay works. (3) dol.ny.gov 2021+: per-notice PDFs/HTML + `/2023-warn-notices`, `/2024-warn-notices` hubs (JS/paginated). | **2001** (Wayback details) | **Wayback CDX detail-page harvest recovers the bulk (~4.3k rows incl. counts + addresses) with no FOIA wait**; year PDFs + modern pages fill listing-only rows; keep the FOIA draft as the completeness backstop (un-archived notices, rescissions). **Superseded 2026-07-08 by the dashboard crosstab** — `dol.ny.gov/warn-dashboard` Download→Crosstab returns the full **2006–2026 history (9,006 rows, 8,812 w/ counts)** in the live CSV's schema (the default Tableau `.csv` endpoint is current-year only; the crosstab needs a browser session, so a normalized snapshot is bundled gzipped in-repo and run via `backfill-historical --state NY`). The Wayback CDX detail-page parser was removed. **Ingested 2026-07-08** (w_homelab #672): purged 492 stale Wayback rows + loaded the crosstab → **prod NY = 8,708 rows, 2006–2026, 98% w/ counts** (floor 2025→2006). Refresh by re-downloading the crosstab + regenerating the .gz. |
| MD | ~~2026~~ ~~2010~~ **2000 ✅** | archived per-year pages `warn{year}.shtml` (verified 2010–2024; old pages use `WIA Code`/`Type Code` headers) | **2000** (`warn2000`–`warn2009` captures found — sweep 2026-07-10; the earlier "no pre-2010" claim was wrong) | **done 2026-06-12** (+1,257); **2000–2009 done 2026-07-10** (+548, floor 2000-01 — same page family the parser already handles) |
| MI | ~~2024~~ **2000 ✅** | **Wayback-only** (probed 2026-07-09): milmi.org published the history; live milmi.org/warn redirects to the pruned LEO page and the files 404. 2016–2024 = per-year HTML tables in the `/warn/archive` capture 2025-06-21 (676 rows); 2000–2015 = annual PDFs `warn{2000..2015}.pdf` (capture 2021-07-15), text tables, numeric incident codes 2000–2006, rescinded rows kept at count 0 | **2000** | **done 2026-07-10** (+2,063; see Progress). Parser: (`parse_mi_archive_html` + `parse_mi_archive_pdf`, static 17-URL Wayback list; parsed sums verified against every report's printed "Total Layoffs"). Remaining: the gated prod Job — ⚠ dry-run review must eyeball the 2024-Q4 overlap with live rows: archive rows carry the real filing date as notice_date while live cards use the layoff date, so duplicates will NOT hash-collide or show as near-misses; compare employers by hand and plan a purge/supersede of the live-source duplicates |
| WI | ~~2020~~ ~~2016~~ **1996 ✅** | the Google Sheet is **cumulative from 2020-01 only** (no per-year tabs); 2016–2019 are static pages `/dislocatedworker/warn/{year}/default.htm` | **1996** (Wayback `worknet.wisconsin.gov` PCML XLS logs) | **done 2026-06-12** (+320, `--year-end 2019`); **pre-2016 done 2026-07-10** (+2,693, floor 1996-01: PCML logs 1996–2015; the 13-row 2016 file DWD abandoned in Feb-2016 excluded — all already in prod) |
| MN | ~~2023~~ **2012 ✅** | DEED PDFs via Wayback CDX replay (mn.gov prunes old assets): monthlies 2015–2016 + 2022+, annual summaries 2018–2021; the Dec-2016 cumulative reaches month sections back through **2014**. The 2022–24 year-end cumulative roll-ups are **skipped** in discovery (`_drop_cumulative_reports`) — they re-list the monthlies with glued employer cells and doubled counts | **2012** (earliest filing date; 2016 cumulative reaches ~2014, older filings via annuals) | **done 2026-07-10** (`_parse_archive_words`, word-position columns from header labels; WARN=YES only). Prod backfill ran (w_homelab #679); data-quality fix #237 then corrected three 2023–25 bugs — cumulative roll-ups ingested alongside monthlies (glued employers + 2× counts), right-aligned counts dropped into the TAA column, and the live chain not stripping DEED's trailing report year. Purge + clean re-ingest via w_homelab #685 (Jobs pruned #686) verified in prod: **541→482 rows** (59 strays purged), **2023–25 glued dupes → 0**, **missing counts 66→4** (2019 45→0, 2024 Yelloh 9→0 via the idempotent upsert) |
| MS | ~~2025~~ ~~PY2020~~ **2004-06 ✅** | MDES quarterly PDFs — `_discover_pdf_urls()` already returns all 23 (PY2020Q1+); old quarterlies merge "Company Name, City" (parser splits the trailing "City (County)" line) | **PY2020** (Jul 2020) | **done 2026-06-12** (+112; 4 quarterlies with a third layout variation skipped — known gap); older → ~~request~~ **Wayback PY2010–PY2019 (all 40 quarters) + 2004–2006 era + the missing PY2023-Q4** (sweep 2026-07-10; **parser built 2026-07-10**: archive-era layout family in `ms._parse_archive_tables` + 52-URL pinned replay list `ms._ARCHIVE_CAPTURES`, ~272 WARN rows verified offline — quarterlies mix flagged "Non-WARN"/"Existing Business & Industry Listing" Rapid-Response events, which are **kept and tagged `closure_category = "Non-WARN"`** (~562 more archive rows; every era's parser reads Reason/Comments since 2026-07-10 — aggregates/reports exclude the category by default). Prod's 43 pre-existing unfiltered PY2020+ Non-WARN rows retagged via one-off Job; **prod backfill done 2026-07-10**: +834, floor 2004-06 (272 WARN + 562 tagged Non-WARN; API total 409); note the PY2023-Q4 header actually reads "PROGRAM YEAR 2023" — the sweep's "mislabels 2024" claim was a misread); Jul 2007–Jun 2010 → request |
| MA | ~~2025~~ ~~FY2022~~ **2019-07 ✅** | mass.gov WARN page publishes **FY22–FY25 XLSX reports** — "Previous WARN reports" links one XLSX per FY at `/doc/fy{NN}-warn-report/download` (discover via Playwright: Akamai gates the page and the href has no `.xlsx`). Two layouts: FY22/FY23 one sheet per region (region = sheet name), FY24+ single CSV-style sheet. | **FY2020** (2019-07) | **done 2026-07-07** (+287, 86 → 373; see Progress); **pre-FY22 done 2026-07-10** (+204, floor 2019-07: Wayback FY2020 .xls + FY21-through-Aug-2020 .xlsx); email for Sep 2020–Mar 2021 + pre-FY2020 |
| WA | ~~2026~~ **2004 ✅** | `fortress.wa.gov/esd/file/warn/Public/SearchWARN.aspx` — ASP.NET `__VIEWSTATE` GridView; the scraper now replays the `Page$N` postback for every page (99 pages, ~15 rows each) | **2004** | **done 2026-07-07** (pagination fix; live fetch = 1,480 rows, floor 2004-01; deploys via the daily scrape, no one-off Job) |
| OR | ~~2020~~ **1989-03 ✅** | **Socrata `data.oregon.gov/ijbz-jpx8` verified 2026-07-09**: official WARN dataset, 397 rows 2020-03→2026-05 (one row per worksite *and* layoff phase; ~2-month update lag). The live HECC tracker (`ccwd.hecc.oregon.gov/Layoff/WARN`) purged everything pre-2020 around Nov 2025 — prod is missing most recent notices (2024: 3 vs 71) despite `ok` runs. Pre-purge history recovered from Wayback captures of the list app (pages 1–22 × 13 sort variants × several crawl epochs): a single 2025-05/06 epoch yields 1,045 of the ~1,050 rows the app reported, so the union is effectively complete — **no mid-2000s gap**, the thin 2010–11 counts are real | **1989** (capture union, dated rows only) | **done 2026-07-10** (+766, floor 2020→**1989-03**, OR ~100 → 866): live Socrata fetch (397 rows → 336 after per-site/phase grouping in `parse_or_socrata`) + bundled `or_archive.tar.gz` capture union (461 dated master rows 1989–2026 whose tracks Socrata lacks; regeneration procedure in `states/or_.py`). **Dedup done 2026-07-11** (w_homelab #719): 73 HECC masters duplicated by Socrata rows (facility vs legal employer names, same track #) superseded via a track-computed notice-id list, 866→793; ~389 date-less 1990s rows dropped (dates only in per-notice scan PDFs) → request |
| NV | ~~2025~~ **2017 ✅** | per-year PDFs under `detr.nv.gov/Content/Media/` in three layout eras (see `nv._ARCHIVE_SOURCES`); 2023 pruned live → Wayback; **2021 scanned image → OCR route done 2026-07-07**; 2025 snapshot ends Jun 3 | **2017** | **done 2026-07-02** (+584) + **2021 OCR +20 (2026-07-07)**; Jun–Dec 2025 + pre-2017 → request (pre-2017 confirmed never published — sweep 2026-07-10) |
| LA | ~~2026~~ ~~2025~~ **2007 ✅** | `WarnNotices{year}.pdf` — only 2025+ still resolve; the 2025 file's layout (no Address column) now parses | **2007** (Wayback `WarnNotices{2007..2024}.pdf`) | **done 2026-07-02** (+23); **pre-2025 done 2026-07-10** (+572, floor 2007-01; only 2024 is partial — captured 2024-08-12, Sep–Dec 2024 published nowhere); pre-2007 → request |

Rows added by the **2026-07-10 milestone sweep** (capture URLs, caveats, and
the ranked build queue live in [backfill-milestones.md](backfill-milestones.md));
**all of these ran in prod 2026-07-10** (see the wave Progress entry above):

| State | DB floor | Source / route | Available back to | Backfill route |
|-------|----------|----------------|-------------------|----------------|
| SC | ~~2026~~ **2009 ✅** | Wayback `scworks.org/docs/librariesprovider6/layoff-notification-reports/{Y}_layoff_notifications*.pdf` 2009–2019 + **still-live unlinked** dew.sc.gov/scworks.org year PDFs 2020–2025 | **2009** | **done 2026-07-10** (+1,153, floor 2009-01); the 2022 Apr–Dec hole closed via the still-live 12-15-2022 edition; residual holes only Dec 16–31 2022, Dec 2023, Dec tails of 2016/17/19 → request; 2013–2021 editions print no notice dates → Jan-1-of-year proxy dates (documented convention) |
| UT | ~~2026~~ **2009 ✅** | the live page (`jobs.utah.gov/.../warnnotices.html`) already holds per-year sections **2009–2026** — the scraper read only the current year until fix #260 (parse all year sections) | **2009** | **done 2026-07-11** via the daily scrape (9→280 rows, floor 2009-01, API-verified); pre-2009 never published |
| IA | ~~2021~~ **2005-07 ✅** | Wayback rolling-log snapshots, union of 4 (`WARN_20150722.pdf`, `WARN_20171219.xlsx`, `WARN_20210105.xlsx`, `WARN_20230823.xlsx`) | **2005-07** | **done 2026-07-10** (+804, floor 2005-07): bundled as `ia_archive.tar.gz` (Mode 3b), run via `backfill-historical --state IA`. XLSX members reuse `IAScraper.parse`; PDF era has its own parser (U+2010 hyphens normalized so overlap rows hash-collide). "Amendment" rows kept as in the live log; the real `mark-superseded --state IA` pass marked 2 zip-variance pairs. Pre-2005 never published |
| NE | ~~2023~~ **2010 ✅** | **frozen live endpoint** `dol.nebraska.gov/LayoffServices/WARNReportData/?year={2010..2020}` + Wayback captures of the rolling page for 2021–22 | **2010** | **done 2026-07-10** (+102, floor 2010-02) |
| WV | ~~2021~~ **2011 ✅** | Wayback cumulative `WV_WARN_Notices_3-1-11_to_6-7-21.pdf` (capture 1 MiB-truncated: fonts lost, content streams intact — `parse_wv_archive_pdf` reconstructs text from the raw streams) | **2011** | **done 2026-07-10** (+366, floor 2011-03): bundled `wv_archive.tar.gz` (Mode 3b), cross-checked against the complete through-Aug-2014 edition; post-run 2 live employer-variant rows superseded (Mylan 2021-05-24 / Monongalia County Coal Resources 2021-06-04 — the state log's revised rows kept) |
| CT | ~~2019~~ **1998 ✅** | Wayback: monthly pages 1998–2008 (`warnreports{Y}-{M}.htm`, variant names 1998–2000) + yearly `warn{Y}.htm` 2010–2018 | **1998** | **done 2026-07-10** (+1,210, floor 1998-01; complete 1998–2008 monthly + 2010–2018 yearly); holes: all of 2013, 2009 except Aug/Sep → request |
| IN | ~~2008~~ **2000-11 ✅** | Wayback DWD pages, 3 generations: `workforce_stats/warn/{2000..2003}.html`, rolling `notices.html` 2003–05, accumulating `employers/warn_notices.html` 2005–07 | **2000-11** | **done 2026-07-10** (+496, floor 2000-11); gaps Jan–Oct 2000 (newly found — the archived 2000.html starts Nov 3), Nov–Dec 2004, Oct–Dec 2007 |
| VA | ~~2010~~ **1999-07 ✅** (partial) | Wayback: PY1999 XLS + PY2002 PDF + PY2003 Excel-HTML `_files/sheet00N.htm` | **1999-07** (partial) | **done 2026-07-10** (+221: PY1999/PY2002/PY2003); **PY2004–06 ARE recoverable — Wayback refetch follow-up build** (the sweep's "unrecoverable" verdict was a local cache bug); PY2000–01 + Jul-2006–Dec-2009 unrecoverable → request |
| SD | ~~2007~~ **1997 ✅** | Wayback frozen cumulative PDF `WARN Notices Received.pdf` (Jul-1997→Dec-2005, 60 notices) | **1997** | **done 2026-07-10** (+60, floor 1997-07); gap 2006→Apr-2007 (~0–5 notices) |
| ID | ~~2009~~ **2008 ✅** | Wayback `labor.idaho.gov/pdf/WARNNotice.pdf` (2008 rows dropped from the current live log) | **2008** | **done 2026-07-10** (+16, floor 2008-02) |
| GA | 2023 | still-live TCSG `warn-public-view/entry/{id}/` pages for 2022 (verified GA202200071) | **2022** (partial) | **run 2026-07-10**: only 31 entries recoverable (ids 071–103 minus pruned 083/097) → +0 inserts, 31 COALESCE field fills onto existing GA2022 rows; **ids 001–070 NOT publicly recoverable** (single-entry route renders an empty shell outside the server-side-filtered view) → request with 2013–2021 |

## Tier 2 — investigated, resolved

- **AK** — interior year gaps (2009, 2011, 2014) are **real**: the cumulative source
  page (`jobs.alaska.gov/rr/WARN_notices.htm`, 2006–present) lists zero notices for
  those years. No backfill possible or needed; optional confirmation in the OR/AK
  inquiry drafts.
- **MI** — michigan.gov **removed pre-2025 notices** from the public search (the
  Sitecore index held Count=559 in the 2025-04-30 Wayback API capture vs 103
  live — purged mid-2025), but the history survives on **milmi.org** in Wayback
  (re-probed 2026-07-09; live milmi.org/warn redirects to the pruned LEO page):
  `milmi.org/warn/archive` capture 2025-06-21 carries per-year HTML tables
  **2016–2024** (685 rows, 5-col schema), and annual PDFs
  `.../_docs/publications/warn/warn{2000..2015}.pdf` (captures 2021-07-15 /
  2016-10-15) cover **2000–2015** with clean text tables. 193 per-notice letter
  PDFs are also archived under michigan.gov `WD-DATA_PUBLIC_WARN_NOTICES4/`.
  → scraper backfill (ROADMAP Wave 3); foia/mi.md stays as a completeness
  backstop only.
- **LA** — only `WarnNotices2025.pdf`+ resolve; 2020–2023 return 404 (despite earlier
  reports of 2024 existing — the agency appears to prune old files). 2025 is now
  ingestable (Tier 1); pre-2025 → records request.
- **GA** — the 264-vs-~3,200 count anomaly vs layoffdata.com (PR #103) is **not
  under-scraping**: the TCSG GravityView backend reports `recordsTotal=265` and we
  hold 264 of them, and GA WARN ID sequences top out ≈100–108 per year, so the
  state issues only ~100 notices/year. layoffdata's 3,181 notices / 375K workers
  (≈10× ours on both axes) is their own row expansion, methodology unknown.
  Minor residue: ID-sequence gaps (e.g. GA2024 001–027 absent from the view) show
  TCSG prunes some entries — the pre-2023 FOIA draft's "complete export" clause
  would recover those too. Verified 2026-07-02.

## Tier 3 — public-records request required

Email/portal drafts live in [docs/foia/](foia/) — one file per state, tracker in
[foia/README.md](foia/README.md). Recipients verified on agency sites 2026-06-12
except where flagged; rows added 2026-07-02 come from the aggregator cross-check
in [coverage-vs-aggregators.md](coverage-vs-aggregators.md).

| State | Years sought | Recipient | Method | Statute |
|-------|--------------|-----------|--------|---------|
| AZ | pre-2010 (probe done 2026-07-09: JobLink search reaches 2010, ingested via backfill after PR #241; 2009 and older are empty at source) | GovQA `desaz.govqa.us` / PublicRecordsRequest@azdes.gov | portal or email — **must declare non-commercial purpose** | A.R.S. §39-121 et seq. |
| CT | ~~pre-2019~~ **2013 + Jan–Jul/Oct–Dec 2009 only** (1998–2018 otherwise in Wayback — sweep 2026-07-10) | CT DOL Records Center | **GovQA portal** (`dolct.govqa.us`) | CT FOIA |
| DE | pre-2007 (probe done 2026-07-09: JobLink search reaches 2007, ingested via backfill after PR #241; 2006 and older are empty at source) | dol.foia@delaware.gov (FOIA Coordinator) | email (state web form alt.) — "any citizen" caveat | 29 Del. C. ch. 100 |
| FL | ~~pre-2020~~ **2012 only** (1998–2019 backfilled 2026-07-10; 2012 is a real hole — the site itself had dropped the year, its sole capture is header-only) | PRRequest@commerce.fl.gov | email (JustFOIA portal alt.) | Ch. 119, F.S. |
| GA | ~~pre-2023~~ **2013–2021 + 2022 ids GA202200001–070** (GDOL search app archived only empty forms; the 2022 entry-page route — run 2026-07-10 — recovered only ids 071–103, 31 field fills: the single-entry route renders an empty shell outside the server-side-filtered view) | GDOL via `dol.georgia.gov/email-us` | **web form** (no records email published) | O.C.G.A. §50-18-70 |
| HI | pre-2019 (confirmed never published online — sweep 2026-07-10) | dlir.director@hawaii.gov | email | UIPA (HRS ch. 92F) |
| IA | ~~pre-2021~~ **pre-2005** (2005–2021 via Wayback log snapshots — sweep 2026-07-10; pre-2005 never published) | RecordsRequest@IWD.Iowa.gov | email | Iowa Code ch. 22 |
| LA | ~~pre-2025~~ **pre-2007 + Sep–Dec 2024** (2007–2024 backfilled 2026-07-10; the 2024 tail was published nowhere — latest capture 2024-08-12; pre-2007 never published) | HiRE@lwc.la.gov | email (online system alt.) | La. R.S. 44:1 et seq. |
| MA | ~~pre-FY2022~~ **Sep 2020–Mar 2021 + pre-FY2020** (FY2020 + Jul–Aug 2020 recovered from Wayback — sweep 2026-07-10) | eolwdpress@mass.gov | email — **agency invites this** | M.G.L. c. 66 |
| MD | ~~pre-2010~~ **dropped 2026-07-10** — `warn2000`–`warn2009` pages archived in Wayback (request = backstop only) | dllr.pio@maryland.gov — "Records Request" in subject | email | MPIA (GP §4-101 et seq.) |
| MI | ~~pre-Nov 2024~~ **dropped 2026-07-09** — 2000–2024 recoverable from milmi.org via Wayback (see Tier 2 MI note); request = post-backfill completeness backstop only | leo-warn@michigan.gov | email | MI FOIA (Act 442 of 1976) |
| MO | ~~pre-2019~~ **pre-Jul-2012 + mid-PY gaps Sep 2015–Jun 2016, May–Jun 2017, Jan–Jun 2018** (Jul 2012–2019 backfilled 2026-07-10, +235; the mid-PY windows have no Wayback coverage) | meghan.maskeryluecke@dhewd.mo.gov (General Counsel), cc info@dhewd.mo.gov | email | Sunshine Law (§610 RSMo) |
| MS | ~~pre-PY2020~~ **Jul 2007–Jun 2010 (+ pre-2004)** (PY2010–19 + 2004–06 + PY2023-Q4 in Wayback — sweep 2026-07-10) | communications@mdes.ms.gov | email | Miss. Code §25-61 |
| ND | pre-2015 (confirmed: the published record starts 2015 — sweep 2026-07-10) | ⚠ no records email published — call (701) 328-2825 for address | phone→email | NDCC ch. 44-04 |
| NE | ~~pre-2023~~ **pre-2010** (2010–2020 still served live by the frozen `WARNReportData?year=` endpoint; 2021–22 in Wayback — sweep 2026-07-10) | NDOL.RapidResponse@nebraska.gov | email | Neb. Rev. Stat. §84-712 |
| NH | all years — split custody, send in parallel (see nh.md) | masslayoff@nhes.nh.gov + NH DOL Commissioner + AG | email + mail — ⚠ NHES addresses verified via archive captures only (nh.gov blocks fetchers) | RSA 91-A |
| NM | pre-2016 (confirmed never published — sweep 2026-07-10) | tammy.gallegos-burke@dws.nm.gov (named on agency site for older records) | email | IPRA (NMSA ch. 14, art. 2) |
| NV | pre-2017 (detr.nv.gov publishes 2017+ — 2017–2024 is a scraper backfill; narrowed 2026-07-02) | detrmedia@detr.nv.gov, cc rapidresponse@detr.nv.gov | email + **required request form** | NRS 239 |
| OK | all years (portal is auth-walled) | forms.office.com/g/kQHiUiCvas + CustodianOfRecords@oesc.ok.gov | form + email — ⚠ OESC posts a $25/hr search fee; letter contests it as non-commercial | 51 O.S. §24A.1 et seq. |
| OR | ~~pre-2020~~ **the ~389 date-less 1990s rows (+ pre-1989)** (dated list history 1989–2026 backfilled 2026-07-10; the 1990s rows' dates live only in scanned per-notice upload PDFs) | HECC Office of Workforce Investments | email | ORS 192 |
| SC | ~~pre-2026~~ **pre-2009 + Dec 16–31 2022, Dec 2023, Dec tails of 2016/17/19** (2009–2025 backfilled 2026-07-10; the Dec residuals are edition-cutoff holes; sces.org era has nothing) | FOIA@dew.sc.gov | email | S.C. Code §30-4-10 et seq. |
| TN | pre-2018 only (re-probed 2026-07-09: the live reports page holds 2025+; 2024 sits in Wayback captures of the same page as the live-schema table, and 2018–2023 exist as **534 archived per-notice WARN letter PDFs** — pruned from live tn.gov — so 2018–2024 is a scraper backfill, not a request) | TDLWD.PublicRecords@tn.gov, cc Sabra.Bledsoe@tn.gov | email — ⚠ **TPRA is TN-citizens-only**; framed as voluntary release, TN co-requester as fallback | T.C.A. §10-7-503 |
| TX | ~~pre-2020~~ **pre-2004** (2004–2018 Wayback XLS/XLSX + Socrata 2019 — sweep 2026-07-10) | warn.list@twc.texas.gov (published for older notices); formal: twc.govqa.us / open.records@twc.texas.gov | email, PIA portal fallback | Gov't Code ch. 552 |
| UT | ~~pre-2026~~ **pre-2009** (live page is already cumulative 2009+ — scraper fix; pre-2009 never published — sweep 2026-07-10) | infodisclosure@utah.gov (GRAMA office, *not* the rapid-response box) | email (openrecords.utah.gov alt.) | GRAMA |
| WV | ~~pre-2021~~ **pre-2011** (2011–2021 cumulative PDF in Wayback — sweep 2026-07-10; pre-2011 never captured) | ⚠ wfwvbsr@wv.gov (general box; no FOIA email published — ask to route) | email | W. Va. Code §29B-1 |

## Blocked — no request drafted

AR (WARN data confidential by state law — a request would be denied), WY (no
public data). Re-verify periodically per STATE_AUDIT.md. NH/OK/TN moved to Tier 3
on 2026-07-02: layoffdata.com shows their records exist (NH since 2009, OK since
1999, TN since 2012), so requests are not futile — see coverage-vs-aggregators.md.
(TN's live source is scraped again as of 2026-06-26; historical depth = whatever
the live archive table lists.)
