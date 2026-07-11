# Backfill milestones — per-state status toward global 2020 / 2010 / 2000

Milestone-oriented rollup of historical coverage: which states block **every
jurisdiction back to 2020-01**, then **2010-01**, then **2000-01 (stretch)** —
and the route for each. Runbooks and prior probe history live in
[historical-sources.md](historical-sources.md); this doc is the scoreboard plus
the verdicts of the **2026-07-10 milestone probe sweep** (Wayback CDX +
live-site probes of every state without a known route; every positive verdict
below was verified by fetching an actual capture and reading WARN rows in it).

**Wave complete 2026-07-10:** the sweep's entire 23-item build queue was built
(PRs #258–#281), merged, and **run in prod** (one-off Job train w_homelab
#709–#715): **+17,714 notices** (bundled batch +3,295 + Wayback batch +14,419),
all verified via the public API. UT ships separately via the daily scrape
(parse-all-sections fix #260, first full scrape pending). Run details + post-run
cleanups in historical-sources.md Progress.

Ranges are the **verified post-run prod floors as of 2026-07-10** — the 2026-07-07
STATE_AUDIT.md table is stale for CA (2006, 20,077 rows), NY (2006, 8,708),
MN (2012, 482), WA (2004, ~1,480), MI (2000, 2,168); those use the post-run
numbers recorded in historical-sources.md Progress.

**Route legend:** ✅ done · 🔨 build item (route verified, code/Job pending) ·
🔍 sweep verdict 2026-07-10 (recoverable, needs a parser build) ·
✉ FOIA/records request only · ⛔ source floor (state confirms nothing older
exists) · 🚫 blocked by state law.

## Milestone scoreboard

| Milestone | After the 2026-07-10 wave, what still blocks it |
|---|---|
| **Global 2020** | Only ✉ items: **GA 2013–2022-partial** (✉ — the old GDOL search app was never archived, and the 2022 entry-page route recovers only ids 071–103: ids 001–070 render an empty shell) and **MA Sep 2020–Mar 2021** (✉ — weekly files not crawled; agency invites email). Small never-published tails: LA Sep–Dec 2024, SC Dec 16–31 2022 + Dec 2023. Pre-wave 🔨 queue: TN 2018–2024; UT lands with the next daily scrape (#260). Everything else ✅: SC→2009, LA→2007, IA→2005, WV→2011, NE→2010, MI→2000 (all done 2026-07-10). |
| **Global 2010** | Adds ✉-only: **HI, NV, NM, CO, ND, MT** (probes confirm those states never published pre-floor lists) + partial holes: MO pre-Jul-2012, MS Jul-2007–Jun-2010, NC pre-2013 (Q4-2012 unrecoverable in CDX), CT 2013 + 2009-except-Aug/Sep, FL 2012, WV pre-2011, VA Jul-2006–Dec-2009. ⛔ source floors: ME (2012), MN (2012). AZ reaches 2010 once the JobLink Job runs. OR no longer blocks — it reaches **1989** ✅. |
| **Global 2000** | The wave got the big sweep wins to ~2000 or beyond ✅: FL/CT/KY→1998, WI→1996, PA→1998-07, MD→2000, IN→2000-11, SD→1997, OR→**1989**, MI→2000, plus existing OH/AL/IL/KS. Still 🔨: CA→2000. Rest are ✉ (TX pre-2004, NY pre-2006, NJ pre-2004, DC, RI, OK pre-2001, VA PY2000–01…) or ⛔ (VT, WA, AK, DE, AZ). |

The sweep estimated **~15–20k recoverable rows, no FOIA needed** — the run
delivered **+17,714** (mid-range), on a prod base of ~38k.

## Per-state table

Reachable floor = floor after running every verified route (no FOIA).

| State | Rows | Range | →2020 | →2010 | →2000 | Reachable floor | Route for missing years |
|---|---|---|---|---|---|---|---|
| AK | 64 | 2006–2025 | ✅ | ✅ | ⛔ | 2006 | Source (cumulative page) starts 2006; gaps 2009/11/14 verified real |
| AL | 1,035 | 1998–2026 | ✅ | ✅ | ✅ | 1998 | Cumulative source since 1998 |
| AR | — | — | 🚫 | 🚫 | 🚫 | — | WARN data confidential by state law |
| AZ | 248 | 2016–2026 | ✅ | 🔨 | ⛔ | 2010 | JobLink reaches 2010 (PR #241); re-backfill Job pending (+508); 2009- empty at source |
| CA | 20,077 | 2006–2026 | ✅ | ✅ | 🔨 | 2000 | Wayback `cn00`–`cn08` HTML slices (verified 2026-07-09) |
| CO | 811 | 2015–2026 | ✅ | ✉ | ✉ | 2015 | Sweep: 2015 was CO's first published year — nothing older anywhere |
| CT | 1,496 | 1998–2026 | ✅ | ✉ | ✉ | 1998 ✅ | **done 2026-07-10** (+1,210, floor 2019→1998-01): monthly pages 1998–2008 + yearly 2010–2018 complete; **holes: all of 2013, 2009 except Aug/Sep** → ✉ |
| DC | 141 | 2005–2026 | ✅ | ✅ | ✉ | 2005 | Sweep: nothing pre-2005 in any archive (legacy domains checked) |
| DE | 42 | 2016–2026 | ✅ | 🔨 | ⛔ | 2007 | JobLink reaches 2007 (PR #241); Job pending (+37); 2006- empty at source |
| FL | 5,337 | 1998–2026 | ✅ | ✉ | ✉ | 1998 ✅ | **done 2026-07-10** (+3,003, floor 2020→1998-01): `react/warn.asp?year=Y` HTML 1998–2018 + reactwarn 2019; **2012 is a real hole** — the site itself had dropped the year (its only capture is a header-only table) → ✉ |
| GA | 264 | 2023–2026 | ✉ | ✉ | ✉ | 2022 (partial) | 2022 entry-page route **run 2026-07-10**: only **31 entries recoverable** (ids 071–103 minus pruned 083/097) → +0 inserts, 31 COALESCE field fills onto existing GA2022 rows; **ids 001–070 are NOT publicly recoverable** (the single-entry route renders an empty shell outside the server-side-filtered view) → ✉ with 2013–2021 (GDOL session app never archived) |
| HI | 418 | 2019–2026 | ✅ | ✉ | ✉ | 2019 | Sweep: DLIR never published a list before 2019 (guides only) |
| IA | 1,294 | 2005–2026 | ✅ | ✅ | ✉ | 2005 ✅ | **done 2026-07-10** (+804, floor 2021→2005-07; snapshot-union bundle; mark-superseded real run marked 2 zip-variance pairs); pre-2005 never published → ✉ |
| ID | 210 | 2008–2026 | ✅ | ✅ | ⛔ | 2008 ✅ | **done 2026-07-10** (+16, floor 2009→2008-02); the log itself begins 2008-02 — older likely nonexistent |
| IL | 3,742 | 1999–2026 | ✅ | ✅ | ✅ | 1999 | Complete (XLSX era + PDF era + Jan-2019 hand transcription) |
| IN | 1,508 | 2000–2026 | ✅ | ✅ | ✉ | 2000-11 ✅ | **done 2026-07-10** (+496, floor 2008→2000-11); gaps Jan–Oct 2000 (the archived 2000.html starts Nov 3), Nov–Dec 2004, Oct–Dec 2007 → ✉ |
| KS | 549 | 1999–2026 | ✅ | ✅ | ✅ | 1999 | Depth done; capped-year re-backfill Job pending (+344, PR #241) |
| KY | 1,183 | 1998–2026 | ✅ | ✅ | ✅ | 1998 ✅ | **done 2026-07-10** (+756, floor 2017→1998-10): kcc.ky.gov year-per-sheet XLSX workbooks 1998–2016 |
| LA | 606 | 2007–2026 | ✅ | ✅ | ✉ | 2007 ✅ | **done 2026-07-10** (+572, floor 2025→2007-01): `WarnNotices{2007..2024}.pdf`; only 2024 is a partial year (captured 2024-08-12; Sep–Dec 2024 published nowhere); pre-2007 never published → ✉ |
| MA | 577 | 2019–2026 | ✉ | ✉ | ✉ | 2019-07 ✅ | **done 2026-07-10** (+204, floor 2021-04→2019-07): FY2020 XLS + FY2021-through-Aug-2020 XLSX; **Sep 2020–Mar 2021 + pre-FY2020 → email** (eolwdpress@mass.gov) |
| MD | 1,881 | 2000–2026 | ✅ | ✅ | ✅ | 2000 ✅ | **done 2026-07-10** (+548, floor 2010→2000-01): `warn{2000..2009}.shtml` — same page family the scraper already parses. The old "no archive pre-2010" note was wrong |
| ME | 80 | 2012–2026 | ✅ | ⛔ | ⛔ | 2012 | JobLink source floor; capped-year Job pending (+12) |
| MI | 2,168 | 2000–2026 | ✅ | ✅ | ✅ | 2000 | milmi.org via Wayback — **done 2026-07-10** (+2,063, floor 2024-11→2000; parsers #247) |
| MN | 482 | 2012–2026 | ✅ | ⛔ | ⛔ | 2012 | Wayback backfill done 2026-07-10; 2012 = earliest filing in DEED annuals |
| MO | 557 | 2012–2026 | ✅ | ✉ | ✉ | 2012-07 ✅ | **done 2026-07-10** (+235, floor 2019→2012-07 — real recoverable was ~235, not 550–650): consolidated log PDF + PY pages; mid-PY capture gaps (Sep 2015–Jun 2016, May–Jun 2017, Jan–Jun 2018) have no Wayback coverage; those + pre-Jul-2012 → ✉ |
| MS | 409 | 2004–2026 | ✅ | ✉ | ✉ | 2004 ✅ | **done 2026-07-10** (+834, floor 2013→2004-06; 562 of those are Non-WARN rows kept but tagged per #279 — aggregates exclude them, so the API total shows 409): all 40 quarterlies PY2010–PY2019 + 2004–2006 era + PY2023-Q4; **Jul 2007–Jun 2010 never archived** → ✉ |
| MT | 43 | 2015–2026 | ✅ | ✉ | ✉ | 2015 | Sweep: only a rolling 2-yr window existed before the 2015+ cumulative file; nothing older ever published (~4 notices/yr) |
| NC | 1,002 | 2013–2026 | ✅ | ✉ | ✉ | 2013-01 ✅ | **done 2026-07-10** (+89, floor 2014→2013-01: 82 from `Warn-2013.pdf` + 7 hub-drift amendment dupes — 4 marked superseded 2026-07-11, 3 non-key-matching variants remain); Q4-2012 unrecoverable — no Dec-2012/Jan-2013 `Warn.pdf` capture in CDX; nothing pre-Oct-2012 (ncesc.com has zero WARN URLs) → ✉ |
| ND | 54 | 2015–2026 | ✅ | ✉ | ✉ | 2015 | Sweep: agency's own file is "WARN Notices 2015 to present" — 2015 is the start of the published record |
| NE | 148 | 2010–2026 | ✅ | ✅ | ✉ | 2010 ✅ | **done 2026-07-10** (+102, floor 2023→2010-02): frozen live endpoint 2010–2020 + Wayback 2021–2022; pre-2010 empty at source → ✉ |
| NH | — | — | ✉ | ✉ | ✉ | — | Not published online; split-custody FOIA drafted |
| NJ | 2,282 | 2004–2026 | ✅ | ✅ | ✉ | 2004 | Workbook floor 2004; pre-2004 unprobed/unpublished → ✉ if pursued |
| NM | 114 | 2016–2026 | ✅ | ✉ | ✉ | 2016 | Sweep: 2016 PDF is the earliest list ever published (older pages are guides) |
| NV | 621 | 2017–2026 | ✅ | ✉ | ✉ | 2017 | Sweep: detr.state.nv.us/nvdetr.org 2001–2016 have guides only — no list pre-2017; Jun–Dec 2025 gap also ✉ |
| NY | 8,708 | 2006–2026 | ✅ | ✅ | ✉ | 2006 | Crosstab floor 2006; pre-2006 → FOIA backstop (draft exists) |
| OH | 3,172 | 1996–2026 | ✅ | ✅ | ✅ | 1996 | Complete; gap-year re-run 2007–2024 pending; 2025 unaccounted |
| OK | 198 | 2001–2026 | ✅ | ✅ | ✉ | 2001 | Portal reaches 2001; pre-2001 → FOIA drafted |
| OR | 866 | 1989–2026 | ✅ | ✅ | ✅ | **1989** ✅ | **done 2026-07-10** (+766, floor 2020→**1989-03**, ~100→866): Socrata + Wayback capture union — **no mid-2000s gap** (the sweep's "possible gap" worry was wrong); ~389 date-less 1990s rows dropped (dates only in scanned per-notice PDFs) → ✉; follow-up: ~95 HECC-master-vs-Socrata-facility duplicates need a computed notice-id supersede list |
| PA | 3,715 | 1998–2026 | ✅ | ✅ | ✅ | 1998-07 ✅ | **done 2026-07-10** (+394, floor 2001→1998-07; the dry-run-throttled 1999 Oct+Nov healed on the real run); **Dec 2000 never captured — permanent gap** |
| RI | 125 | 2009–2026 | ✅ | ✅ | ✉ | 2009 | Sweep: earliest listing ever archived is the 2009 table — nothing older exists |
| SC | 1,178 | 2009–2026 | ✅ | ✅ | ✉ | 2009 ✅ | **done 2026-07-10** (+1,153, floor 2026→2009-01): Wayback 2009–2019 + still-live unlinked 2020–2025 PDFs; the 2022 Apr–Dec hole closed via the live 12-15-2022 edition; residual holes only Dec 16–31 2022, Dec 2023, Dec tails of 2016/17/19; 2013–2021 editions print no notice dates → Jan-1-of-year proxy dates |
| SD | 139 | 1997–2026 | ✅ | ✅ | ✅ | 1997 ✅ | **done 2026-07-10** (+60, floor 2007→1997-07): frozen cumulative PDF Jul-1997–Dec-2005; gap 2006→Apr-2007 (≈0–5 notices) |
| TN | 90 | 2025–2026 | 🔨 | ✉ | ✉ | 2018 | 2018–2024 verified in Wayback (reports-page captures + 534 letter PDFs); pre-2018 ✉ (TPRA citizens-only caveat) |
| TX | 5,430 | 2004–2026 | ✅ | ✅ | ✉ | 2004 ✅ | **done 2026-07-10** (+3,192, floor 2020→2004-01): Wayback XLS/XLSX 2004–2018 (two hosts) + Socrata 2019; pre-2004 → ✉ |
| UT | 9 | 2026 | ✅ | ✅ | ✉ | 2009 | **Fix merged 2026-07-10 (#260, parse all year sections)** — first full scrape pending: expect ~275 rows / floor 2009 at the next morning run; pre-2009 never published |
| VA | 1,337 | 1999–2026 | ✅ | ✅ | 🔨 | 1999-07 (partial) ✅ | **done 2026-07-10** (+221, floor 2010→1999-07: PY1999/PY2002/PY2003 bundle); **PY2004–06 ARE recoverable via a Wayback refetch** 🔨 (the sweep's "unrecoverable" verdict was wrong — a local cache bug overwrote the fetched generations); **PY2000–01 and Jul-2006–Dec-2009 unrecoverable** → ✉ |
| VT | 97 | 2003–2026 | ✅ | ✅ | ⛔ | 2003 | JobLink source floor; capped-year Job pending (+3) |
| WA | 1,480 | 2004–2026 | ✅ | ✅ | ⛔ | 2004 | Pagination reaches source floor 2004-01 |
| WI | 3,637 | 1996–2026 | ✅ | ✅ | ✅ | 1996 ✅ | **done 2026-07-10** (+2,693, floor 2016→1996-01: PCML XLS logs 1996–2015); the 2016 file was abandoned by DWD in Feb-2016 (13 rows, all already in prod) — excluded |
| WV | 415 | 2011–2026 | ✅ | ✉ | ✉ | 2011 ✅ | **done 2026-07-10** (+366, floor 2021→2011-03; 2 live employer-variant rows superseded — Mylan 2021-05-24 and Monongalia County Coal Resources 2021-06-04, the state log's revised rows kept); pre-2011 never captured → ✉ |
| WY | — | — | 🚫 | 🚫 | 🚫 | — | No public data; confidential by state law |

## Sweep verdicts — recoverable (build queue detail)

Ranked by estimated rows. Every entry lists the pattern + one verified capture;
"latest capture per year" applies to all rolling/cumulative files.

**All routes below were built (PRs #258–#281) and run in prod 2026-07-10
(w_homelab #709–#715).** Actual inserts are in the build-queue table; the
sections stay as route documentation, with post-run corrections folded in.

### TX — Wayback 2004–2018 + Socrata 2019 — ✅ +3,192 in prod (2026-07-10)
`twc.texas.gov/files/news/warn-act-listings-{Y}.xls` (2004–2013) / `.xlsx`
(2014–2018); mirror host `www.twc.state.tx.us` fills gaps — **2017 exists only
there**, and post-year captures for 2016/2018 too. Schema identical to Socrata
`data.texas.gov/resource/8w53-c4f6.json` (re-verified: 2,368 rows,
2019-01-04→2026-06; 2019=153, 2020=1,209). Verified:
`web.archive.org/web/20161223010946id_/http://twc.texas.gov/files/news/warn-act-listings-2010.xls`
(166 rows, complete year). Caveats: rolling-within-year → take the latest
capture from whichever host has one dated after Jan 1 of the next year; `.xls`
needs xlrd. Pre-2004: nothing on either host → FOIA.

### FL — Wayback 1998–2019, essentially complete — ✅ +3,003 in prod (2026-07-10)
`floridajobs.org/react/warn.asp?year={Y}` (1998–2018, one cumulative HTML page
per year, case-insensitive REACT) + `reactwarn.floridajobs.org/WarnList/Records?year=2019`
(2 pages). Every year has a post-year 200 capture. Verified:
`web.archive.org/web/20160622214052id_/http://floridajobs.org/REACT/warn.asp?year=2005`
(113 rows). Caveats: company name + street address glued in one cell; layoff
date often a "x thru y" range; 1997 is a soft-404 — floor is 1998.
**Built + run 2026-07-10** (`parse_fl_warn_asp` + pinned replay captures in
`warn_v2/scrapers/states/fl.py`; `backfill-historical --state FL`): +3,003 in
prod, floor 1998-01, city/ZIP on every row. One hole: **2012 is a real hole —
the site itself had dropped the year** (its only capture, Nov 2019, is a
header-only table); recovering 2012 needs a records request.

### SC — Wayback 2009–2019 + still-live unlinked PDFs 2020–2025 — ✅ +1,153 in prod (2026-07-10)
2009–2018: `scworks.org/docs/librariesprovider6/layoff-notification-reports/{Y}_layoff_notifications*.pdf`
(2016–2018 carry date suffixes); 2019: `2019-warn-report-(12-18-19).pdf`.
2020–2025: direct dew.sc.gov/scworks.org `sites/.../Documents/{Y} ... WARN Report ....pdf`
URLs still return 200 live though unlinked. Verified:
`web.archive.org/web/20200418074824id_/https://scworks.org/docs/librariesprovider6/layoff-notification-reports/2012_layoff_notifications.pdf?sfvrsn=d83615d7_4`
(13 pp, monthly sections, county+NAICS). Caveats: multiple snapshot editions
per year — take the latest-dated filename; 2019 edition dated 12-18-19 may miss
late Dec; text-layer PDFs with Unicode apostrophes. Pre-2009 (sces.org): nothing.
Run outcome: the 2022 Apr–Dec hole closed via still-live
`scworks.org/sites/scworks/files` editions (12-15-2022 edition); residual holes
only Dec 16–31 2022, Dec 2023, and the Dec tails of 2016/17/19. The 2013–2021
editions print no notice dates → those rows carry Jan-1-of-year proxy dates
(documented convention).

### WI — Wayback 1996–2015 XLS logs — ✅ +2,693 in prod (2026-07-10)
`worknet.wisconsin.gov/worknet_info/downloads/PCML/{Y}pcml_log.xls` — one file
per year, **every year 1996–2016 captured**. Verified:
`web.archive.org/web/20140904102400id_/http://worknet.wisconsin.gov/worknet_info/downloads/PCML/2010pcml_log.xls`
(~110–140 notices; NAICS, type, schedule). Caveats: records span multiple sheet
rows (address/contact lines under company); "(update)" amendment rows; may
include sub-threshold notices; xlrd needed. Run outcome: 2,693 rows 1996–2015;
the 2016 PCML file was **abandoned by DWD in Feb-2016** (13 rows, all already
in prod) — excluded.

### LA — Wayback 2007–2024 per-year PDFs — ✅ +572 in prod (2026-07-10)
`laworks.net/Downloads/WFD/WarnNotices{Y}.pdf` — **every year 2007–2026 has a
200 capture** (2021/2022 under `www2.laworks.net`). Verified:
`web.archive.org/web/20231011195653id_/https://www.laworks.net/Downloads/WFD/WarnNotices2020.pdf`
(10 pp, ~119 rows). Caveats: cumulative-within-year → latest capture per year;
company cells wrap with embedded multi-line addresses. Pre-2007: nothing.
Run outcome: real recoverable was **576, not 1,200–1,800** — the sweep's
estimate double-counted repeated page headers. Only 2024 is a partial year
(latest capture 2024-08-12; Sep–Dec 2024 published nowhere).

### CT — Wayback 1998–2018, two eras — ✅ +1,210 in prod (2026-07-10)

Built as `backfill-historical --state CT` (142 pinned captures in
`warn_v2/scrapers/states/ct.py`); ran in the serial Wayback Job (~150
sequential fetches at the throttled pace, the long tail of the train):
**+1,210, floor 1998-01**. Coverage is complete 1998–2008 monthly +
2010–2018 yearly.

1998–2008: monthly pages under
`ctdol.state.ct.us/progsupt/bussrvce/warnreports/{Y}%20Warn%20Reports/warnreports{Y}-{M}.htm`
(1998–2000 use variant names `warn-0198.htm` / `warn-99-01.htm` /
`warn2000-01.htm`); 2010–2018: cumulative `warnreports/warn{Y}.htm`. Verified:
`web.archive.org/web/20061003124631id_/.../2005%20Warn%20Reports/warnreports2005-06.htm`
(June 2005, 5 notices) and `.../20190720163140id_/.../warn2015.htm` (~37
notices). **Holes → FOIA:** all of 2013 (never captured, no variant found),
2009 months 1–7 and 10–12 (only Aug+Sep captured), possibly Dec 21–31 2012.
Caveats: `Rec'd` glued into date cells, smart-quote artifacts, free-text
counts, amended notices as near-duplicate rows. Note: `warn2019.htm`–`warn2025.htm`
also exist as a cross-check of current-era data.

### KY — Wayback 1998–2016 XLSX workbooks — ✅ +756 in prod (2026-07-10)
`kcc.ky.gov/documents/RapidResponse/WARNRecordByYear.xlsx` (capture
20150927133413; sheets "WARN 1998"…"WARN 2015", 741 rows) and
`kcc.ky.gov/Documents/WARN%20Report%202016.xlsx` (capture 20161222125836; adds
"WARN 2016", 38 rows). Both downloaded + parsed with openpyxl during the sweep.
Caveats: Dec-2016 capture may miss the final week (cross-check the live
SharePoint workbook's 2017 start); one `2106-07-06` typo date; low-count years
2002–2007 (4–12 rows/yr) are consistent across independent captures — real
reporting gaps, not truncation.

### IA — Wayback rolling-log snapshots, union covers 2005-07→2021 — ✅ +804 in prod (2026-07-10)
~180 dated snapshots of a pruning cumulative log. Union these four:
`WARN_20150722.pdf` (2005-07→2015-07; capture 20150903000422),
`WARN_20171219.xlsx` (2011→2017-12), `WARN_20210105.xlsx` (2015-08→2021-01;
capture 20210107103313), `WARN_20230823.xlsx` (2018-09→2023, overlaps floor).
All under `iowaworkforcedevelopment.gov/sites/search.iowaworkforcedevelopment.gov/files/**`.
Caveats: heavy overlap → dedupe on (company, notice_date, layoff_date, city);
"Amendment" rows; XLSX has trailing empty columns / unsized sheets (openpyxl
read_only quirk); PDF-only for 2005–2011. Pre-2005: never published.
Post-run: the real `mark-superseded --state IA` pass marked 2 zip-variance
pairs.

### MO — Wayback Jul-2012→2019 — ✅ +235 in prod (2026-07-10)
`jobs.mo.gov/sites/jobs/files/warn_log_jul2012_to_present_2015-07-01.pdf`
(capture 20151018024542; 17 pp, Jul 2012→Jul 2015) + `warn-log-py2015.pdf`
(20161223014721) + HTML PY pages: `jobs.mo.gov/es/warn2016` (20170409074237 —
Spanish-path capture of the English table), `content/missouri-warn-notices-py-2017`
(20171204110254), `-py-2018` (20190211194351). Caveats: **program years
(Jul–Jun)**; rolling YTD → latest capture per PY; pre-Jul-2012 → FOIA (ded.mo.gov
etc. all negative). Run outcome: real recoverable was **~235, not 550–650** —
mid-PY capture gaps (Sep 2015–Jun 2016, May–Jun 2017, Jan–Jun 2018) have no
Wayback coverage and stay Sunshine-Law territory.

### MD — Wayback 2000–2009 year pages, existing parser family — ✅ +548 in prod (2026-07-10)
`dllr.state.md.us/employment/warn{2000..2009}.shtml` all captured (2000–2007
at 20081205…, warn2008 at 20090421050910, warn2009 at 20110419154158); `.htm`
originals exist for 2000–2007 too. Verified: warn2000.shtml (77 notices,
KMART), warn2005.shtml (90). All captures post-date year end → complete years.
**Corrects the old "no archive pre-2010" note.** Extending the existing
`warn{year}.shtml` ingester back to 2000 should just work.

### IN — Wayback 2000–2007 DWD pages — ✅ +496 in prod (2026-07-10)
`in.gov/dwd/workforce_stats/warn/{2000..2003}.html` (per-year tables) +
`workforce_stats/warn/notices.html` (rolling 2003–2005; Oct-2004 capture holds
Jan–Oct 2004) + `in.gov/dwd/employers/warn_notices.html` (accumulating
2005–2007; capture 20070921184150 holds all three years). Verified: 2000.html
capture 20030423222041 (FFI Corporation, SIC-coded rows). Gaps: **Jan–Oct 2000
(newly found on the run — the archived 2000.html starts Nov 3)**, Nov–Dec 2004,
Oct–Dec 2007. SIC pre-2005, NAICS after.

### MS — Wayback quarterlies: PY2010–PY2019 complete + 2004–2006 + PY2023-Q4 — ✅ +834 in prod (2026-07-10)
All 40 quarters `mdes.ms.gov/media/{id}/py{Y}_q{n}_warn_{months}.pdf` have 200
captures (companion `_map.pdf`s too). **The missing PY2023-Q4 is recovered**:
`web.archive.org/web/20240816055525id_/https://mdes.ms.gov/media/440515/py2023-q4-warn-apr2024-jun2024.pdf`
(its header reads "PROGRAM YEAR 2023" — the sweep's "mislabels 2024" claim was
a misread). Older era:
`mdes.ms.gov/wps/PA_1_0_{6A,CH}/docs/Employer/Warn{Y}Q{n}.pdf` for 2004–2006
(filename year = calendar year, not PY — parse the in-PDF header). **Jul 2007–Jun
2010: CDX has only 404 captures → FOIA window.** Caveats: quarterlies mix
flagged "Non-WARN" Rapid Response events — **kept and tagged**
`closure_category = "Non-WARN"` per #279 (562 of the +834; aggregates exclude
them, so the API total shows 409); several filename mislabels
(`py2014_q2...jan2015_mar2015` is really Q3).

### WV — Wayback cumulative PDF 2011→2021 — ✅ +366 in prod (2026-07-10)
`workforcewv.org/images/files/PublicInfo/WV_WARN_Notices_3-1-11_to_6-7-21.pdf`
(capture 20211026131319) — one block per notice (company/address/county/dates/
count), bridges exactly to the 2021 floor. Older complete copies on
wvcommerce.org (`…to_8-12-14.pdf`, capture 20161221062445) as cross-checks.
Caveats: **the 6-7-21 capture is crawler-truncated at exactly 1 MiB —
pdfplumber fails but PyMuPDF/fitz repairs it and recovers all 137 pages**;
repeated-character-collapse in text extraction ("Mas Layof") — parse
defensively or OCR; pre-2011 never captured. Post-run: 2 live employer-variant
rows superseded (Mylan 2021-05-24/1,246 and Monongalia County Coal Resources
2021-06-04/None — the state log's revised rows kept).

### PA — Wayback Jul-1998→Nov-2000 month pages — ✅ +394 in prod (2026-07-10)
1998: `dli.state.pa.us/warn.html` (capture 19991104100952; Jul–Nov 1998
sections). 1999: `li.state.pa.us/dept/warn/{mon}99.html` all 12 months (some
only on the `li.` mirror). 2000: `{mon}00.html` Jan–Nov (**note `sept00`**;
dec00 was never captured — the one gap). Same employer/county/count/effective-date
block format as the existing per-month parser lineage. Verified: jan99.html
capture 20000709183110 (SANYO Reedsville 81). Run outcome: 1999 Oct+Nov —
throttled away during the dry run — healed on the real run; Dec 2000 stays a
permanent gap.

### OR — Socrata 2020+ + Wayback app captures — ✅ +766 in prod (2026-07-10), floor **1989-03**
Live HECC app now holds ZERO pre-2020 rows (purged; verified via the export
POST). A June-2024 crawl captured `ccwd.hecc.oregon.gov/Layoff/WARN?page=N&SortOrder=X`
pages 1–22 in ~12 sort variants while the app still held full history (~51
pages). Verified: page=10 capture 20201006143908 (2016–17 rows); page=22
SortOrder=EstDate_desc capture 20240621021957 (2009–10 rows). Run outcome:
the capture union recovers dated rows back to **1989** (not ~2009) and there
is **NO mid-2000s gap** — the sweep's worry was unfounded; prod OR went
~100 → 866. ~389 date-less 1990s rows dropped (dates only in scanned
per-notice upload PDFs, also archived) → FOIA. **Pending follow-up:** ~95
HECC-master-vs-Socrata-facility duplicates need a computed notice-id
supersede list.

### UT — live page already cumulative 2009–2026 — 🔨 fix merged (#260), first full scrape pending
`jobs.utah.gov/employer/business/warnnotices.html` holds 18 per-year sections
(~275 rows) **today**; the scraper only ingests the current-year section.
Wayback corroborates (capture 20100413170506 of the `.asp` predecessor).
Caveats: sloppy old dates (`05/2009`, `01/07//09`); no county/NAICS; pre-2009
never published. The parse-all-sections fix merged 2026-07-10 (#260) and ships
via the daily scrape — expect ~275 rows / floor 2009 at the next morning run.

### VA — Wayback PY1999 + PY2002–PY2003 — ✅ +221 in prod (2026-07-10, partial)
**Built + run 2026-07-10** (Mode 3b `warn_v2/scrapers/data/va_archive.tar.gz`):
PY1999 `vec.state.va.us/docs/xls/warnnot99.xls` (capture 20030426225501; 59
notices, multi-row address blocks) + PY2002 `vec.state.va.us/pdf/warnlog03.pdf`
(capture 20050510175855; 87 rows, one row printed twice in the source) +
PY2003 `warnnot04_files/sheet001.htm` statewide Excel-HTML sheet (76 rows) —
222 rows, 221 unique — all in prod. Regional-tab dedupe verified: the four
regional sheets' union is a subset of Statewide (modulo one amended notice
date), so only the statewide sheet is bundled. **Follow-up build (small):** the
PY2004 (`WARNLOGPY04_files`), PY2005 and PY2006 workbook data sheets ARE
captured in Wayback — the sweep's "unrecoverable" verdict was wrong (the
capture generations exist; the local cache's fixed filenames let later
generations overwrite them, so only the last-fetched warnnot04 sheets
survived); refetch per-workbook and extend the bundle. **Unrecoverable:
PY2000–01 (never captured), Jul-2006→Dec-2009** → FOIA. Caveats: three
formats; program years Jul–Jun.

### MA — Wayback FY2020 + early FY2021 — ✅ +204 in prod (2026-07-10)
`mass.gov/doc/warn-report-for-fy-2020/download` (capture 20200828043125;
legacy .xls, 6 regional sheets, ~175 notices — Date Received / Company / City /
Layoff Date / # Affected) + `warn-report-for-week-ending-08-21-20/download`
(capture 20200828041524; FY-cumulative through Aug 21 2020, ~40 rows). **Zero
WARN docs captured between 2020-08-28 and 2021-11-30** → the Sep-2020→Mar-2021
tail and pre-FY2020 stay email-only (agency invites it).

### NC — Wayback 2013 — ✅ +89 in prod (2026-07-10)
`nccommerce.com/Portals/11/WARN/Warn-2013.pdf` (capture 20150327025758; full
calendar 2013, 82 notices, 9,869 employees) — pinned into
`_discover_nc_pdf_urls`; same summary-count layout as 2014–2017, letter-spaced
city glyphs despaced by glyph gap (nc.py `_join_city`). Known source typo kept
as printed: one December-section row reads "2/03/2013" (really 12/03). The
rolling `Warn.pdf` Q4-2012 slice is **unrecoverable** — no Dec-2012/Jan-2013
capture exists in CDX, so the floor is **2013-01, not 2012-10**. Pre-Oct-2012:
nothing (ncesc.com has zero WARN URLs). Run outcome: +89 = 82 from
`Warn-2013.pdf` + 7 hub-drift amendment dupes; the mark-superseded pass
(2026-07-11) marked the 4 key-matching pairs (AAR Manufacturing, Bottom Dollar
Food Stores, Fluor Federal Solutions, Stanley Furniture — all zip-variance);
the other 3 don't key-match (employer-name drift) and stay as variants.

### NE — live frozen endpoint 2010–2020 + Wayback 2021–2022 — ✅ +102 in prod (2026-07-10)
`dol.nebraska.gov/LayoffServices/WARNReportData/?year={2010..2020}` **still
serves historical years live today** (HTML fragment: Date/Company/Jobs
Affected/City/Location; 2008/2009 and 2021+ return empty). 2021–2022 from
captures of the current rolling page (e.g. 20221126185419, 28 rows spanning
2020–2022). Wayback also holds the older `WARNReport?year=` pages 2013–2017 as
fallback. **Snapshot the live endpoint promptly — it's legacy/undocumented.**

### GA — 2022 partial via live entry pages — ✅ run 2026-07-10 (31 field fills, +0 inserts)
`tcsg.edu/warn-public-view/entry/{id}/` pages are still served live for 2022
notices (verified: entry 41068 = GA202200071, Dexter Axle, first separation
2023-01-09); 153 entry pages ≥41068 are also archived. Run outcome: only **31
entries were recoverable** (ids 071–103 minus pruned 083/097), applied as
COALESCE fills of county/address/closure_type/separation-date onto existing
GA2022 rows. **GA202200001–070 are NOT publicly recoverable** — the
single-entry route renders an empty shell for ids outside the
server-side-filtered view — so they join the FOIA scope with 2013–2021
(GDOL era: the session-based search app archived only empty forms).

### SD — Wayback 1997–2005 cumulative PDF — ✅ +60 in prod (2026-07-10)
`state.sd.us/dol/WIA/WIA%20Handbook/WARN%20Notices%20Received.pdf` (captures
20060618123843 / 20070114121809 — identical, frozen at PY-05): 60 notices,
8,232 workers, Jul-1997→Dec-2005 (Date/Company/Location/#Workers/Action).
Gap 2006-01→2007-04 (successor page starts 05/2007 = current floor; SD ~5
notices/yr, so ≈0–5 lost). One out-of-order row — parse by date, not position.

### ID — Wayback 2008 log — ✅ +16 in prod (2026-07-10)
`labor.idaho.gov/pdf/WARNNotice.pdf` (capture 20090418074939) — cumulative
log whose 2008 rows (incl. Micron Boise 1,400–1,600) were dropped from the
current live `WARN-NOTICES-LOG_2009-2025.pdf`. Idaho's log begins 2008-02;
pre-2008 may simply not exist.

## Sweep verdicts — confirmed FOIA-only (probes found nothing)

| State | Window confirmed unpublished | Evidence |
|---|---|---|
| HI | pre-2019 | dlir.state.hi.us 1999+ captures are law guides only; wdc file inventory starts 2019 |
| NV | pre-2017 | detr.state.nv.us / nvdetr.org 2001–2016: guides + Rapid Response pages, no lists |
| NM | pre-2016 | 2011/2012 Rapid Response pages link only the employer guide; 2016 PDF is the first list |
| CO | pre-2015 | Dec-2016 capture of warn-listings links exactly two sheets: 2015 + 2016 (first published years) |
| ND | pre-2015 | agency file literally titled "WARN Notices 2015 to present"; 1997–2008 captures are info pages |
| MT | pre-2015 | pre-2021 site published only a rolling ~2-yr window; DLI domain sweep negative |
| DC | pre-2005 | does.dc.gov + 1998–2004 legacy domains: zero WARN listing URLs |
| RI | pre-2009 | earliest archived listing is the 2009 table (warn3.htm); dlt.state.ri.us negative |
| GA | 2013–2021 + 2022 ids 001–070 | GDOL session-app captures render empty search forms; CICS-era logs never crawled; the TCSG single-entry route renders an empty shell for ids outside the server-side-filtered view (only ids 071–103 recovered — run 2026-07-10) |
| CT | 2013 + most of 2009 | year page never captured (2013); only Aug/Sep monthlies exist (2009) |
| TX | pre-2004 | no earlier files on either TWC host (domain + /news/ sweeps) |
| MS | Jul 2007–Jun 2010 | quarterlies exist in CDX only as 404 captures from 2013 |
| VA | PY2000–01, Jul 2006–Dec 2009 | never captured (PY2004–06 data sheets ARE in Wayback — refetch follow-up build, the sweep's "unrecoverable" verdict was a local cache bug) |
| MO | pre-Jul-2012 + Sep 2015–Jun 2016, May–Jun 2017, Jan–Jun 2018 | ded.mo.gov, dolir.mo.gov, missourieconomy.org all negative; the mid-PY capture gaps have no Wayback coverage (found on the 2026-07-10 run) |
| MA | Sep 2020–Mar 2021, pre-FY2020 | zero WARN doc captures 2020-08-28→2021-11-30; weekly docs never crawled |
| FL | 2012 | a real hole — the site itself had dropped the year (its only capture is a header-only table) |
| IN | Jan–Oct 2000 | the archived 2000.html starts Nov 3 (found on the 2026-07-10 run) |
| LA | Sep–Dec 2024 | latest 2024 capture is 2024-08-12; the Sep–Dec tail was published nowhere |
| PA | Dec 2000 | the one month page never captured — permanent gap |
| NC | Q4 2012 | no Dec-2012/Jan-2013 capture of the rolling `Warn.pdf` exists in CDX |
| OR | date-less 1990s rows (~389) | dates only in scanned per-notice upload PDFs — dropped from the 2026-07-10 ingest |
| SC | Dec 16–31 2022, Dec 2023, Dec tails of 2016/17/19 | residual edition-cutoff holes after the 2026-07-10 run |

## Build queue — ALL 23 DONE 2026-07-10 (builds #258–#281, prod Jobs w_homelab #709–#715)

Actual prod inserts vs the sweep estimates ("est." column kept for the record):

| # | Build | Recovers | Est. rows | Actual (2026-07-10) |
|---|---|---|---|---|
| 1 | ✅ TX Wayback XLS/XLSX + Socrata 2019 | 2004–2019 | ~2,700–3,700 | **+3,192**, floor 2004-01 |
| 2 | ✅ FL warn.asp HTML | 1998–2019 | ~2,200–3,000 | **+3,003**, floor 1998-01; 2012 is a real hole → ✉ |
| 3 | ✅ SC year PDFs (Wayback + live-unlinked) | 2009–2025 | ~1,500–3,000 | **+1,153**, floor 2009-01; 2022 Apr–Dec closed via live 12-15-2022 edition |
| 4 | ✅ WI PCML XLS logs | 1996–2015 | ~1,500–2,500 | **+2,693**, floor 1996-01; abandoned 13-row 2016 file excluded |
| 5 | ✅ LA WarnNotices PDFs | 2007–2024 | ~~1,200–1,800~~ ~576 (headers double-counted) | **+572**, floor 2007-01; Sep–Dec 2024 published nowhere |
| 6 | ✅ CT monthly+yearly HTML | 1998–2018 | ~900–1,400 | **+1,210**, floor 1998-01; 2013 + most-of-2009 holes → ✉ |
| 7 | ✅ KY workbook captures | 1998–2016 | ~780 | **+756**, floor 1998-10 |
| 8 | ✅ IA snapshot union | 2005–2021 | ~600–800 | **+804**, floor 2005-07; mark-superseded real: 2 zip-variance pairs |
| 9 | ✅ MO logs + PY pages | 2012-07–2019 | ~~550–650~~ ~235 (mid-PY capture gaps) | **+235**, floor 2012-07 |
| 10 | ✅ MD warn{Y}.shtml 2000–2009 | 2000–2009 | ~400–600 | **+548**, floor 2000-01 |
| 11 | ✅ IN DWD pages | 2000–2007 | ~450–530 | **+496**, floor 2000-11; new gap Jan–Oct 2000 |
| 12 | ✅ MS quarterlies (incl. PY2023-Q4) | 2004–Jun 2010 hole-adjacent + PY2010–19 | ~400–800 | **+834**, floor 2004-06 (562 tagged Non-WARN; API total 409) |
| 13 | ✅ WV cumulative PDF | 2011–2021 | ~350 | **+366**, floor 2011-03; 2 live variants superseded |
| 14 | ✅ PA pre-2001 month pages | 1998-07–2000-11 | ~300–350 | **+394**, floor 1998-07; 1999 Oct+Nov healed on real run |
| 15 | ✅ OR Socrata + app captures | **1989**–2026 | ~500–700 | **+766**, floor **1989-03** (~100→866); ~95-dupe supersede list pending |
| 16 | 🔨 UT scraper fix | 2009–2026 | ~265 | fix merged (#260); first full scrape pending (~275 expected) |
| 17 | ✅ VA three-format captures | PY1999, PY2002–03 | ~240–260 | **+221**, floor 1999-07; PY2004–06 refetch = follow-up build |
| 18 | ✅ MA FY2020 + wk-2020-08-21 | 2019-07–2020-08 | ~215 | **+204**, floor 2019-07 |
| 19 | ✅ NC 2013 | 2013 | 82 | **+89** (82 + 7 amendment dupes; 4 marked superseded 2026-07-11), floor 2013-01 |
| 20 | ✅ NE frozen endpoint + captures | 2010–2022 | ~130 | **+102**, floor 2010-02 |
| 21 | ✅ GA 2022 entry pages | 2022 | ~~70–100~~ 31 | **+0 inserts** — 31 COALESCE field fills; ids 001–070 → ✉ |
| 22 | ✅ SD 1997–2005 PDF | 1997–2005 | ~60 | **+60**, floor 1997-07 |
| 23 | ✅ ID 2008 log | 2008 | ~17 | **+16**, floor 2008-02 |

Wave total: **+17,714** (bundled batch +3,295 + Wayback batch +14,419).
Post-run: a 12-state mark-superseded sweep (2026-07-11) found pairs only in
NC — 4 zip-variance pairs marked; every other state came back zero. OR's ~95
HECC-master-vs-Socrata-facility duplicates need a computed notice-id
supersede list (follow-up — the automated matcher can't key-match them).

Still queued (pre-sweep items): JobLink re-backfill Jobs AZ/KS/DE/ME/VT
(~900), TN 2018–2024 (~500+), CA 2000–2005 (Wayback HTML slices), OH gap-year
re-run 2007–2024. MI 2000–2024 shipped mid-sweep (**done 2026-07-10**, +2,063).

## Cross-cutting lessons from the sweep

- **CDX `matchType=domain` + `filter=original:.*warn.*` can silently return 0
  on large domains** (confirmed false-negative on jobs.mo.gov) — never trust it
  as a negative; use targeted prefixes or full-domain dumps + local grep.
- Wayback truncates some large PDFs at exactly 1 MiB (WV) — check
  `x-archive-orig-content-length` and repair with PyMuPDF.
- Rolling/cumulative files: always take the **latest capture per year**, and
  prefer a capture dated after Jan 1 of the following year.
- Several states' "current" pages silently hold full history the scraper
  ignores (UT) or legacy endpoints still serve old years live (NE, SC direct
  PDF URLs, GA entry pages) — probe live before assuming Wayback-only.
