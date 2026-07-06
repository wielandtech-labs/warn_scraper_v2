# Value opportunities — the 60-day lead signal

WARN notices must be filed at least 60 days before the separation date, so the
dataset is *predictive*: we know who becomes available to the labor market,
where, from which industry, and roughly how many — before it happens. This doc
ranks concrete ways to turn that lead time into value, grounded in what the
repo already has and in verified external APIs. Companion to
[ROADMAP.md](ROADMAP.md) (data-quality work tracks); nothing here is scheduled
work until an item is promoted into a track.

Audiences considered: recruiters/employers, affected workers (public good),
B2B sales & risk teams, researchers/journalists.

## 1. Why the fields we already store are a forward signal

| Field | Signal | Where it lives |
|-------|--------|----------------|
| `effective_date` (~100%) | **When** the cohort hits the market | `warn_v2/db/models.py` Notice |
| NAICS sector/subsector (post-enrichment) | **What skills** the cohort likely has | Company enrichment cascade |
| county + lat/lon (~85–95%) | **Which local market** absorbs them | Location, geocoded |
| `layoff_count` (~30–50%) | **How many** | Notice |
| `closure_category` (Closure vs Layoff) | **Severity** — plant closure means the whole site's occupation mix, not a trim | Notice |
| D&B family tree (paid tier) | **Corporate context** — parent distress, multi-site events | `/api/companies/{id}/family` |

Existing rails every idea below can ship on: filterable email subscriptions
(`warn_v2/notifications/`), role-gated paid tier with D&B columns
(`docs/auth-operations.md`), CSV/JSON exports, RSS, map pins, per-state
reports.

## 2. Ranked opportunities

### A. Talent Availability Radar — recruiters (recommended first product)

"~120 mostly-manufacturing workers hit the Wichita market on September 1."
A forward calendar keyed on `effective_date` (today the UI is retrospective),
filterable by NAICS × metro × cohort size, delivered as a page + digest email +
export.

