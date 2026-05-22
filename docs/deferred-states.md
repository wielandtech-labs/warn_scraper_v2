# Deferred state scrapers

States from the V1 active set whose live sources have drifted in ways that
need investigation (URL moved, new bot protection, page rebuilt with
JS-rendered content). Listed here so the Phase-4-style enrichment / heal
agent has a queue to work through later.

Last checked: 2026-05-22.

| State | V1 URL | What changed | Next step |
|-------|--------|--------------|-----------|
| **CT** | `ctdol.state.ct.us/progsupt/bussrvce/warnreports/warn{year}.htm` | URL 404s; site migrated to `portal.ct.gov`. WARN notices now live in a JS-rendered document library at `dolpublicdocumentlibrary.ct.gov/CsblrCategory?prefix=%2Frapid_response%2Fwarn_documents`. | Inspect the document library's network calls; likely a JSON listing of per-notice PDFs. May require Playwright for the initial listing fetch. |
| **GA** | `https://www.dol.state.ga.us/public/es/warn/searchwarns` | 404 on old URL; new `dol.georgia.gov` site has no WARN section — no public listing found on the employer resources or documents pages. | Monitor `dol.georgia.gov` for a WARN notices section to appear; may require a direct inquiry to GA DOL. |
| **MI** | `https://milmi.org/warn` | URL itself returns 200 from `michigan.gov/leo/...` but the new template renders an empty `facet-warn---counties` component; the data loads via JS / a deeper API. | Probe the page in a real browser, capture the XHR; update scraper to hit the JSON endpoint directly. |
| **NJ JSP** | `lwd.state.nj.us/WorkForceDirectory/warn.jsp?...` | Behind Incapsula (403 + JS challenge). V2 falls back to the still-live yearly PDF at `nj.gov/labor/assets/PDFs/WARN/{year}_WARN_Notice_Archive.pdf` (see `warn_v2/scrapers/states/nj.py`). | If the PDF ever stops being published, scraping the JSP page would need a real browser (Playwright) — not worth it. |
| **OK JobLink** | `okjobmatch.com/search/warn_lookups?...` | Whole `okjobmatch.com` host returns 404 (IIS). Other JobLink-platform states (AZ/DE/KS/ME/VT) still work. | Check whether Oklahoma migrated to a different `*jobmatch.com` subdomain. |
| **OH** | `jfs.ohio.gov/warn/current.stm` | Page now renders via IBM WebSphere Portal with no static table content; data is JS-rendered. OhioMeansJobs portal also JS-rendered. | Probe network requests in a real browser; find the JSON/API endpoint behind the portal. |
| **PA** | `dli.pa.gov/Individuals/Workforce-Development/warn/notices/Pages/{Month}-{Year}.aspx` | Old DLI domain redirects to `pa.gov/agencies/dli`; monthly ASPX pages are gone. New WARN notices page exists at `pa.gov/agencies/dli/.../warn-notices.html` but has no data (JS-rendered or unpublished). | Check network requests on the new pa.gov WARN page; may have a hidden data API. |
| **OR** | `ccwd.hecc.oregon.gov/Layoff/WARN` | **Resolved** — county filter (`?County=Name&page=N`) restricts to OR only. Scraper iterates all 36 counties with pagination. Implemented in `warn_v2/scrapers/states/or_.py`. | — |
| **IA** | `iowawf.gov/147/WARN-Notices` | Domain changed; `workforce.iowa.gov/employers/resources/warn/notices` resolves but shows a JS-rendered data visualization (no static table). | Probe the network requests on the notices page to find the underlying data API. |

| **MA** | `mass.gov/lists/...warn-act-layoff-list` | CDN returns 403 "Not allowed" for all bot requests, including the weekly CSV download URLs (`/doc/warn-report-for-week-ending-{date}/download`). `eolwd.mass.gov` hostname no longer resolves. | Requires a browser with real TLS fingerprint (Playwright/Camoufox). Weekly CSV pattern known: `/doc/warn-report-for-week-ending-MM-DD-YYYY/download`. |
| **MN** | `mn.gov/deed/business/downsizing-restructuring/warn/` | ShieldSquare/PerimeterX bot challenge; redirects automated requests to `validate.perfdrive.com`. | Requires a headless browser with fingerprint spoofing. |
| **MO** | `jobs.mo.gov/warn` | Incapsula bot protection; returns JS challenge for all automated requests. | Requires a headless browser. |
| **AR** | *(no V1 scraper)* | WARN notices are treated as confidential in Arkansas; no public disclosure required or published. | No action — state law prohibits public release. |
| **NH** | *(no V1 scraper)* | New Hampshire does not require public posting of WARN notices; the state agency does not publish a list. | No action — no public data source. |
| **WY** | *(no V1 scraper)* | Wyoming has no state WARN law and does not publish federal WARN filings. | No action. |
| **WV** | *(no V1 scraper)* | Per-notice PDFs available individually on request; no machine-readable list published. | Would require fetching index + per-notice PDF parsing. Low value. |

These are good candidates for the heal agent in "greenfield" mode (Phase 4-ish)
— given a live sample and a contract, it can write a scraper from scratch.
For now they fail at `fetch()` and the runner logs `fetch_failed` cleanly.
