# Deferred state scrapers

States from the V1 active set whose live sources have drifted in ways that
need investigation (URL moved, new bot protection, page rebuilt with
JS-rendered content). Listed here so the Phase-4-style enrichment / heal
agent has a queue to work through later.

Last checked: 2026-05-21.

| State | V1 URL | What changed | Next step |
|-------|--------|--------------|-----------|
| **CT** | `ctdol.state.ct.us/progsupt/bussrvce/warnreports/warn{year}.htm` | URL 404s; site migrated to `portal.ct.gov`. WARN notices now live in a JS-rendered document library at `dolpublicdocumentlibrary.ct.gov/CsblrCategory?prefix=%2Frapid_response%2Fwarn_documents`. | Inspect the document library's network calls; likely a JSON listing of per-notice PDFs. May require Playwright for the initial listing fetch. |
| **GA** | `https://www.dol.state.ga.us/public/es/warn/searchwarns` | 404 (WebSphere `SRVE0295E`) on GET and POST. The whole `dol.state.ga.us` path appears to have been retired. | Search current Georgia DOL site for the new WARN URL. |
| **IL** | `apps.illinoisworknet.com/iebs/api/public/export?...` (XLSX export) | The data endpoint 404s. The user-facing page at `illinoisworknet.com/warnlayoffsearch` still serves HTML (SharePoint), but the data loads via a different (probably JS) backend. | Inspect the live page's network calls to discover the new data endpoint. |
| **MI** | `https://milmi.org/warn` | URL itself returns 200 from `michigan.gov/leo/...` but the new template renders an empty `facet-warn---counties` component; the data loads via JS / a deeper API. | Probe the page in a real browser, capture the XHR; update scraper to hit the JSON endpoint directly. |
| **NJ JSP** | `lwd.state.nj.us/WorkForceDirectory/warn.jsp?...` | Behind Incapsula (403 + JS challenge). V2 falls back to the still-live yearly PDF at `nj.gov/labor/assets/PDFs/WARN/{year}_WARN_Notice_Archive.pdf` (see `warn_v2/scrapers/states/nj.py`). | If the PDF ever stops being published, scraping the JSP page would need a real browser (Playwright) — not worth it. |
| **OK JobLink** | `okjobmatch.com/search/warn_lookups?...` | Whole `okjobmatch.com` host returns 404 (IIS). Other JobLink-platform states (AZ/DE/KS/ME/VT) still work. | Check whether Oklahoma migrated to a different `*jobmatch.com` subdomain. |

These are good candidates for the heal agent in "greenfield" mode (Phase 4-ish)
— given a live sample and a contract, it can write a scraper from scratch.
For now they fail at `fetch()` and the runner logs `fetch_failed` cleanly.
