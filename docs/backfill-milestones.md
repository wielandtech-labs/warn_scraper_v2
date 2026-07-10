# Backfill milestones — per-state status toward global 2020 / 2010 / 2000

Milestone-oriented rollup of historical coverage: which states block **every
jurisdiction back to 2020-01**, then **2010-01**, then **2000-01 (stretch)** —
and the route for each. Runbooks and prior probe history live in
[historical-sources.md](historical-sources.md); this doc is the scoreboard plus
the verdicts of the **2026-07-10 milestone probe sweep** (Wayback CDX +
live-site probes of every state without a known route; every positive verdict
below was verified by fetching an actual capture and reading WARN rows in it).

Ranges are the **verified prod floors as of 2026-07-10** — the 2026-07-07
STATE_AUDIT.md table is stale for CA (2006, 20,077 rows), NY (2006, 8,708),
MN (2012, 482), WA (2004, ~1,480), MI (2000, 2,168); those use the post-run
numbers recorded in historical-sources.md Progress.

**Route legend:** ✅ done · 🔨 build item (route verified, code/Job pending) ·
🔍 sweep verdict 2026-07-10 (recoverable, needs a parser build) ·
✉ FOIA/records request only · ⛔ source floor (state confirms nothing older
exists) · 🚫 blocked by state law.

## Milestone scoreboard

| Milestone | After the 🔨/🔍 builds below, what still blocks it |
|---|---|
| **Global 2020** | Only **GA 2013–2021** (✉ — the old GDOL search app was never archived) and **MA Sep 2020–Mar 2021** (✉ — weekly files not crawled; agency invites email). Everything else is recoverable: UT→2009, SC→2009, LA→2007, IA→2005, WV→2011, NE→2010, TN→2018 🔨; MI→2000 ✅ (done 2026-07-10). |
| **Global 2010** | Adds ✉-only: **HI, NV, NM, CO, ND, MT** (probes confirm those states never published pre-floor lists) + partial holes: MO pre-Jul-2012, MS Jul-2007–Jun-2010, NC pre-Oct-2012, CT 2013 + most of 2009, OR pre-2009. ⛔ source floors: ME (2012), MN (2012). AZ reaches 2010 once the JobLink Job runs. |
| **Global 2000** | Big sweep wins get 12 states to ~2000: FL/CT/KY→1998, WI→1996, PA→1998-07, MD/IN→2000, SD→1997, CA→2000 🔨, MI→2000 ✅, plus existing OH/AL/IL/KS. Rest are ✉ (TX pre-2004, NY pre-2006, NJ pre-2004, DC, RI, OK pre-2001…) or ⛔ (VT, WA, AK, DE, AZ). |

