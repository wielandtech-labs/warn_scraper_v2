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

- **2026-07-07 — CA 2009–2013 probe + detailed-PDF parser** (spike + parser;
  prod run pending). The interior hole (dense only from 2014, one stray 2008
  row) is **recoverable from the Wayback Machine — no CPRA request needed.**
  Probe findings:
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
  - **Volume**: ~6.8K aggregator delta since 2009-01. A single filing can list
    multiple layoff waves (distinct effective dates + counts) under one
    received-date/address; those collapse to one `notice_id` on ingest — the
    same accepted dedup granularity as PA, so expect `seen`>`inserted` deltas.
  - **Remaining**: the gated prod backfill Job (dry-run → real → re-audit).
    Pre-2008 (`cn00`–`cn08` also in Wayback) is a possible later spike.
- **2026-07-07 — IL PDF era 1999–2019 parser landed** (`parse_il_pdf`, PR #211):
  the archive's monthly PDFs are a two-column labeled *form*, not a table —
  `extract_text()` flattens the columns and glues a left value onto the next
  right label, so the parser splits `extract_words()` by x (labels at x≈20/380,
  split at 376), collects `LABEL: value` pairs per notice block, and joins
  wrapped values. Validated across four format eras (1999 SIC + `PRIMARY EVENT
  COUNTY` section headers; 2005 `CITY, STATE` no-ZIP; 2010 NAICS + UNION; 2019
  `Monthly WARN Report` naming). SIC (1999–2005) → `extra["sic_code"]`, not
  `naics_code`. Discovery bounded to years ≤ 2019 (2020+ is the ingested XLSX
  era) and skips the WARN Act statute PDF. Wired into the IL backfill spec next
  to the xlsx discovery (`--state IL` now covers the whole history; xlsx
  re-ingest is idempotent). **Gated backfill Job pending** — ~250 monthly PDFs,
  est. +2,500–4,000 net-new rows (DB floor is 2020, so 1999–2019 is all new);
  run `--dry-run` → real → `mark-superseded --state IL --dry-run` → re-audit.
- **2026-07-07 — NV 2021 OCR route added** (parser PR #210): the last NV
  archive gap, `Content/Media/WARN_2021.pdf`, is a single-page **scanned image
  with no text layer** (one 842×387 px embedded image, 20-row lattice table,
  7 columns, no Notification column — the 2022 shape). `parse_nv_archive` now
  detects the missing text layer and falls back to the tesseract OCR path via
  the new `pdf_extract.ocr_word_boxes` (returns pdfplumber-shaped word boxes
  with x0/top normalized from pixels to points), then reuses the existing
  word-position parser with 2021 x-bounds `(129,186,239,291,454,526,10_000)`.
  OCR is Docker-only (no tesseract in CI/local), so a synthetic-word unit test
  guards the column layout and the real-OCR fixture test is skip-guarded.
  **Remaining: the gated prod run** (`backfill-historical --state NV
  --year-start 2021 --year-end 2021`, dry-run first — brand-new year, no
  dedup), verify **+~20 rows** against the known ground truth, then re-audit.
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
| CA | 2014 (dense; 1 stray 2008 row) | Live EDD page publishes **FY2014–2025 only** (verified 2026-07-07). Pre-2014 calendar-year reports survive in **Wayback** at `edd.ca.gov/Jobs_and_Training/warn/eddwarncn*.pdf`. We ingest the **detailed** A–Z slices `eddwarncn{da,dbd,del,dmr,ds,dtz}{YY}.pdf` (6/year, carry notice-received date + street address; the simple `cn{YY}` consolidations lack both → dedup collisions, rejected). Rolling year-to-date snapshots → take the **latest 200 capture per file**. Records are two-column (LWIA name wraps at x0≥425) with `(cid:NN)` glyphs in 2009–2010 | **2006** (Wayback; `cn00`–`cn08` reach 2000) | **parser done 2026-07-07** (`parse_ca_detail_pdf` + `_discover_ca_historical_urls`, Wayback CDX); **gated prod Job pending**. ~6.8K aggregator delta; multi-wave filings collapse per `notice_id` (expect seen>inserted) |
| CO | ~~2021~~ **2015 ✅** | one Google Sheet per year linked from `cdle.colorado.gov/employers/layoff-separations/layoff-warn-list` (co.py registry + link discovery; regular scraper reads only the two newest sheets) | **2015** | **done 2026-07-02** (+768, via the #110 full sweep); re-runs via year loop (`--state CO`) |
| KS | ~~2026~~ **1999 ✅** | `kansasworks.com/search/warn_lookups?q[notice_on_gteq]=YYYY-01-01` (JobLink date-range search) | **1999** | **done 2026-06-12** (+542) |
| ME | ~~2026~~ **2012 ✅** | `joblink.maine.gov/search/warn_lookups` (JobLink) | **2012** | **done 2026-06-12** (+76) |
| VT | ~~2026~~ **2003 ✅** | `vermontjoblink.com/search/warn_lookups` (JobLink) | **2003** | **done 2026-06-12** (+91) |
| FL | ~~2026~~ **2020 ✅** | `reactwarn.floridajobs.org/WarnList/Records?year=Y` — paginated (e.g. 2020 = 1,337 records); page links followed | **2020** (older years return 0 rows) | **done 2026-06-12** (+2,167); pre-2020 → FOIA |
| TX | ~~2026~~ **2020 ✅** | `warn-act-listings-{year}-twc.xlsx` — **only 2020+ still resolve** (pre-2020 files removed from twc.texas.gov; the old `/files/news/` era is dead; Socrata `data.texas.gov/dataset/8w53-c4f6` starts 2019-01, 2,363 rows — verified 2026-06-12) | **2020** | **done 2026-06-12** (+2,166); pre-2020 → records request (warn.list@twc.texas.gov) |
| NC | 2026 | archive hub `commerce.nc.gov/...warn-summary-report-archives` → per-year **PDF** documents with irregular slugs (`warn-report-2019/open` etc.); three layout eras — summary-count text 2014–~2017, SSRS grid ~2018–2021, live-schema grid 2022+ | **2014** | **parser done 2026-07-07** (hub discovery + three-era `parse_nc_pdf`, dispatch on detected content); gated prod run pending (floor 2026→2014) |
| NJ | ~~2026~~ **2004 ✅** | cumulative `nj.gov/labor/assets/PDFs/WARN/WARN_Notice_Archive.xlsx` — one sheet per year, same 5 columns as the live PDF (23 sheets 2004–2026, 2,349 rows) | **2004** | **done 2026-07-07** (+2,203, near_miss=0; see Progress) |
| NM | ~~2025~~ **2016 ✅** | per-year PDFs on `dws.nm.gov/Rapid-Response` (filenames vary 2016–2018 → discovered from the hub's anchors) | **2016** | **done 2026-06-12** (+109); pre-2016 → request |
| HI | ~~2026~~ **2019 ✅** | `labor.hawaii.gov/wdc/{year}-warn-notices/`; hub `real-time-warn-updates` lists 2019–2026 | **2019** | **done 2026-06-12** (+401); pre-2019 → UIPA request |
| KY | ~~2025~~ **2017 ✅** (the earlier "2021 ✅" claim was wrong) | per-year CSVs exist only for **2025+**; the 2021–2024 folders hold `.xls`/`.xlsx` instead, and any recent `.xlsx` workbook carries **one sheet per year back to 2017** (verified 2026-07-02; see Progress) | **2017** | **done 2026-07-02** (+343, workbook route); pre-2017 → request |
| MO | 2019 | `jobs.mo.gov/warn/{year}` — the regular scraper **already crawls 2019–present every run**; DB is complete | 2019 | **no backfill needed**; pre-2019 → request (drafted) |
| OH | ~~2026~~ **1996 ✅** (gap years 2007–09, 2011, 2013, 2023–24 pending re-run) | Four eras (probed 2026-06-12, re-probed 2026-07-06), all via httpx — **no Playwright**: **1996–2006** per-year PDFs (`WARN_{y}.pdf` / `Warn_{y}.pdf`, Wayback replay); **2007–2019** `.stm` files that actually serve Excel-exported PDFs (Wayback replay pinned per year via CDX — the nearest-to-2020 anchor hit dead 302 captures; slug variants as fallback); **2020–2022** `archive.stm?year=Y` HTML (live-table layout, Wayback); **2021–2024** per-year pages on the June-2026 site linking a `dam.assets.ohio.gov` CSV (live-CSV shape; old JSON portal retired — Wayback captures kept as fallback). **2025 unaccounted for** (no live page, nothing in CDX) | **1996** | first run **done 2026-07-06** (+2,319, 22/31 years, w_homelab #595); gap-year discovery fixed same day → **re-run 2007–2024**; 2025 → investigate/FOIA |
| PA | ~~2024~~ **2001 ✅** | Live AEM page holds accordion sections **2023–2026 only** (probed 2026-06-12). Pre-2023: **archived per-month pages, two hosts, same content template** (probed 2026-07-06) — `portal.state.pa.us/portal/server.pt/community/{yr}/10542/{month}_{year}_warn_notices/{id}` (2001–2015) and SharePoint `dli.pa.gov/.../warn/notices/Pages/{Month}-{Year}.aspx` (2011–2022); CDX-discovered, SharePoint capture preferred on overlap. **262/264 months archived** (missing: 2021-10, 2022-04 — never captured). Month pages carry no per-notice filing date → `notice_date` = first-of-month proxy. 2005 live sample: 256 rows, full city+count | **2001** | **done 2026-07-07** (+3,158 rows 2001–2022; 262/262 archived months verified per-month in prod after two throttle top-ups; 2017–2022 purged + re-ingested post-#183). `mark-superseded` not needed — the one flagged row was junk the purge removed |
| IL | ~~2025~~ **2020 ✅** | `illinoisworknet.com/LayoffRecovery/` archive — monthly XLSX 2020+, monthly **PDFs 1999–2019** (a two-column labeled *form*, not a table — split words by x, not `extract_text`) | **1999** (PDF era) | xlsx era **done 2026-06-12** (+861 on rerun); **PDF-era parser done 2026-07-07** (`parse_il_pdf`, wired into the IL backfill spec alongside the xlsx discovery). Gated backfill Job pending |
| NY | 2025 | `dol.ny.gov/warn-dashboard` Tableau CSV is **current-year only and ignores year-filter params** (verified 2026-06-12). **Probed 2026-07-06, three eras**: (1) old ASP portal `labor.ny.gov/app/warn/details.asp?id=N` — **4,294 unique ids archived in Wayback (ids 3–9536, ~2001–2020), each a full record**: street address, county/WIB/region, business type, **Number Affected**, layoff + closing dates, reason. Enumerate straight from CDX (`details.asp*`, status 200); per-year `default.asp?warnYr=Y` listing snapshots are too sparse to drive discovery. (2) Year-summary PDFs `{Y}-nys-warn-notices.pdf` 2016–2020 — index-style (posted/notice dates, employer, region; **no counts/addresses**; 2020 = 160 pp, clean text layer); live URLs 403, Wayback replay works. (3) dol.ny.gov 2021+: per-notice PDFs/HTML + `/2023-warn-notices`, `/2024-warn-notices` hubs (JS/paginated). | **2001** (Wayback details) | **Wayback CDX detail-page harvest recovers the bulk (~4.3k rows incl. counts + addresses) with no FOIA wait**; year PDFs + modern pages fill listing-only rows; keep the FOIA draft as the completeness backstop (un-archived notices, rescissions). Route decided 2026-07-07: **parser implemented** (`_discover_ny_detail_urls` + `parse_ny_detail`); gated Job round pending. |
| MD | ~~2026~~ **2010 ✅** | archived per-year pages `warn{year}.shtml` (verified 2010–2024; old pages use `WIA Code`/`Type Code` headers) | **2010** | **done 2026-06-12** (+1,257) |
| WI | ~~2020~~ **2016 ✅** | the Google Sheet is **cumulative from 2020-01 only** (no per-year tabs); 2016–2019 are static pages `/dislocatedworker/warn/{year}/default.htm` | **2016** | **done 2026-06-12** (+320, `--year-end 2019`) |
| MN | 2023 | DEED PDFs via Wayback CDX replay (mn.gov prunes old assets): monthlies 2015–2016 + 2022+, annual summaries 2018–2021, cumulative yearly reports 2022–24; the Dec-2016 cumulative reaches month sections back through **2014** | **2014** (via the 2016 cumulative) | **multi-era parser done 2026-07-07** (`_parse_archive_words`, word-position columns from header labels; WARN=YES only; verified against every file's own "(N records)" section counts). Prod run pending — ⚠ live-scraper rows 2023+ were text-fallback parses with glued employer+city+industry; plan a PA-style purge + re-ingest of that era in the Job dry-run review |
| MS | ~~2025~~ **PY2020 ✅** | MDES quarterly PDFs — `_discover_pdf_urls()` already returns all 23 (PY2020Q1+); old quarterlies merge "Company Name, City" (parser splits the trailing "City (County)" line) | **PY2020** (Jul 2020) | **done 2026-06-12** (+112; 4 quarterlies with a third layout variation skipped — known gap); older → request |
| MA | 2025 | mass.gov WARN page publishes **FY22–FY25 XLSX reports** | FY2022 | ingest FY xlsx; pre-FY22 → email (invited) |
| WA | ~~2026~~ **2004 ✅** | `fortress.wa.gov/esd/file/warn/Public/SearchWARN.aspx` — ASP.NET `__VIEWSTATE` GridView; the scraper now replays the `Page$N` postback for every page (99 pages, ~15 rows each) | **2004** | **done 2026-07-07** (pagination fix; live fetch = 1,480 rows, floor 2004-01; deploys via the daily scrape, no one-off Job) |
| OR | 2020 | HECC site states it retains only **six years** of WARN records; `data.oregon.gov` Socrata dataset `ijbz-jpx8` exists (content unverified) | ~mid-2020 | check Socrata dataset; pre-2020 → inquiry |
| NV | ~~2025~~ **2017 ✅** | per-year PDFs under `detr.nv.gov/Content/Media/` in three layout eras (see `nv._ARCHIVE_SOURCES`); 2023 pruned live → Wayback; **2021 is a scanned image → OCR route (done 2026-07-07)**; 2025 snapshot ends Jun 3 | **2017** | **done 2026-07-02** (+584); 2021 OCR parser done 2026-07-07 (prod run pending); Jun–Dec 2025 + pre-2017 → request |
| LA | ~~2026~~ **2025 ✅** | `WarnNotices{year}.pdf` — only 2025+ still resolve; the 2025 file's layout (no Address column) now parses | **2025** | **done 2026-07-02** (+23); pre-2025 → request (drafted) |

## Tier 2 — investigated, resolved

- **AK** — interior year gaps (2009, 2011, 2014) are **real**: the cumulative source
  page (`jobs.alaska.gov/rr/WARN_notices.htm`, 2006–present) lists zero notices for
  those years. No backfill possible or needed; optional confirmation in the OR/AK
  inquiry drafts.
- **MI** — michigan.gov **removed pre-2025 notices** from the public search; the LEO
  FAQ directs historical requests to FOIA (`leo-warn@michigan.gov`). The Sitecore
  API the scraper uses 403s externally and its index only carries recent items →
  records request (draft in foia/mi.md).
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
| AZ | pre-2016 — ⚠ probe AZ Job Connection (JobLink) date-range search first | GovQA `desaz.govqa.us` / PublicRecordsRequest@azdes.gov | portal or email — **must declare non-commercial purpose** | A.R.S. §39-121 et seq. |
| CT | pre-2019 | CT DOL Records Center | **GovQA portal** (`dolct.govqa.us`) | CT FOIA |
| DE | pre-2016 — ⚠ probe Delaware JobLink date-range search first | dol.foia@delaware.gov (FOIA Coordinator) | email (state web form alt.) — "any citizen" caveat | 29 Del. C. ch. 100 |
| FL | pre-2020 | PRRequest@commerce.fl.gov | email (JustFOIA portal alt.) | Ch. 119, F.S. |
| GA | pre-2023 | GDOL via `dol.georgia.gov/email-us` | **web form** (no records email published) | O.C.G.A. §50-18-70 |
| HI | pre-2019 | dlir.director@hawaii.gov | email | UIPA (HRS ch. 92F) |
| IA | pre-2021 | RecordsRequest@IWD.Iowa.gov | email | Iowa Code ch. 22 |
| LA | pre-2025 | HiRE@lwc.la.gov | email (online system alt.) | La. R.S. 44:1 et seq. |
| MA | pre-FY2022 | eolwdpress@mass.gov | email — **agency invites this** | M.G.L. c. 66 |
| MD | pre-2010 (published log starts 2010) | dllr.pio@maryland.gov — "Records Request" in subject | email | MPIA (GP §4-101 et seq.) |
| MI | pre-Nov 2024 (site pruned all pre-2025; widened 2026-07-02) | leo-warn@michigan.gov | email | MI FOIA (Act 442 of 1976) |
| MO | pre-2019 | meghan.maskeryluecke@dhewd.mo.gov (General Counsel), cc info@dhewd.mo.gov | email | Sunshine Law (§610 RSMo) |
| MS | pre-PY2020 | communications@mdes.ms.gov | email | Miss. Code §25-61 |
| ND | pre-2015 | ⚠ no records email published — call (701) 328-2825 for address | phone→email | NDCC ch. 44-04 |
| NE | pre-2023 | NDOL.RapidResponse@nebraska.gov | email | Neb. Rev. Stat. §84-712 |
| NH | all years — split custody, send in parallel (see nh.md) | masslayoff@nhes.nh.gov + NH DOL Commissioner + AG | email + mail — ⚠ NHES addresses verified via archive captures only (nh.gov blocks fetchers) | RSA 91-A |
| NM | pre-2016 | tammy.gallegos-burke@dws.nm.gov (named on agency site for older records) | email | IPRA (NMSA ch. 14, art. 2) |
| NV | pre-2017 (detr.nv.gov publishes 2017+ — 2017–2024 is a scraper backfill; narrowed 2026-07-02) | detrmedia@detr.nv.gov, cc rapidresponse@detr.nv.gov | email + **required request form** | NRS 239 |
| OK | all years (portal is auth-walled) | forms.office.com/g/kQHiUiCvas + CustodianOfRecords@oesc.ok.gov | form + email — ⚠ OESC posts a $25/hr search fee; letter contests it as non-commercial | 51 O.S. §24A.1 et seq. |
| OR | pre-2020 (existence inquiry) | HECC Office of Workforce Investments | email | ORS 192 |
| SC | pre-2026 | FOIA@dew.sc.gov | email | S.C. Code §30-4-10 et seq. |
| TN | pre-2025 (need is pre-2021; 2021–2024 also on the live reports page) | TDLWD.PublicRecords@tn.gov, cc Sabra.Bledsoe@tn.gov | email — ⚠ **TPRA is TN-citizens-only**; framed as voluntary release, TN co-requester as fallback | T.C.A. §10-7-503 |
| TX | pre-2020 | warn.list@twc.texas.gov (published for older notices); formal: twc.govqa.us / open.records@twc.texas.gov | email, PIA portal fallback | Gov't Code ch. 552 |
| UT | pre-2026 | infodisclosure@utah.gov (GRAMA office, *not* the rapid-response box) | email (openrecords.utah.gov alt.) | GRAMA |
| WV | pre-2021 | ⚠ wfwvbsr@wv.gov (general box; no FOIA email published — ask to route) | email | W. Va. Code §29B-1 |

## Blocked — no request drafted

AR (WARN data confidential by state law — a request would be denied), WY (no
public data). Re-verify periodically per STATE_AUDIT.md. NH/OK/TN moved to Tier 3
on 2026-07-02: layoffdata.com shows their records exist (NH since 2009, OK since
1999, TN since 2012), so requests are not futile — see coverage-vs-aggregators.md.
(TN's live source is scraped again as of 2026-06-26; historical depth = whatever
the live archive table lists.)