The differentiator is **occupation-mix inference without LinkedIn**: BLS's
[OEWS industry-specific estimates](https://www.bls.gov/oes/oes_emp.htm) give
the occupation distribution per NAICS industry (national, down to 4–6 digit
NAICS), and the [industry-occupation matrix](https://www.bls.gov/emp/tables/industry-occupation-matrix-industry.htm)
is downloadable outright; both free via the
[BLS Public Data API](https://www.bls.gov/data/). Apply the national staffing
pattern for the notice's NAICS to its `layoff_count` and you get "likely ~40
machinists, ~15 industrial engineers, ~10 logistics staff" per notice. Caveat
to state in the UI: it's a statistical prior from the industry pattern, not
data about the actual affected roles.

- Data needed: NAICS (enrichment coverage is the bottleneck — see §4),
  effective_date, county, layoff_count.
- Cost: $0 (BLS is free). Optional upgrade for high-value notices only:
  company-level headcount-by-function from
  [Coresignal](https://coresignal.com/pricing/) ($49+/mo, credit-based) or
  [People Data Labs](https://syncgtm.com/blog/people-data-labs-review)
  (free 100 lookups/mo, Pro $98/mo).
- Legal risk: none — public statistical data.
- Effort: medium (one enrichment table + one route + one page + digest tweak).
- Revenue: the natural paid-tier feature; competitors
  ([Intellizence](https://docs.intellizence.com/signals-api/layoffs),
  [WARNTracker](https://www.warntracker.com/)) charge for weaker versions.

**A2 add-on — LinkedIn ad-targeting-spec export.** The one officially
sanctioned LinkedIn integration that fits (see §3): per notice cohort, generate
a Campaign-Manager-ready spec — company name (list upload supports up to
[300k companies](https://www.linkedin.com/help/lms/answer/a423102)), geography,
job functions inferred from the OEWS mix — so a recruiter or outplacement firm
can run "employees of {filer} in {metro}" ads during the 60-day window
([targeting options](https://www.linkedin.com/help/lms/answer/a424655),
300-member minimum audience). Manual CSV/spec export first; LinkedIn
Advertising API (Marketing Developer Program application) only if demand
justifies one-click campaign creation.

### B. Vendor/portfolio watchlists — B2B sales & risk

Users upload a list of companies (customers, vendors, borrowers, portfolio);
we alert when a watched company **or anything in its D&B family tree** files
WARN. The family-tree join is the moat — aggregators match on literal employer
names; we can catch "subsidiary of your borrower filed in another state" via
`canonical_company_id` + parent rollups that already exist.

Free adjacent signals to bundle into the same alert: SEC 8-K filings via
[EDGAR full-text search](https://tldrfiling.com/blog/sec-edgar-full-text-search-api)
(free, no key, 10 req/s, User-Agent header required, 2001–present) — an 8-K
within days of a WARN notice is a strong distress confirmation; bankruptcy
dockets via CourtListener/RECAP (free API).

- Data needed: nothing new — company matching + family trees exist.
- Cost: $0.
- Legal risk: none — all public filings.
- Effort: medium (watchlist table + matching job + digest integration; webhook
  delivery later).
- Revenue: the clearest *recurring* B2B product (per-seat or per-list pricing);
  this is what Intellizence sells as "risk intelligence."

### C. Worker resource pages — affected workers (public good + SEO)

Per-notice "what now" panel: the state's rapid-response / WIOA
dislocated-worker program page, the state UI filing link, and nearby current
openings matched on county + occupation via the
[CareerOneStop Web API](https://www.careeronestop.org/Developers/WebAPI/web-api.aspx)
(free with [registration](https://www.careeronestop.org/Developers/WebAPI/registration.aspx);
display-license terms: data shown as-is, for the registered purpose). The OEWS
occupation mix from idea A doubles here: "people in your role are also hired
by …".

- Cost: $0. Effort: low-medium (static per-state resource table + one API
  client + a panel on `notice-detail.tsx`).
- Revenue: none directly — this is the public-good and SEO/backlink engine
  (state agencies and journalists link to pages like this), which feeds
  everything else.

### D. Local labor-market impact index — researchers/journalists

Normalize layoffs by the county employment base:
`layoff_count ÷ county employment` (Census
[County Business Patterns](https://www.census.gov/programs-surveys/cbp.html),
free API, county × NAICS employment counts) → "this closure is 4% of the
county's manufacturing employment," an industry-adjusted trend index, and
embeddable/citable charts + downloads.

- Cost: $0. Effort: low (one join + one stats endpoint + charts on existing
  stats page).
- Revenue: indirect — citations and backlinks build the authority that makes
  A and B sellable. Journalists are the distribution channel, not the buyer.

## 3. The LinkedIn question, answered directly

**Data OUT of LinkedIn is a dead end.** The official
[product catalog](https://developer.linkedin.com/product-catalog) contains no
people-search or company-data API — every product is a push-in integration
(Sign In, Share, Job Posting, Apply Connect / Recruiter System Connect for ATS
vendors, ads). The only data-out products (Member/Pages Data Portability) are
EU-DMA member-authorized exports. The scraping route is legally closed:
LinkedIn's lawsuit shut down Proxycurl in 2025 with a
[permanent injunction](https://linkedapi.io/guides/proxycurl-alternatives).
Compliant enrichment means licensed aggregators (Coresignal, People Data Labs,
Bright Data) at **company** level — never individual profiles — and §2A shows
free government data covers most of the v1 need anyway.

**Data INTO LinkedIn is the sanctioned play.** LinkedIn Ads officially supports
targeting current employees of named companies refined by geography and job
function/seniority. That's idea A2: we don't extract who's affected — we let
recruiters, outplacement firms, and workforce agencies *reach* them during the
window, using our data to build the targeting spec. The same mechanism lets a
state agency advertise retraining programs to an affected cohort (ties into C).

## 4. Shared prerequisite: NAICS enrichment coverage

Ideas A, C, D all key on NAICS, currently ~16% coverage at ~100 companies/day
(ROADMAP Track 5). Raising throughput is the single highest-leverage
investment:

- **Batch-mode Haiku**: the Claude enrichment path
  (`warn_v2/enrichment/agent.py`) at 50% batch-API discount; rough math —
  ~3 tool-call turns ≈ $0.005–0.01/company, so the ~5k-company backlog is
  tens of dollars, not a budget item. The cap is policy, not cost.
- **Aggregator bulk match**: Coresignal/PDL company enrichment would also fill
  employee_count and industry in one pass (PDL free tier: 1,000 company
  lookups/mo — enough to clear the backlog in ~5 months for $0, or one Pro
  month ≈ $98).
- Notices without NAICS should still appear in A/C/D outputs, flagged
  "industry unknown," so coverage gaps degrade gracefully instead of hiding
  records.

## 5. Recommended sequence

1. **D — impact index** (free, low effort): instant differentiation, SEO/
   citation engine.
2. **A — Talent Radar MVP** on free BLS data (+A2 spec export): the core
   60-day product; validates recruiter demand before any paid API spend.
3. **B — watchlists**: first true recurring-revenue product, built on the
   family-tree moat.
4. **C — worker pages**: ongoing public-good layer; ships piecemeal alongside
   the others.

Paid-API spend (Coresignal/PDL beyond free tiers) is deferred until A shows
demand; the enrichment-throughput raise (§4) should happen regardless.
