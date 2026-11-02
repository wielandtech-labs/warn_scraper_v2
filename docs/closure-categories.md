# Closure vs. layoff: which sources publish it

`closure_type` is the source's own text. `closure_category` buckets it as
`Closure`, `Layoff` or `Non-WARN` (`warn_v2/closure.py`), and is NULL when the
source has no type or names both. Both columns are first-non-null-wins, so a
parser or normalizer fix reaches only the rows a scraper re-reads. For
everything else, run `warn-v2 recategorize-closures` (it works from the stored
`closure_type`) or re-run `backfill-historical` (the category fills in on the
re-upsert).

A daily scrape doesn't always re-read. Scrapers that fetch through
`conditional_get` record `not_modified` and skip the parse while the source
file is unchanged, so a fix doesn't reach them until the state publishes a new
file. RI was stuck this way after #424, and a one-off Job re-read it
unconditionally (w_homelab #1302). Check the state's recent `/api/scraper-runs`
before you count on the daily run.

## Audit 2026-10-31

Prod had 94,328 notices, 54% of them categorized. Every state's live parser
was checked against its source, and prod values were sampled per year.

**Sources publish the type, and we keep it** (90%+ categorized): AL, DC, GA,
IL, IN, KY, MI, MO, MS, NV, OK, OR, PA, SC, VA, WI, plus WV live, CO and IA.
CO, IA, AK and VA also carry free-text reasons ("Loss of contract",
"Amendment") that stay NULL on purpose.

**Fixed in this audit:**

| State | What was wrong | Repair for stored rows |
|---|---|---|
| WA | Read "Type of Layoff" (Permanent/Temporary), not "Closure Layoff" | the daily scrape re-reads the full list (done 2026-11-01) |
| NC | Read "Type of layoff or closure" (Permanent/Temporary), not "WARN notice type"; 2020-21 PDFs wrap the header | `backfill-historical --state NC` |
| CA | FY report PDFs head the column "Layoff/Closure Type"; 2020-25 rows from the retired `WARN_Report.xlsx` predate #118 | re-ingest the FY PDFs (`_discover_archive_urls`) |
| RI | "Closing: No" was left NULL instead of Layoff | a one-off unconditional re-read (the daily scrape returns `not_modified`) |
| TN | 2013 - Aug 2014 archive rows carry WARN numbers, not CL/LO | `backfill-historical --state TN` (cross-fills from the warnnotices page) |
| MD | 2010-22 rows store the raw codes `1`/`2` (ingested before the code map) | `recategorize-closures` |
| IL, CO, MO | "Shutdown", "Red in Force", "Downsize", "Furlough", "Lay-Off" not normalized | `recategorize-closures` |

**Sources with no type to read:**

- No type column: TX, FL, NJ, LA, ID, MT, ND, NM, UT, HI, MA, SD (live), NE
  (live), MN, CT (2019+, the document library lists file names only), WV
  (link list).
- JobLink (KS, AZ, DE, ME, VT): the results table's type column only ever says
  "WARN", and the detail page has no type.
- Some years only: OH 2021-24 (the year CSVs lack the Layoff/Closure column
  the live CSV has), NY before 2022 (blank in DOL's own crosstab), CA 2000-03
  (simple HTML pages), CT 1998-2004, TN 2015-16 and some of 2014, and MN's
  2014-19 reports ("Layoff Status" holds service levels, not a type). OH's
  1996-2020 PDFs are unchecked.

For these, the only remaining source is the notice letters themselves, which
is how `enrich_ga` gets GA's type.
