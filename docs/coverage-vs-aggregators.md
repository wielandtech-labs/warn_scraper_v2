# Coverage cross-check vs. external aggregators — 2026-07-07

Comparison of warn.wielandtech.com coverage against the two big public WARN
aggregators, per the project policy in [historical-sources.md](historical-sources.md):
aggregators are a **completeness cross-check only**, never ingested. The goal is to
find coverage gaps (states / date ranges) that are not already handled by a drafted
public-records request in [foia/](foia/) or a known backfill route.

Refresh of the 2026-07-02 comparison, after the PA / OH / KY / LA / NV / CO
backfill wave landed. ⚠ Snapshot caveats: the **NY backfill is mid-run**
(w_homelab #623, ~4,293 Wayback detail pages) and the **IL date-cells
backfill Job is running** — both states' numbers will move again; MS / NJ /
MN parser PRs (#196 / #197 / #202) are open but their prod runs have not
happened yet.

## Method

- **Ours**: live API, `GET /api/stats/by-state` + `GET /api/stats/by-month?state=XX`
  per jurisdiction (fetched 2026-07-07). "Since" = earliest month with ≥1 notice.
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
| AR | — | 0 | — | — | — (futile) | parity — confidential by state law (re-verified 2026-07-07) |
| AZ | 2016-01 | 248 | 2008-01 | ~997 | pre-2016 | covered by draft — ⚠ probe AZ Job Connection (JobLink) date-range search before sending |
| CA | 2008-09 | 15,897 | 2009-01 | ~22,700 | — | **anomaly**: 2009–2013 hole (dense only 2014+); EDD-archive probe is hand-off item #9 |
| CO | 2015-01 | 811 | 2014-10 | ~851 | — | **resolved 2026-07-02** (scraper had been frozen on the 2021 sheet; backfilled 44 → 811) — near-parity now |
| CT | 2019-05 | 286 | 2014-01 | ~471 | pre-2019 | covered by draft |
| DC | 2005-05 | 141 | — | — | — | ours only (LD has no DC); interior holes 2006–14, 2018–19 uncorroborated |
| DE | 2016-01 | 42 | 2007-01 | ~79 | pre-2016 | covered by draft (⚠ JobLink probe first); **anomaly stands: zero rows in calendar 2024** |
| FL | 2020-01 | 2,334 | 1998-01 | ~5,600 | pre-2020 | covered by draft |
| GA | 2023-01 | 264 | 2023-01 | ~3,200 | pre-2023 | covered by draft; **count anomaly stands** — 12× at same floor, check row granularity |
| HI | 2019-01 | 418 | 2019-01 | ~448 | pre-2019 | parity + covered |
| IA | 2021-05 | 490 | 2005-07 | ~1,300 | pre-2021 | covered by draft |
| ID | 2009-01 | 194 | 2009-01 | ~195 | — | parity |
| IL | 2018-01 | 1,025 | 2020-01 | ~1,100 | — | ours deeper; 1999–2019 PDF era = hand-off item #1; date-cells backfill Job running 2026-07-07 |
| IN | 2008-07 | 1,012 | 2008-07 | ~990 | — | parity |
| KS | 1999-02 | 549 | 1998-08 | ~902 | — | minor: LD floor 6 months lower + higher count; JobLink floor is 1999 — note only |
| KY | 2017-01 | 427 | 1998-10 | ~1,200 | — | **anomaly resolved** — the 2026-07-02 workbook backfill is now fully visible (floor 2025→2017, 77→427); pre-2017 → request |
| LA | 2025-01 | 34 | 2007-01 | ~618 | pre-2025 | covered by draft; **2025 thinness resolved** (was 5 rows from 2025-12 only; now 24 across 2025 after the layout-tolerant parser) |
| MA | 2025-07 | 86 | 2019-07 | ~645 | pre-FY2022 | FY22–FY25 xlsx = hand-off item #5 (unclaimed); older covered by draft |
| MD | 2010-01 | 1,333 | 2000-01 | ~2,000 | pre-2010 | covered by draft |
| ME | 2012-01 | 80 | 2012-01 | ~90 | — | parity |
| MI | 2024-11 | 105 | 2000-01 | ~2,200 | pre-2024-11 | covered by draft (extended through Oct 2024 — site pruned pre-2025) |
| MN | 2023-01 | 75 | 2018-01 | ~1,300 | — | multi-era parser done 2026-07-07 (PR #202; reaches month sections back to **2014**, deeper than LD); prod run pending after NY — incl. purge of the glued-employer 2023+ live rows |
| MO | 2019-01 | 322 | 2006-07 | ~975 | pre-2019 | covered by draft |
| MS | 2013-02 | 124 | 2010-07 | ~763 | pre-PY2020 | covered by draft (2013 row is a stray; 2014–19 hole inside draft scope); straggler-quarterly parser fixed 2026-07-07 (PR #196, ~15 rows pending run) |
| MT | 2015-01 | 43 | 2015-01 | ~44 | — | parity |
| NC | 2026-01 | 49 | 2012-01 | ~1,400 | — | backfill-instead: archive PDFs to 2014 = hand-off item #2; 2012–13 sliver → fold into any later request |
| ND | 2015-07 | 54 | 2015-07 | ~53 | pre-2015 | parity + covered |
| NE | 2023-03 | 46 | 2014-01 | ~865 | pre-2023 | covered by draft |
| NH | — | 0 | 2009-09 | ~114 | all years | covered by draft (LD proves records exist); no public source re-verified 2026-07-07 |
| NJ | 2026-01 | 79 | 2004-01 | ~2,300 | — | cumulative-workbook parser done 2026-07-07 (PR #197; floor lands exactly on LD's 2004-01, 2,349 rows); prod run pending |
| NM | 2016-01 | 114 | 2016-01 | ~116 | pre-2016 | parity + covered |
| NV | 2017-01 | 601 | 2017-01 | ~669 | pre-2017 | **anomaly resolved** — 2026-07-02 backfill visible (11→601, floor 2017-01 = LD); residual: 2021 scanned-image year (hand-off item #7) + Jun–Dec 2025 (in request) |
| NY | 2003-03 | 674 | 2006-07 | ~7,100 | — | **backfill mid-run** (w_homelab #623; floor already 2025→2003-03, 217→674 while running) — re-compare after the run + audit; reserved |
| OH | 1996-07 | 3,172 | 1996-07 | ~3,300 | — | **near-parity** — 1996–2024 era backfill + gap-year re-run landed (55→3,172, floors identical); 2025 still unaccounted anywhere |
| OK | 2001-03 | 198 | 1999-11 | ~525 | all years | **resolved: live since 2026-07-06** — the Salesforce portal serves full history (floor 2001-03). LD is 16 months deeper + ~2.6× count → keep the drafted request for pre-2001 / completeness cross-check |
| OR | 2020-04 | 100 | 2010-09 | ~659 | pre-2020 | covered by draft |
| PA | 2001-01 | 3,321 | 2001-01 | ~3,800 | — | **done 2026-07-07** — Wayback era ingested (390→3,321), floors identical; count gap = LD granularity + our superseded-row collapse |
| PR | — | — | 2019-03 | ~20 | — | not a tracked jurisdiction — scope report = hand-off item #12 |
| RI | 2009-03 | 125 | 2009-01 | ~125 | — | parity (2-month sliver) |
| SC | 2026-01 | 25 | 2012-01 | ~781 | pre-2026 | covered by draft |
| SD | 2007-05 | 79 | 2007-05 | ~79 | — | parity |
| TN | 2025-01 | 90 | 2012-01 | ~1,100 | pre-2021 (asks through 2024) | covered by draft; 2021–2024 also scrapeable from the dept's reports page; ⚠ TPRA residency caveat |
| TX | 2020-01 | 2,238 | 2004-01 | ~5,500 | pre-2020 | covered by draft |
| UT | 2026-01 | 9 | 2009-01 | ~275 | pre-2026 | covered by draft |
| VA | 2010-07 | 1,116 | 2010-07 | ~1,100 | — | parity |
| VT | 2003-07 | 97 | 2003-07 | ~99 | — | parity |
| WA | 2026-03 | 31 | 2004-01 | ~1,500 | — | backfill first: `__VIEWSTATE` pagination = hand-off item #6, then reassess depth |
| WI | 2016-01 | 944 | 2016-01 | ~981 | — | parity |
| WV | 2021-05 | 51 | 2015-10 | ~274 | pre-2021 | covered by draft |
| WY | — | 0 | — | — | — (futile) | parity — no public data (re-verified 2026-07-07) |

Small calendar slivers between a draft's explicit end date and our DB floor
(CT 2019-01..04, IA 2021-01..04, NE 2023-01..02, WV 2021-01..04) are already
handled by the drafts' standing "a complete export through the present is equally
welcome" clause.

## Changes since the 2026-07-02 comparison

- **Resolved anomalies**: CO (scraper unfrozen, 44→811), KY (workbook backfill
  visible, 77→427, floor 2017), NV (11→601, floor 2017), LA 2025 thinness
  (5→34, spread across the year), OK (was 0 — live scraper + full portal
  history since 2026-07-06, floor 2001-03).
- **Big floor moves from the backfill wave**: PA 2024→2001 (+2,931),
  OH 2026→1996 (+3,117), NY 2025→2003 **and still ingesting** (mid-run).
- **Parsers landed, prod runs pending**: NJ cumulative workbook (PR #197,
  floor will hit LD's 2004-01 exactly), MN multi-era (PR #202, floor will
  pass LD's 2018 down to 2014), MS straggler quarterlies (PR #196).
- FOIA drafts from 2026-07-02 (AZ, DE, MD, NH, OK, TN, TX) remain **unsent**;
  OK's is now cross-check/pre-2001 only.

## Not FOIA — flagged for separate investigation

1. **CA 2009–2013 hole** — dense coverage only from 2014; LD floor 2009-01 and
   ~6.8K more rows overall. Check EDD's published report archive before a CPRA
   request (hand-off item #9).
2. **GA count discrepancy** — same 2023-01 floor but 264 vs ~3,200. Likely
   row-granularity (per-location?) but could be under-scraping.
3. **DE 2024 empty** — still zero rows in calendar 2024 inside an otherwise
   continuous range (re-checked 2026-07-07).
4. **PR** — layoffdata covers Puerto Rico (since 2019); we have no PR
   jurisdiction (hand-off item #12).

## Refresh procedure

Re-run the comparison by pulling `/api/stats/by-state` + per-state
`/api/stats/by-month` and re-parsing `layoffdata.com/data/` (server-rendered; each
state card carries "since Mmm YYYY" + counts). warntracker.com has no public
per-state floors to compare against.