Estimated recoverable volume from the sweep, **no FOIA needed: ~15–20k rows**
(vs ~38k currently in prod).

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
| CT | 286 | 2019–2026 | ✅ | 🔨 | 🔨 | 1998 | Wayback: monthly pages 1998–2009 + yearly `warn{Y}.htm` 2010–2018 **built** (`backfill-historical --state CT`, 142 pinned captures, 1,342 rows offline); prod Job pending; **holes: all of 2013, Jan–Jul + Oct–Dec 2009** → ✉ |
| DC | 141 | 2005–2026 | ✅ | ✅ | ✉ | 2005 | Sweep: nothing pre-2005 in any archive (legacy domains checked) |
| DE | 42 | 2016–2026 | ✅ | 🔨 | ⛔ | 2007 | JobLink reaches 2007 (PR #241); Job pending (+37); 2006- empty at source |
| FL | 2,334 | 2020–2026 | ✅ | 🔨 | 🔨 | 1998 | Wayback: `react/warn.asp?year=Y` HTML 1998–2018 + reactwarn 2019 — parser built 2026-07-10 (2,863+152 rows offline; the lone 2012 capture is empty), ingest Job pending |
| GA | 264 | 2023–2026 | ✉ | ✉ | ✉ | 2022 (partial) | 2022: ~70–100 notices via still-live TCSG `/warn-public-view/entry/{id}/` pages 🔍; 2013–2021: GDOL session app never archived → ✉ |
| HI | 418 | 2019–2026 | ✅ | ✉ | ✉ | 2019 | Sweep: DLIR never published a list before 2019 (guides only) |
| IA | 490 | 2021–2026 | 🔍 | 🔍 | ✉ | 2005 | Wayback: union of 4 rolling-log snapshots (PDF 2005–2015, XLSX 2011–2023) covers 2005-07→2021 (+600–800) |
| ID | 194 | 2009–2026 | ✅ | ✅ | 🔍 | 2008 | Wayback: 2008 cumulative log PDF (+~17); log itself begins 2008-02 — older likely nonexistent |
| IL | 3,742 | 1999–2026 | ✅ | ✅ | ✅ | 1999 | Complete (XLSX era + PDF era + Jan-2019 hand transcription) |
| IN | 1,012 | 2008–2026 | ✅ | ✅ | 🔨 | 2000 | Wayback: DWD year pages 2000–2007 **built** (+496 verified offline; prod run pending); gaps Jan–Oct 2000, Nov–Dec 2004, Oct–Dec 2007 |
| KS | 549 | 1999–2026 | ✅ | ✅ | ✅ | 1999 | Depth done; capped-year re-backfill Job pending (+344, PR #241) |
| KY | 427 | 2017–2026 | ✅ | 🔍 | 🔍 | 1998 | Wayback: kcc.ky.gov year-per-sheet XLSX workbooks, WARN 1998–2016 (+~780) |
| LA | 34 | 2025–2026 | 🔍 | 🔍 | ✉ | 2007 | Wayback: `WarnNotices{2007..2024}.pdf` all captured (+1.2–1.8k); pre-2007 never published |
| MA | 373 | 2021–2026 | 🔍 | ✉ | ✉ | 2019-07 | Wayback: FY2020 XLS + FY2021-through-Aug-2020 XLSX (+~215); **Sep 2020–Mar 2021 + pre-FY2020 → email** (eolwdpress@mass.gov) |
| MD | 1,333 | 2010–2026 | ✅ | ✅ | 🔍 | 2000 | Wayback: `warn{2000..2009}.shtml` — same page family the scraper already parses (+400–600). The old "no archive pre-2010" note was wrong |
| ME | 80 | 2012–2026 | ✅ | ⛔ | ⛔ | 2012 | JobLink source floor; capped-year Job pending (+12) |
| MI | 2,168 | 2000–2026 | ✅ | ✅ | ✅ | 2000 | milmi.org via Wayback — **done 2026-07-10** (+2,063, floor 2024-11→2000; parsers #247) |
| MN | 482 | 2012–2026 | ✅ | ⛔ | ⛔ | 2012 | Wayback backfill done 2026-07-10; 2012 = earliest filing in DEED annuals |
| MO | 322 | 2019–2026 | ✅ | 🔍 | ✉ | 2012-07 | Wayback: consolidated log PDF Jul-2012–Jul-2015 + PY2015–PY2018 pages (+550–650); pre-Jul-2012 → ✉ |
| MS | 139 | 2013–2026 | ✅ | 🔍 | ✉ | 2004 | Wayback: all 40 quarterlies PY2010–PY2019 + 2004–2006 era + the missing PY2023-Q4 (+400–800); **Jul 2007–Jun 2010 never archived** → ✉ |
| MT | 43 | 2015–2026 | ✅ | ✉ | ✉ | 2015 | Sweep: only a rolling 2-yr window existed before the 2015+ cumulative file; nothing older ever published (~4 notices/yr) |
| NC | 913 | 2014–2026 | ✅ | 🔍 | ✉ | 2012-10 | Wayback: `Warn-2013.pdf` full year + rolling `Warn.pdf` Q4-2012 (+~140); nothing pre-Oct-2012 (ncesc.com has zero WARN URLs) |
| ND | 54 | 2015–2026 | ✅ | ✉ | ✉ | 2015 | Sweep: agency's own file is "WARN Notices 2015 to present" — 2015 is the start of the published record |
| NE | 46 | 2023–2026 | 🔍 | 🔍 | ✉ | 2010 | **Live frozen endpoint** `dol.nebraska.gov/LayoffServices/WARNReportData/?year=Y` still serves 2010–2020 today; Wayback fills 2021–2022 (+~130) |
| NH | — | — | ✉ | ✉ | ✉ | — | Not published online; split-custody FOIA drafted |
| NJ | 2,282 | 2004–2026 | ✅ | ✅ | ✉ | 2004 | Workbook floor 2004; pre-2004 unprobed/unpublished → ✉ if pursued |
| NM | 114 | 2016–2026 | ✅ | ✉ | ✉ | 2016 | Sweep: 2016 PDF is the earliest list ever published (older pages are guides) |
| NV | 621 | 2017–2026 | ✅ | ✉ | ✉ | 2017 | Sweep: detr.state.nv.us/nvdetr.org 2001–2016 have guides only — no list pre-2017; Jun–Dec 2025 gap also ✉ |
| NY | 8,708 | 2006–2026 | ✅ | ✅ | ✉ | 2006 | Crosstab floor 2006; pre-2006 → FOIA backstop (draft exists) |
| OH | 3,172 | 1996–2026 | ✅ | ✅ | ✅ | 1996 | Complete; gap-year re-run 2007–2024 pending; 2025 unaccounted |
| OK | 198 | 2001–2026 | ✅ | ✅ | ✉ | 2001 | Portal reaches 2001; pre-2001 → FOIA drafted |
| OR | 100 | 2020–2026 | ✅ | 🔍 | ✉ | 2009 (partial) | 🔨 Socrata 2020-03+ (+~300); Wayback: June-2024 crawl of the HECC app captured pages 1–22 × ~12 sort orders while it still held full history → union recovers ~2009–2020-03 (+200–400); 1990s rows are date-less in the list view |
| PA | 3,321 | 2001–2026 | ✅ | ✅ | 🔍 | 1998-07 | Wayback: dli/li.state.pa.us month pages Jul-1998–Nov-2000 (+300–350); **Dec 2000 never captured**; same block format as the existing per-month parser |
| RI | 125 | 2009–2026 | ✅ | ✅ | ✉ | 2009 | Sweep: earliest listing ever archived is the 2009 table — nothing older exists |
| SC | 25 | 2026 | 🔍 | 🔍 | ✉ | 2009 | Wayback: scworks.org per-year PDFs 2009–2019 + **still-live unlinked** dew.sc.gov/scworks.org year PDFs 2020–2025 (+1.5–3k) |
| SD | 79 | 2007–2026 | ✅ | ✅ | 🔍 | 1997 | Wayback: frozen cumulative PDF Jul-1997–Dec-2005 (60 notices, 8,232 workers); gap 2006→Apr-2007 (≈0–5 notices) |
| TN | 90 | 2025–2026 | 🔨 | ✉ | ✉ | 2018 | 2018–2024 verified in Wayback (reports-page captures + 534 letter PDFs); pre-2018 ✉ (TPRA citizens-only caveat) |
| TX | 2,238 | 2020–2026 | ✅ | 🔍 | ✉ | 2004 | Wayback: `warn-act-listings-{Y}.xls(x)` 2004–2018 across two hosts (+2.5–3.5k) + Socrata `8w53-c4f6` 2019+ (fills our missing 2019, 153 rows); pre-2004 → ✉ |
| UT | 9 | 2026 | 🔍 | 🔍 | ✉ | 2009 | **The live page already holds 2009–2026** (~275 rows, per-year sections) — scraper fix, no external recovery; pre-2009 never published |
| VA | 1,116 | 2010–2026 | ✅ | ✅ | 🔍 | 1999-07 (partial) | Wayback: PY1999 XLS + PY2002 PDF + PY2003/PY2004 Excel-HTML sheets (+240–260); **PY2000–01 and Jul-2005–Dec-2009 unrecoverable** → ✉ |
| VT | 97 | 2003–2026 | ✅ | ✅ | ⛔ | 2003 | JobLink source floor; capped-year Job pending (+3) |
| WA | 1,480 | 2004–2026 | ✅ | ✅ | ⛔ | 2004 | Pagination reaches source floor 2004-01 |
| WI | 944 | 2016–2026 | ✅ | 🔍 | 🔍 | 1996 | Wayback: `worknet.wisconsin.gov` per-year PCML XLS logs **1996–2016**, every year captured (+1.5–2.5k) |
| WV | 51 | 2021–2026 | 🔍 | 🔍 | ✉ | 2011 | Wayback: cumulative "3-1-11 to 6-7-21" PDF bridges exactly to our floor (+~350); pre-2011 never captured |
| WY | — | — | 🚫 | 🚫 | 🚫 | — | No public data; confidential by state law |

## Sweep verdicts — recoverable (build queue detail)

Ranked by estimated rows. Every entry lists the pattern + one verified capture;
"latest capture per year" applies to all rolling/cumulative files.

### TX — Wayback 2004–2018 + Socrata 2019 (~2,500–3,500 rows)
`twc.texas.gov/files/news/warn-act-listings-{Y}.xls` (2004–2013) / `.xlsx`
(2014–2018); mirror host `www.twc.state.tx.us` fills gaps — **2017 exists only
there**, and post-year captures for 2016/2018 too. Schema identical to Socrata
`data.texas.gov/resource/8w53-c4f6.json` (re-verified: 2,368 rows,
2019-01-04→2026-06; 2019=153, 2020=1,209). Verified:
`web.archive.org/web/20161223010946id_/http://twc.texas.gov/files/news/warn-act-listings-2010.xls`
(166 rows, complete year). Caveats: rolling-within-year → take the latest
capture from whichever host has one dated after Jan 1 of the next year; `.xls`
needs xlrd. Pre-2004: nothing on either host → FOIA.

### FL — Wayback 1998–2019, essentially complete (~2,200–3,000 rows)
`floridajobs.org/react/warn.asp?year={Y}` (1998–2018, one cumulative HTML page
per year, case-insensitive REACT) + `reactwarn.floridajobs.org/WarnList/Records?year=2019`
(2 pages). Every year has a post-year 200 capture. Verified:
`web.archive.org/web/20160622214052id_/http://floridajobs.org/REACT/warn.asp?year=2005`
(113 rows). Caveats: company name + street address glued in one cell; layoff
date often a "x thru y" range; 1997 is a soft-404 — floor is 1998.
**Built 2026-07-10** (`parse_fl_warn_asp` + pinned replay captures in
`warn_v2/scrapers/states/fl.py`; `backfill-historical --state FL`): 2,863 rows
1998–2018 + 152 rows 2019 parsed offline, city/ZIP on every row. One hole: the
only 2012 capture (Nov 2019) is a header-only table — 0 rows for that year;
recovering 2012 would need a records request.

### SC — Wayback 2009–2019 + still-live unlinked PDFs 2020–2025 (~1,500–3,000 rows)
2009–2018: `scworks.org/docs/librariesprovider6/layoff-notification-reports/{Y}_layoff_notifications*.pdf`
(2016–2018 carry date suffixes); 2019: `2019-warn-report-(12-18-19).pdf`.
2020–2025: direct dew.sc.gov/scworks.org `sites/.../Documents/{Y} ... WARN Report ....pdf`
URLs still return 200 live though unlinked. Verified:
`web.archive.org/web/20200418074824id_/https://scworks.org/docs/librariesprovider6/layoff-notification-reports/2012_layoff_notifications.pdf?sfvrsn=d83615d7_4`
(13 pp, monthly sections, county+NAICS). Caveats: multiple snapshot editions
per year — take the latest-dated filename; 2019 edition dated 12-18-19 may miss
late Dec; text-layer PDFs with Unicode apostrophes. Pre-2009 (sces.org): nothing.

### WI — Wayback 1996–2016 XLS logs (~1,500–2,500 rows)
`worknet.wisconsin.gov/worknet_info/downloads/PCML/{Y}pcml_log.xls` — one file
per year, **every year 1996–2016 captured**. Verified:
`web.archive.org/web/20140904102400id_/http://worknet.wisconsin.gov/worknet_info/downloads/PCML/2010pcml_log.xls`
(~110–140 notices; NAICS, type, schedule). Caveats: records span multiple sheet
rows (address/contact lines under company); "(update)" amendment rows; may
include sub-threshold notices; xlrd needed; 2016 file (captured 2016-12-28)
doubles as a cross-check of our existing 2016.

### LA — Wayback 2007–2024 per-year PDFs (~1,200–1,800 rows)
`laworks.net/Downloads/WFD/WarnNotices{Y}.pdf` — **every year 2007–2026 has a
200 capture** (2021/2022 under `www2.laworks.net`). Verified:
`web.archive.org/web/20231011195653id_/https://www.laworks.net/Downloads/WFD/WarnNotices2020.pdf`
(10 pp, ~119 rows). Caveats: cumulative-within-year → latest capture per year;
company cells wrap with embedded multi-line addresses. Pre-2007: nothing.

### CT — Wayback 1998–2018, two eras (~900–1,400 rows) — 🔨 BUILT 2026-07-10

Built as `backfill-historical --state CT` (142 pinned captures in
`warn_v2/scrapers/states/ct.py`; 1,342 rows parsed offline across 1998–2018,
zero unparseable). Prod Job pending — ~150 sequential Wayback fetches at the
throttled pace, budget several hours.

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

### KY — Wayback 1998–2016 XLSX workbooks (~780 rows)
`kcc.ky.gov/documents/RapidResponse/WARNRecordByYear.xlsx` (capture
20150927133413; sheets "WARN 1998"…"WARN 2015", 741 rows) and
`kcc.ky.gov/Documents/WARN%20Report%202016.xlsx` (capture 20161222125836; adds
"WARN 2016", 38 rows). Both downloaded + parsed with openpyxl during the sweep.
Caveats: Dec-2016 capture may miss the final week (cross-check the live
SharePoint workbook's 2017 start); one `2106-07-06` typo date; low-count years
2002–2007 (4–12 rows/yr) are consistent across independent captures — real
reporting gaps, not truncation.

### IA — Wayback rolling-log snapshots, union covers 2005-07→2021 (+600–800)
~180 dated snapshots of a pruning cumulative log. Union these four:
`WARN_20150722.pdf` (2005-07→2015-07; capture 20150903000422),
`WARN_20171219.xlsx` (2011→2017-12), `WARN_20210105.xlsx` (2015-08→2021-01;
capture 20210107103313), `WARN_20230823.xlsx` (2018-09→2023, overlaps floor).
All under `iowaworkforcedevelopment.gov/sites/search.iowaworkforcedevelopment.gov/files/**`.
Caveats: heavy overlap → dedupe on (company, notice_date, layoff_date, city);
"Amendment" rows; XLSX has trailing empty columns / unsized sheets (openpyxl
read_only quirk); PDF-only for 2005–2011. Pre-2005: never published.

### MO — Wayback Jul-2012→2019 (~550–650 rows)
`jobs.mo.gov/sites/jobs/files/warn_log_jul2012_to_present_2015-07-01.pdf`
(capture 20151018024542; 17 pp, Jul 2012→Jul 2015) + `warn-log-py2015.pdf`
(20161223014721) + HTML PY pages: `jobs.mo.gov/es/warn2016` (20170409074237 —
Spanish-path capture of the English table), `content/missouri-warn-notices-py-2017`
(20171204110254), `-py-2018` (20190211194351). Caveats: **program years
(Jul–Jun)**; rolling YTD → latest capture per PY; pre-Jul-2012 → FOIA (ded.mo.gov
etc. all negative).

### MD — Wayback 2000–2009 year pages, existing parser family (+400–600)
`dllr.state.md.us/employment/warn{2000..2009}.shtml` all captured (2000–2007
at 20081205…, warn2008 at 20090421050910, warn2009 at 20110419154158); `.htm`
originals exist for 2000–2007 too. Verified: warn2000.shtml (77 notices,
KMART), warn2005.shtml (90). All captures post-date year end → complete years.
**Corrects the old "no archive pre-2010" note.** Extending the existing
`warn{year}.shtml` ingester back to 2000 should just work.

### IN — Wayback 2000–2007 DWD pages (+450–530)
`in.gov/dwd/workforce_stats/warn/{2000..2003}.html` (per-year tables) +
`workforce_stats/warn/notices.html` (rolling 2003–2005; Oct-2004 capture holds
Jan–Oct 2004) + `in.gov/dwd/employers/warn_notices.html` (accumulating
2005–2007; capture 20070921184150 holds all three years). Verified: 2000.html
capture 20030423222041 (FFI Corporation, SIC-coded rows). Gaps: Nov–Dec 2004,
Oct–Dec 2007. SIC pre-2005, NAICS after.

### MS — Wayback quarterlies: PY2010–PY2019 complete + 2004–2006 + PY2023-Q4 (+400–800)
All 40 quarters `mdes.ms.gov/media/{id}/py{Y}_q{n}_warn_{months}.pdf` have 200
captures (companion `_map.pdf`s too). **The missing PY2023-Q4 is recovered**:
`web.archive.org/web/20240816055525id_/https://mdes.ms.gov/media/440515/py2023-q4-warn-apr2024-jun2024.pdf`
(header mislabels it "PROGRAM YEAR 2024" — trust the month range). Older era:
`mdes.ms.gov/wps/PA_1_0_{6A,CH}/docs/Employer/Warn{Y}Q{n}.pdf` for 2004–2006
(filename year = calendar year, not PY — parse the in-PDF header). **Jul 2007–Jun
2010: CDX has only 404 captures → FOIA window.** Caveats: quarterlies mix
flagged "Non-WARN" Rapid Response events — filter; several filename mislabels
(`py2014_q2...jan2015_mar2015` is really Q3).

### WV — Wayback cumulative PDF 2011→2021 (+~350)
`workforcewv.org/images/files/PublicInfo/WV_WARN_Notices_3-1-11_to_6-7-21.pdf`
(capture 20211026131319) — one block per notice (company/address/county/dates/
count), bridges exactly to the 2021 floor. Older complete copies on
wvcommerce.org (`…to_8-12-14.pdf`, capture 20161221062445) as cross-checks.
Caveats: **the 6-7-21 capture is crawler-truncated at exactly 1 MiB —
pdfplumber fails but PyMuPDF/fitz repairs it and recovers all 137 pages**;
repeated-character-collapse in text extraction ("Mas Layof") — parse
defensively or OCR; pre-2011 never captured.

### PA — Wayback Jul-1998→Nov-2000 month pages (+300–350)
1998: `dli.state.pa.us/warn.html` (capture 19991104100952; Jul–Nov 1998
sections). 1999: `li.state.pa.us/dept/warn/{mon}99.html` all 12 months (some
only on the `li.` mirror). 2000: `{mon}00.html` Jan–Nov (**note `sept00`**;
dec00 was never captured — the one gap). Same employer/county/count/effective-date
block format as the existing per-month parser lineage. Verified: jan99.html
capture 20000709183110 (SANYO Reedsville 81).

### OR — Socrata 2020+ 🔨 + Wayback app captures ~2009–2020-03 (+500–700 combined)
Live HECC app now holds ZERO pre-2020 rows (purged; verified via the export
POST). A June-2024 crawl captured `ccwd.hecc.oregon.gov/Layoff/WARN?page=N&SortOrder=X`
pages 1–22 in ~12 sort variants while the app still held full history (~51
pages) — the union of sort variants recovers most dated rows back to ~2009.
Verified: page=10 capture 20201006143908 (2016–17 rows); page=22
SortOrder=EstDate_desc capture 20240621021957 (2009–10 rows). Caveats: ~280–300
oldest rows (1990s track numbers) have empty date cells (dates only in scanned
per-notice upload PDFs, also archived — OCR); a mid-2000s coverage gap is
possible where neither sort direction's 22 pages reach.

### UT — live page already cumulative 2009–2026 (+~265) — scraper fix
`jobs.utah.gov/employer/business/warnnotices.html` holds 18 per-year sections
(~275 rows) **today**; the scraper only ingests the current-year section.
Wayback corroborates (capture 20100413170506 of the `.asp` predecessor).
Caveats: sloppy old dates (`05/2009`, `01/07//09`); no county/NAICS; pre-2009
never published.

### VA — Wayback PY1999 + PY2002–PY2004 (+240–260, partial)
PY1999: `vec.state.va.us/docs/xls/warnnot99.xls` (capture 20030426225501; 59
notices, multi-row address blocks). PY2002: `vec.state.va.us/pdf/warnlog03.pdf`
(capture 20050510175855; 11 pp). PY2003/PY2004: Excel-HTML framesets whose
`_files/sheet001–005.htm` data sheets ARE captured
(`vec.virginia.gov/vecportal/employer/docs/xls/warnlog/warnnot04_files/sheet001.htm`
capture 20050914003027; `docs/xls/warnlog/WARNLOGPY04.htm` + sheets capture
20220324101727). **Unrecoverable: PY2000–01 (never captured), PY2005/PY2006
(framesets archived but data sheets missing), Jul-2006→Dec-2009** → FOIA.
Caveats: three formats; program years Jul–Jun; regional tabs duplicate the
statewide sheet — dedupe.

### MA — Wayback FY2020 + early FY2021 (+~215)
`mass.gov/doc/warn-report-for-fy-2020/download` (capture 20200828043125;
legacy .xls, 6 regional sheets, ~175 notices — Date Received / Company / City /
Layoff Date / # Affected) + `warn-report-for-week-ending-08-21-20/download`
(capture 20200828041524; FY-cumulative through Aug 21 2020, ~40 rows). **Zero
WARN docs captured between 2020-08-28 and 2021-11-30** → the Sep-2020→Mar-2021
tail and pre-FY2020 stay email-only (agency invites it).

### NC — Wayback 2013 + Q4-2012 (+~140)
`nccommerce.com/Portals/11/WARN/Warn-2013.pdf` (capture 20150327025758; full
calendar 2013, ~120–150 notices) + rolling `Warn.pdf` captures 2012-12
(Oct–Dec 2012). Caveats: 2013 PDF has letter-spaced city glyphs ("O x ford") —
de-space like the NC 2014 era; 2012 report lists County where 2013 lists City.
Pre-Oct-2012: nothing (ncesc.com has zero WARN URLs).

### NE — live frozen endpoint 2010–2020 + Wayback 2021–2022 (+~130)
`dol.nebraska.gov/LayoffServices/WARNReportData/?year={2010..2020}` **still
serves historical years live today** (HTML fragment: Date/Company/Jobs
Affected/City/Location; 2008/2009 and 2021+ return empty). 2021–2022 from
captures of the current rolling page (e.g. 20221126185419, 28 rows spanning
2020–2022). Wayback also holds the older `WARNReport?year=` pages 2013–2017 as
fallback. **Snapshot the live endpoint promptly — it's legacy/undocumented.**

### GA — 2022 partial via live entry pages (+70–100)
`tcsg.edu/warn-public-view/entry/{id}/` pages are still served live for 2022
notices (verified: entry 41068 = GA202200071, Dexter Axle, first separation
2023-01-09); 153 entry pages ≥41068 are also archived. Enumerate IDs or lift
the GravityView "As of 2023-01-01" view filter. **Dedupe by GA WARN ID — some
GA2022 entries may already be in the DB under a 2023 notice_date.** 2013–2021
(GDOL era): the session-based search app archived only empty forms → FOIA.

### SD — Wayback 1997–2005 cumulative PDF (+60)
`state.sd.us/dol/WIA/WIA%20Handbook/WARN%20Notices%20Received.pdf` (captures
20060618123843 / 20070114121809 — identical, frozen at PY-05): 60 notices,
8,232 workers, Jul-1997→Dec-2005 (Date/Company/Location/#Workers/Action).
Gap 2006-01→2007-04 (successor page starts 05/2007 = current floor; SD ~5
notices/yr, so ≈0–5 lost). One out-of-order row — parse by date, not position.

### ID — Wayback 2008 log (+~17)
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
| GA | 2013–2021 | GDOL session-app captures render empty search forms; CICS-era logs never crawled |
| CT | 2013 + most of 2009 | year page never captured (2013); only Aug/Sep monthlies exist (2009) |
| TX | pre-2004 | no earlier files on either TWC host (domain + /news/ sweeps) |
| MS | Jul 2007–Jun 2010 | quarterlies exist in CDX only as 404 captures from 2013 |
| VA | PY2000–01, Jul 2005–Dec 2009 | never captured / framesets without data sheets |
| MO | pre-Jul-2012 | ded.mo.gov, dolir.mo.gov, missourieconomy.org all negative |
| MA | Sep 2020–Mar 2021, pre-FY2020 | zero WARN doc captures 2020-08-28→2021-11-30; weekly docs never crawled |

## Build queue (ranked by estimated rows)

| # | Build | Recovers | Est. rows | Effort notes |
|---|---|---|---|---|
| 1 | TX Wayback XLS/XLSX + Socrata 2019 | 2004–2019 | ~2,700–3,700 | Schema = Socrata schema; two hosts; latest-capture logic |
| 2 | FL warn.asp HTML | 1998–2019 | ~2,200–3,000 | Name+address glued cell; date ranges |
| 3 | SC year PDFs (Wayback + live-unlinked) | 2009–2025 | ~1,500–3,000 | Multiple editions per year; live 2020–2025 files also fix current-era depth |
| 4 | WI PCML XLS logs | 1996–2016 | ~1,500–2,500 | Multi-row records; xlrd |
| 5 | LA WarnNotices PDFs | 2007–2024 | ~1,200–1,800 | Existing LA parser is layout-tolerant — may extend |
| 6 | CT monthly+yearly HTML | 1998–2018 | ~900–1,400 | 🔨 built (1,342 rows offline; Job pending); two eras; 2013/2009 holes |
| 7 | KY workbook captures | 1998–2016 | ~780 | Already-parsed format family (openpyxl) |
| 8 | IA snapshot union | 2005–2021 | ~600–800 | 4 files; heavy dedup — **built 2026-07-10** (bundled Mode 3b, 770 pre-2021 rows after dedup) |
| 9 | MO logs + PY pages | 2012-07–2019 | ~550–650 | PDF + HTML; program years |
| 10 | MD warn{Y}.shtml 2000–2009 | 2000–2009 | ~400–600 | **Easiest big win — existing parser family** |
| 11 | IN DWD pages | 2000–2007 | ~450–530 | 3 page generations |
| 12 | MS quarterlies (incl. PY2023-Q4) | 2004–Jun 2010 hole-adjacent + PY2010–19 | ~400–800 | Existing MS parser eras + header-vs-filename checks |
| 13 | WV cumulative PDF | 2011–2021 | ~350 | fitz repair for truncated capture |
| 14 | PA pre-2001 month pages | 1998-07–2000-11 | ~300–350 | Extends existing PA month parser |
| 15 | OR Socrata + app captures | 2009–2026 | ~500–700 | Socrata first (easy); capture-union harder |
| 16 | UT scraper fix | 2009–2026 | ~265 | Parse all year sections, not just current |
| 17 | VA three-format captures | PY1999, PY2002–04 | ~240–260 | XLS + PDF + Excel-HTML |
| 18 | MA FY2020 + wk-2020-08-21 | 2019-07–2020-08 | ~215 | Existing MA regional-sheet parser (FY22/23 layout) |
| 19 | NC 2013 + Q4-2012 | 2012-10–2013 | ~140 | Existing NC PDF dispatch + de-spacing |
| 20 | NE frozen endpoint + captures | 2010–2022 | ~130 | Trivial HTML; **snapshot soon** |
| 21 | GA 2022 entry pages | 2022 | ~70–100 | ID enumeration; dedupe by GA WARN ID |
| 22 | SD 1997–2005 PDF | 1997–2005 | ~60 | Single file |
| 23 | ID 2008 log | 2008 | ~17 | Single file |

Already queued before this sweep: JobLink re-backfill Jobs AZ/KS/DE/ME/VT
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
