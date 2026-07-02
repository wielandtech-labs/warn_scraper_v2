# Coverage cross-check vs. external aggregators — 2026-07-02

Comparison of warn.wielandtech.com coverage against the two big public WARN
aggregators, per the project policy in [historical-sources.md](historical-sources.md):
aggregators are a **completeness cross-check only**, never ingested. The goal is to
find coverage gaps (states / date ranges) that are not already handled by a drafted
public-records request in [foia/](foia/) or a known backfill route.

## Method

- **Ours**: live API, `GET /api/stats/by-state` + `GET /api/stats/by-month?state=XX`
  per jurisdiction (fetched 2026-07-02). "Since" = earliest month with ≥1 notice.
- **layoffdata.com** (a.k.a. WARN Database): the public `/data/` page, which lists
  per-state notice counts, worker totals, and a "since Mmm YYYY" coverage floor for
  49 states + PR (no AR, WY — unavailable by state law; no DC card). Parsed from the
  server-rendered HTML; counts are their rounded display values (e.g. "1.0K").
- **warntracker.com**: claims all 50 states + DC back to 1988, but per-state
  historical extent is **not publicly exposed** — the free page only serves a 2026
  sample via an internal endpoint; everything else is paywalled. It contributes no
  per-state floors to this comparison and is noted here for completeness.
- Counts are methodology-dependent (row granularity, dedup, superseding) — year
  floors are the primary signal; counts only flag order-of-magnitude anomalies.

## Per-state comparison

"LD" = layoffdata.com. Notice counts: ours exact, LD approximate (rounded display).

