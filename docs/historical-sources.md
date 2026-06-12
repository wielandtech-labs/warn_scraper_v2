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

## Tier 1 — published archive: ingest with code

| State | DB floor | Source / route | Available back to | Backfill route |
|-------|----------|----------------|-------------------|----------------|
| KS | 2026 | `kansasworks.com/search/warn_lookups?q[notice_on_gteq]=YYYY-01-01` (JobLink date-range search) | **1999** | JobLink `fetch(year=)` registry entry |
| ME | 2026 | `joblink.maine.gov/search/warn_lookups` (JobLink) | **2012** | JobLink registry entry |
| VT | 2026 | `vermontjoblink.com/search/warn_lookups` (JobLink) | **2003** | JobLink registry entry |
| FL | 2026 | `reactwarn.floridajobs.org/WarnList/Records?year=Y` — paginated (e.g. 2020 = 1,337 records) | **2020** (older years return 0 rows) | year loop + page-following; pre-2020 → FOIA |
| TX | 2026 | `warn-act-listings-{year}-twc.xlsx` (2022+ era) / `twc.texas.gov/files/news/warn-act-listings-{year}.xlsx` (≤2021 era); Socrata `data.texas.gov/dataset/8w53-c4f6` as fallback | ~2004 (per era files) | year loop, both URL eras |
| NC | 2026 | archive hub `commerce.nc.gov/...warn-summary-report-archives` → `warn-report-{year}/open` | **2014** | year loop |
| NJ | 2026 | cumulative `nj.gov/labor/assets/PDFs/WARN/WARN_Notice_Archive.xlsx` (year range unknown — parse first); per-year PDF only 2023 | TBD (parse xlsx) | ingest cumulative xlsx |
| NM | 2025 | per-year PDFs on `dws.nm.gov/Rapid-Response` (filenames vary 2016–2018) | **2016** | year loop w/ link discovery; pre-2016 → request |
| HI | 2026 | `labor.hawaii.gov/wdc/{year}-warn-notices/`; hub `real-time-warn-updates` lists 2019–2026 | **2019** | year loop; pre-2019 → UIPA request |
| KY | 2025 | `kyworks.ky.gov/Services/Documents/Prior%20Year%20Warn%20Notices.xlsx` (confirmed 200, range unknown — parse first) | TBD (parse xlsx) | ingest prior-year xlsx |
| MO | 2019 | `jobs.mo.gov/warn/{year}` (Playwright) | 2019 | year loop; pre-2019 → request |
| OH | 2026 | JFS per-year pages | **1996** | new per-year fetch/parse |
| PA | 2024 | pa.gov AEM accordion | **2001** | new parse; strict dedup (286 superseded rows already) |
| IL | 2025 | `illinoisworknet.com/LayoffRecovery/` archive — monthly XLSX 2020+, PDFs 2002–2019 | **2002** (PDF era), 1999 partial | `discover_urls` mode + `parse_il_pdf` |
| NY | 2025 | `dol.ny.gov/warn-dashboard` + per-year PDFs (check whether dashboard CSV is already all-years) | ~2010s | investigate, then ingest |
| MD | 2026 | `labor.maryland.gov/employment/warn.shtml` per-year pages | **2010** | year loop |
| WI | 2020 | Google Sheets per-year tabs | **2016** | per-tab ingest |
| MN | 2023 | DEED `mn.gov/deed/...warn-archive` | **2018** | archive page ingest (vs existing Wayback CDX) |
| MS | 2025 | MDES quarterly PDFs — `_discover_pdf_urls()` already returns all; scraper ingests only `[0]` | **PY2020** | ingest the full discovered list; older → request |
| MA | 2025 | mass.gov WARN page publishes **FY22–FY25 XLSX reports** | FY2022 | ingest FY xlsx; pre-FY22 → email (invited) |
| WA | 2026 | `fortress.wa.gov/esd/file/warn/Public/SearchWARN.aspx` — ASP.NET `__VIEWSTATE` pagination the scraper doesn't follow (10+ pages; depth unknown) | TBD | implement postback paging, then reassess |
| OR | 2020 | HECC site states it retains only **six years** of WARN records; `data.oregon.gov` Socrata dataset `ijbz-jpx8` exists (content unverified) | ~mid-2020 | check Socrata dataset; pre-2020 → inquiry |

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
  reports of 2024 existing — the agency appears to prune old files). Pre-2025 →
  records request.

## Tier 3 — public-records request required

Email/portal drafts live in [docs/foia/](foia/) — one file per state, tracker in
[foia/README.md](foia/README.md). Recipients verified on agency sites 2026-06-12
except where flagged.

| State | Years sought | Recipient | Method | Statute |
|-------|--------------|-----------|--------|---------|
| CT | pre-2019 | CT DOL Records Center | **GovQA portal** (`dolct.govqa.us`) | CT FOIA |
| FL | pre-2020 | PRRequest@commerce.fl.gov | email (JustFOIA portal alt.) | Ch. 119, F.S. |
| GA | pre-2023 | GDOL via `dol.georgia.gov/email-us` | **web form** (no records email published) | O.C.G.A. §50-18-70 |
| HI | pre-2019 | dlir.director@hawaii.gov | email | UIPA (HRS ch. 92F) |
| IA | pre-2021 | RecordsRequest@IWD.Iowa.gov | email | Iowa Code ch. 22 |
| LA | pre-2025 | HiRE@lwc.la.gov | email (online system alt.) | La. R.S. 44:1 et seq. |
| MA | pre-FY2022 | eolwdpress@mass.gov | email — **agency invites this** | M.G.L. c. 66 |
| MI | pre-2024 | leo-warn@michigan.gov | email | MI FOIA (Act 442 of 1976) |
| MO | pre-2019 | meghan.maskeryluecke@dhewd.mo.gov (General Counsel), cc info@dhewd.mo.gov | email | Sunshine Law (§610 RSMo) |
| MS | pre-PY2020 | communications@mdes.ms.gov | email | Miss. Code §25-61 |
| ND | pre-2015 | ⚠ no records email published — call (701) 328-2825 for address | phone→email | NDCC ch. 44-04 |
| NE | pre-2023 | NDOL.RapidResponse@nebraska.gov | email | Neb. Rev. Stat. §84-712 |
| NM | pre-2016 | tammy.gallegos-burke@dws.nm.gov (named on agency site for older records) | email | IPRA (NMSA ch. 14, art. 2) |
| NV | pre-2024 | detrmedia@detr.nv.gov, cc rapidresponse@detr.nv.gov | email + **required request form** | NRS 239 |
| OR | pre-2020 (existence inquiry) | HECC Office of Workforce Investments | email | ORS 192 |
| SC | pre-2026 | FOIA@dew.sc.gov | email | S.C. Code §30-4-10 et seq. |
| UT | pre-2026 | infodisclosure@utah.gov (GRAMA office, *not* the rapid-response box) | email (openrecords.utah.gov alt.) | GRAMA |
| WV | pre-2021 | ⚠ wfwvbsr@wv.gov (general box; no FOIA email published — ask to route) | email | W. Va. Code §29B-1 |

## Blocked — no request drafted

AR (WARN data confidential by state law — a request would be denied), NH (no
public listing; Akamai-blocked), OK (Salesforce auth wall), TN (scraper built,
tn.gov blocks container IPs), WY (no public data). Re-verify periodically per
STATE_AUDIT.md.
