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
    image (needs OCR), **Jun–Dec 2025** is published nowhere (the master
    rotated to 2026 before the scraper first ran) → keep in the NV request.
  - All three still need the one-off prod Jobs per the runbook below.
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
- Remaining Wave 2: OH 1996+ (code in PR #55), PA 2001+ (Wayback-era parse,
  strict dedup), MN multi-era parser, NC PDFs 2014+, NJ cumulative xlsx,
  MA FY xlsx; WA pagination fix.
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
| KS | ~~2026~~ **1999 ✅** | `kansasworks.com/search/warn_lookups?q[notice_on_gteq]=YYYY-01-01` (JobLink date-range search) | **1999** | **done 2026-06-12** (+542) |
| ME | ~~2026~~ **2012 ✅** | `joblink.maine.gov/search/warn_lookups` (JobLink) | **2012** | **done 2026-06-12** (+76) |
| VT | ~~2026~~ **2003 ✅** | `vermontjoblink.com/search/warn_lookups` (JobLink) | **2003** | **done 2026-06-12** (+91) |
| FL | ~~2026~~ **2020 ✅** | `reactwarn.floridajobs.org/WarnList/Records?year=Y` — paginated (e.g. 2020 = 1,337 records); page links followed | **2020** (older years return 0 rows) | **done 2026-06-12** (+2,167); pre-2020 → FOIA |
| TX | ~~2026~~ **2020 ✅** | `warn-act-listings-{year}-twc.xlsx` — **only 2020+ still resolve** (pre-2020 files removed from twc.texas.gov; the old `/files/news/` era is dead; Socrata `data.texas.gov/dataset/8w53-c4f6` starts 2019-01, 2,363 rows — verified 2026-06-12) | **2020** | **done 2026-06-12** (+2,166); pre-2020 → records request (warn.list@twc.texas.gov) |
| NC | 2026 | archive hub `commerce.nc.gov/...warn-summary-report-archives` → per-year **PDF** documents with irregular slugs (`warn-report-2019/open` etc.) | **2014** | needs a PDF parser → Wave 2 (hub discovery + `parse_nc_pdf`) |
| NJ | 2026 | cumulative `nj.gov/labor/assets/PDFs/WARN/WARN_Notice_Archive.xlsx` (year range unknown — parse first); per-year PDF only 2023 | TBD (parse xlsx) | ingest cumulative xlsx |
| NM | ~~2025~~ **2016 ✅** | per-year PDFs on `dws.nm.gov/Rapid-Response` (filenames vary 2016–2018 → discovered from the hub's anchors) | **2016** | **done 2026-06-12** (+109); pre-2016 → request |
| HI | ~~2026~~ **2019 ✅** | `labor.hawaii.gov/wdc/{year}-warn-notices/`; hub `real-time-warn-updates` lists 2019–2026 | **2019** | **done 2026-06-12** (+401); pre-2019 → UIPA request |
| KY | 2025 (~~2021 claim was wrong~~) | per-year CSVs exist only for **2025+**; the 2021–2024 folders hold `.xls`/`.xlsx` instead, and any recent `.xlsx` workbook carries **one sheet per year back to 2017** (verified 2026-07-02; see Progress) | **2017** | `backfill-historical --state KY` (workbook route) — prod run pending; pre-2017 → request |
| MO | 2019 | `jobs.mo.gov/warn/{year}` — the regular scraper **already crawls 2019–present every run**; DB is complete | 2019 | **no backfill needed**; pre-2019 → request (drafted) |
| OH | 2026 | Four eras (probed 2026-06-12), all via httpx — **no Playwright**: **1996–2006** per-year PDFs (`WARN_{y}.pdf` / `Warn_{y}.pdf`, Wayback replay); **2007–2019** `.stm` files that actually serve Excel-exported PDFs (Wayback, slug variants tried); **2020–2022** `archive.stm?year=Y` HTML (live-table layout, Wayback); **2021–2024** live portal pages with the table embedded as JSON in `div#js-placeholder-json-data` (incl. per-notice PDF URLs). **2025 unaccounted for** (no live page, nothing in CDX) | **1996** | year loop + era-dispatch parser (implemented, Wave 2B); 2025 → investigate/FOIA |
| PA | 2024 | Live AEM page holds accordion sections **2023–2026 only** (probed 2026-06-12). Pre-2023 → Wayback snapshots of the older dli.pa.gov WARN pages | **2001** | Wave 2B: Wayback-era parse; strict dedup (286 superseded rows already; `--year-end 2022` on the real run) |
| IL | ~~2025~~ **2020 ✅** | `illinoisworknet.com/LayoffRecovery/` archive — monthly XLSX 2020+, monthly **PDFs 1999–2019** | **1999** (PDF era) | xlsx era **done 2026-06-12** (+861 on rerun); PDF era: `parse_il_pdf` (deferred) |
| NY | 2025 | `dol.ny.gov/warn-dashboard` Tableau CSV is **current-year only and ignores year-filter params** (verified 2026-06-12); history = per-year PDF listings | ~2010s | per-year PDF parse (Wave 2C decision) or FOIA |
| MD | ~~2026~~ **2010 ✅** | archived per-year pages `warn{year}.shtml` (verified 2010–2024; old pages use `WIA Code`/`Type Code` headers) | **2010** | **done 2026-06-12** (+1,257) |
| WI | ~~2020~~ **2016 ✅** | the Google Sheet is **cumulative from 2020-01 only** (no per-year tabs); 2016–2019 are static pages `/dislocatedworker/warn/{year}/default.htm` | **2016** | **done 2026-06-12** (+320, `--year-end 2019`) |
| MN | 2023 | DEED PDFs via Wayback CDX replay (mn.gov prunes old assets): monthlies 2015–2016 + 2022+, annual summaries 2018–2021 | **2018** (annuals), 2015 (monthlies) | discovery implemented; **run blocked on a multi-era parser** (2015/16 + annual + 2022–24 wide layouts) → Wave 2B |
| MS | ~~2025~~ **PY2020 ✅** | MDES quarterly PDFs — `_discover_pdf_urls()` already returns all 23 (PY2020Q1+); old quarterlies merge "Company Name, City" (parser splits the trailing "City (County)" line) | **PY2020** (Jul 2020) | **done 2026-06-12** (+112; 4 quarterlies with a third layout variation skipped — known gap); older → request |
| MA | 2025 | mass.gov WARN page publishes **FY22–FY25 XLSX reports** | FY2022 | ingest FY xlsx; pre-FY22 → email (invited) |
| WA | 2026 | `fortress.wa.gov/esd/file/warn/Public/SearchWARN.aspx` — ASP.NET `__VIEWSTATE` pagination the scraper doesn't follow (10+ pages; depth unknown) | TBD | implement postback paging, then reassess |
| OR | 2020 | HECC site states it retains only **six years** of WARN records; `data.oregon.gov` Socrata dataset `ijbz-jpx8` exists (content unverified) | ~mid-2020 | check Socrata dataset; pre-2020 → inquiry |
| NV | 2025 | per-year PDFs under `detr.nv.gov/Content/Media/` in three layout eras (see `nv._ARCHIVE_SOURCES`); 2023 pruned live → Wayback; **2021 is a scanned image (OCR needed)**; 2025 snapshot ends Jun 3 | **2017** | `backfill-historical --state NV` — prod run pending; 2021 + Jun–Dec 2025 + pre-2017 → request |
| LA | 2026 | `WarnNotices{year}.pdf` — only 2025+ still resolve; the 2025 file's layout (no Address column) now parses | **2025** | `backfill-historical --state LA` — prod run pending; pre-2025 → request (drafted) |

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