| ST | Ours since | Ours n | LD since | LD n | Existing draft | Verdict |
|----|-----------|--------|----------|------|----------------|---------|
| AK | 2006-02 | 64 | 2006-02 | 63 | — | parity (interior gaps 2009/11/14 confirmed real) |
| AL | 1998-07 | 1,035 | 1998-07 | ~1,000 | — | parity |
| AR | — | 0 | — | — | — (futile) | parity — confidential by state law |
| AZ | 2016-01 | 249 | 2008-01 | ~996 | — | **new FOIA candidate: pre-2016** — but probe AZ Job Connection (JobLink) date-range search first, per the KS/ME/VT precedent |
| CA | 2008-09 | 15,869 | 2009-01 | ~22,700 | — | **anomaly**: 2009–2013 hole (1 stray 2008 row, dense only 2014+); investigate EDD archive, then CPRA |
| CO | 1957-07 | 44 | 2014-10 | ~850 | — | **anomaly**: scraper stale — latest row 2021-12, 44 rows total vs LD 850 since 2014 |
| CT | 2019-05 | 286 | 2014-01 | ~470 | pre-2019 | covered by draft |
| DC | 2005-05 | 141 | — | — | — | ours only (LD has no DC); interior holes 2006–14, 2018–19 uncorroborated |
| DE | 2016-01 | 42 | 2007-01 | ~78 | — | **new FOIA candidate: pre-2016** — but probe Delaware JobLink date-range search first (also: zero 2024 rows — verify against source) |
| FL | 2020-01 | 2,333 | 1998-01 | ~5,600 | pre-2020 | covered by draft (LD confirms records to 1998) |
| GA | 2023-01 | 264 | 2023-01 | ~3,200 | pre-2023 | covered by draft; **count anomaly** — 12× at same floor, check row granularity |
| HI | 2019-01 | 418 | 2019-01 | ~448 | pre-2019 | parity + covered |
| IA | 2021-05 | 490 | 2005-07 | ~1,300 | pre-2021 | covered by draft |
| ID | 2009-01 | 194 | 2009-01 | ~194 | — | parity |
| IL | 2018-01 | 1,025 | 2020-01 | ~1,100 | — | ours deeper; 1999–2017 PDF era = known deferred backfill |
| IN | 2008-07 | 1,012 | 2008-07 | ~988 | — | parity |
| KS | 1999-02 | 549 | 1998-08 | ~902 | — | minor: LD floor 6 months lower + higher count; JobLink floor is 1999 — note only |
| KY | 2025-01 | 77 | 1998-10 | ~1,200 | — | backfill first (prior-year xlsx), then request; **anomaly**: the +54 rows from the 2021+ backfill are absent from the live API |
| LA | 2025-12 | 5 | 2007-01 | ~612 | pre-2025 | covered by draft; **anomaly**: only 5 rows from 2025-12 — WarnNotices2025.pdf should cover all of 2025 |
| MA | 2025-07 | 86 | 2019-07 | ~645 | pre-FY2022 | FY22–FY25 xlsx = pending backfill; older covered by draft |
| MD | 2010-01 | 1,331 | 2000-01 | ~1,900 | — | **new FOIA candidate: pre-2010** (archive pages only verified to 2010) |
| ME | 2012-01 | 79 | 2012-01 | ~90 | — | parity |
| MI | 2024-11 | 104 | 2000-01 | ~2,200 | pre-2024 | covered by draft — **extended to Oct 2024** (site pruned all pre-2025; Jan–Oct 2024 was outside the old scope) |
| MN | 2023-01 | 75 | 2018-01 | ~1,300 | — | backfill-instead: Wave 2B multi-era parser (LD floor 2018 matches the annual-summary depth) |
| MO | 2019-01 | 322 | 2006-07 | ~974 | pre-2019 | covered by draft |
| MS | 2013-02 | 124 | 2010-07 | ~757 | pre-PY2020 | covered by draft (2013 row is a stray; 2014–19 hole inside draft scope) |
| MT | 2015-01 | 43 | 2015-01 | ~44 | — | parity |
| NC | 2026-01 | 47 | 2012-01 | ~1,400 | — | backfill-instead: archive PDFs to 2014 (Wave 2); 2012–13 sliver → fold into any later request |
| ND | 2015-07 | 54 | 2015-07 | ~53 | pre-2015 | parity + covered |
| NE | 2023-03 | 45 | 2014-01 | ~863 | pre-2023 | covered by draft |
| NH | — | 0 | 2009-09 | ~114 | — (was "futile") | **new FOIA candidate: all years** — LD proves records exist despite no public listing |
| NJ | 2026-01 | 73 | 2004-01 | ~2,300 | — | backfill-instead: cumulative WARN_Notice_Archive.xlsx (range TBD; LD suggests to 2004) |
| NM | 2016-01 | 114 | 2016-01 | ~116 | pre-2016 | parity + covered |
| NV | 2025-01 | 11 | 2017-01 | ~667 | pre-2024 | backfill-instead 2017–2024: detr.nv.gov publishes per-year archives 2017+ (re-checked 2026-07-02) — draft **narrowed to pre-2017**; scraper only captures 2025+ (**anomaly**) |
| NY | 2025-01 | 217 | 2006-07 | ~7,100 | — | largest open gap; Wave 2C decision pending (per-year PDFs vs FOIA) — LD floor 2006-07 |
| OH | 2026-01 | 55 | 1996-07 | ~3,300 | — | backfill-instead: 1996–2024 era-dispatch backfill merged (#55), prod run pending |
| OK | — | 0 | 1999-11 | ~525 | — (was "futile") | **new FOIA candidate: all years** — data exists behind the Salesforce wall; LD floor Nov 1999 |
| OR | 2020-04 | 100 | 2010-09 | ~657 | pre-2020 | covered by draft (LD corroborates pre-2020 records exist beyond HECC's 6-year retention) |
| PA | 2024-09 | 390 | 2001-01 | ~3,800 | — | backfill-instead: Wayback era parse to 2001 (Wave 2B) |
| PR | — | — | 2019-03 | ~20 | — | not a tracked jurisdiction — possible expansion (new scraper or request) |
| RI | 2009-03 | 125 | 2009-01 | ~125 | — | parity (2-month sliver) |
| SC | 2026-01 | 25 | 2012-01 | ~780 | pre-2026 | covered by draft |
| SD | 2007-05 | 79 | 2007-05 | ~78 | — | parity |
| TN | 2025-01 | 90 | 2012-01 | ~1,100 | — (was "futile") | **new FOIA candidate: pre-2021** (draft asks through 2024 as prune insurance) — the dept's reports page publicly lists 2021–2026, so 2021–2024 is also a backfill candidate; ⚠ TPRA residency caveat, see draft |
| TX | 2020-01 | 2,238 | 2004-01 | ~5,500 | — | **new FOIA candidate: pre-2020** — route already identified (warn.list@twc.texas.gov), never drafted |
| UT | 2026-01 | 9 | 2009-01 | ~275 | pre-2026 | covered by draft |
| VA | 2010-07 | 1,113 | 2010-07 | ~1,100 | — | parity |
| VT | 2003-07 | 97 | 2003-07 | ~99 | — | parity |
| WA | 2026-03 | 27 | 2004-01 | ~1,500 | — | backfill first: fix `__VIEWSTATE` pagination, then reassess depth (LD floor 2004) |
| WI | 2016-01 | 943 | 2016-01 | ~980 | — | parity |
| WV | 2021-05 | 51 | 2015-10 | ~273 | pre-2021 | covered by draft |
| WY | — | 0 | — | — | — (futile) | parity — no public data |

Small calendar slivers between a draft's explicit end date and our DB floor
(CT 2019-01..04, IA 2021-01..04, NE 2023-01..02, WV 2021-01..04) are already
handled by the drafts' standing "a complete export through the present is equally
welcome" clause; only MI and NV needed their explicit windows widened (full missing
calendar year).

## Actions taken (this PR)

New drafts added to [foia/](foia/), tracker rows in foia/README.md:

- **AZ** — pre-2016 (LD floor 2008-01) — ⚠ probe the AZ Job Connection JobLink
  date-range search first; KS/ME/VT proved JobLink archives reach far below the
  visible floor
- **DE** — pre-2016 (LD floor 2007-01) — ⚠ same JobLink probe first
  (joblink.delaware.gov)
- **MD** — pre-2010 (LD floor 2000-01)
- **NH** — all years (LD floor 2009-09; previously assumed futile)
- **OK** — all years (LD floor 1999-11; previously assumed futile)
- **TN** — pre-2021 need, draft asks through 2024 (LD floor 2012-01; previously
  assumed futile; 2021–2024 also scrapeable from the dept's reports page)
- **TX** — pre-2020 (LD floor 2004-01; recipient was already identified in
  historical-sources.md)

Adjusted existing drafts: **MI** extended through Oct 2024 (site pruned pre-2025);
**NV** narrowed to pre-2017 — detr.nv.gov turns out to publish per-year archives
back to 2017, so 2017–2024 is a scraper backfill, not a records request.

## Not FOIA — flagged for separate investigation

1. **CO scraper stale/broken** — no rows since 2021-12 and only 44 total, vs LD's
   ~850 since 2014. Highest-priority anomaly: this is live-coverage loss, not history.
2. **CA 2009–2013 hole** — dense coverage only from 2014; LD floor 2009-01 and
   ~6.8K more rows overall. Check EDD's published report archive before a CPRA request.
3. **GA count discrepancy** — same 2023-01 floor but 264 vs ~3,200. Likely
   row-granularity (per-location?) but could be under-scraping.
4. **KY backfill rows missing** — historical-sources records +54 rows (2021+)
   backfilled 2026-06-12, but the API shows nothing before 2025-01.
5. **LA 2025 thin** — 5 rows starting 2025-12; the cumulative WarnNotices2025.pdf
   should have produced Jan–Dec 2025.
6. **DE 2024 empty** — zero rows in calendar 2024 inside an otherwise continuous range.
7. **NV scraper shallow** — detr.nv.gov lists per-year notices 2017–2026, but the
   DB has only 11 rows from 2025-01; the scraper apparently reads the current list
   only. Backfill 2017–2024 from the site's per-year archives.
8. **PR** — layoffdata covers Puerto Rico (since 2019); we have no PR jurisdiction.

## Refresh procedure

Re-run the comparison by pulling `/api/stats/by-state` + per-state
`/api/stats/by-month` and re-parsing `layoffdata.com/data/` (server-rendered; each
state card carries "since Mmm YYYY" + counts). warntracker.com has no public
per-state floors to compare against.
