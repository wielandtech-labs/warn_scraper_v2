<p align="center">
  <a href="https://warnindex.com"><img src="frontend/public/icon-192.png" width="72" height="72" alt="WARN Index logo"></a>
</p>

<h1 align="center">WARN Index</h1>

<p align="center">
  <b>The free US layoff tracker.</b> Every WARN Act notice from 47 states and DC,<br>
  collected daily, cleaned, mapped and open: <a href="https://warnindex.com"><b>warnindex.com</b></a>
</p>

<p align="center">
  <a href="https://github.com/wielandtech-labs/warn_scraper_v2/actions/workflows/ci.yml"><img src="https://github.com/wielandtech-labs/warn_scraper_v2/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/code-AGPL--3.0-blue" alt="Code license: AGPL-3.0"></a>
  <a href="https://creativecommons.org/licenses/by/4.0/"><img src="https://img.shields.io/badge/data-CC%20BY%204.0-lightgrey" alt="Data license: CC BY 4.0"></a>
  <a href="https://doi.org/10.5281/zenodo.23902958"><img src="https://zenodo.org/badge/DOI/10.5281/zenodo.23902958.svg" alt="DOI"></a>
  <br>
  <a href="https://huggingface.co/datasets/warn-index/us-warn-layoffs"><img src="https://img.shields.io/badge/Hugging%20Face-dataset-FFD21E?logo=huggingface&logoColor=black" alt="Hugging Face dataset"></a>
  <a href="https://www.kaggle.com/datasets/warnindex/us-warn-act-layoff-notices-1989-2026"><img src="https://img.shields.io/badge/Kaggle-dataset-20BEFF?logo=kaggle&logoColor=white" alt="Kaggle dataset"></a>
  <a href="https://bsky.app/profile/warnindex.com"><img src="https://img.shields.io/badge/Bluesky-%40warnindex.com-1185FE?logo=bluesky&logoColor=white" alt="Bluesky: @warnindex.com"></a>
</p>

<p align="center">
  <a href="https://warnindex.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/img/hero-dark.png">
      <img src="docs/img/hero-light.png" alt="The WARN Index dashboard: workers affected, notices and a map of layoffs by state" width="900">
    </picture>
  </a>
</p>

Employers planning a plant closing or mass layoff usually have to notify the
state about 60 days ahead under the federal **WARN Act** and state "mini-WARN"
laws. Those notices are public, but every state publishes them differently:
HTML tables, PDFs, spreadsheets, search forms. WARN Index checks each state's
postings on a schedule, most of them daily, then de-duplicates, geocodes and
classifies the filings into one national database.

## Live right now

These badges are served by warnindex.com and show the workers affected by
notices filed in the last 30 days (GitHub caches images, so they can lag a few
hours):

<p>
  <a href="https://warnindex.com/states/CA"><img src="https://warnindex.com/embed/badge/state/CA.svg" alt="California layoffs, last 30 days"></a>
  <a href="https://warnindex.com/states/TX"><img src="https://warnindex.com/embed/badge/state/TX.svg" alt="Texas layoffs, last 30 days"></a>
  <a href="https://warnindex.com/states/MI"><img src="https://warnindex.com/embed/badge/state/MI.svg" alt="Michigan layoffs, last 30 days"></a>
  <a href="https://warnindex.com/states/IL"><img src="https://warnindex.com/embed/badge/state/IL.svg" alt="Illinois layoffs, last 30 days"></a>
  <a href="https://warnindex.com/states/WA"><img src="https://warnindex.com/embed/badge/state/WA.svg" alt="Washington layoffs, last 30 days"></a>
  <a href="https://warnindex.com/states/FL"><img src="https://warnindex.com/embed/badge/state/FL.svg" alt="Florida layoffs, last 30 days"></a>
</p>

## What you can do with it

- **Search** notices by company, state, city or industry, and see a company's
  full filing history in one place.
- **Watch the trend**: layoffs over time on a map and on charts, set against
  official BLS labor data, plus reports for each state and industry.
- **Get alerts** by email when a new notice matches your filters, or follow
  large ones on [Bluesky](https://bsky.app/profile/warnindex.com).
- **Use the data**: a REST API, CSV/JSON exports and a full weekly snapshot.

<p align="center">
  <a href="https://warnindex.com/stats">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/img/trends-dark.png">
      <img src="docs/img/trends-light.png" alt="Layoff trends: workers affected by month, with summary figures" width="900">
    </picture>
  </a>
</p>

## Get the data

You don't need to run the scraper to use the data:

- **Live tracker, alerts and API:** [warnindex.com](https://warnindex.com) ([API docs](https://warnindex.com/api-docs))
- **Full weekly snapshot:** [Hugging Face](https://huggingface.co/datasets/warn-index/us-warn-layoffs) · [Kaggle](https://www.kaggle.com/datasets/warnindex/us-warn-act-layoff-notices-1989-2026)
- **Citable archive (DOI):** [10.5281/zenodo.23902958](https://doi.org/10.5281/zenodo.23902958)
- **New large notices on Bluesky:** [@warnindex.com](https://bsky.app/profile/warnindex.com)

The data is CC BY 4.0 (see [License](#license)).

## Embed it on your site

The state badges above work anywhere an image does: blogs, READMEs,
newsletters.

```html
<a href="https://warnindex.com/states/CA"><img src="https://warnindex.com/embed/badge/state/CA.svg" alt="California WARN layoffs, last 30 days (WARN Index)" height="20"></a>
```

Any single notice is also available as a self-contained card that stays up to
date. On a notice's page at warnindex.com, click **Embed** to copy its
snippet. It looks like this:

```html
<iframe src="https://warnindex.com/embed/notices/NOTICE_ID" title="Employer WARN notice" width="100%" height="260" style="max-width:480px;border:0;color-scheme:normal" loading="lazy"></iframe>
<p style="font-size:12px">Source: <a href="https://warnindex.com/notices/NOTICE_ID">WARN Index</a></p>
```

Please keep the link back to warnindex.com: it's the attribution the CC BY
license asks for.

## How it works

```mermaid
flowchart LR
    S[47 state sites + DC] -->|scheduled scrape| R[Scraper runner]
    R -->|parse OK| DB[(Postgres)]
    R -->|parse fails| SN[Snapshot saved]
    SN --> H["/heal-scraper<br/>(Claude Code)"]
    H -->|fix + PR for review| R
    DB --> E[Company enrichment<br/>+ geocoding]
    E --> DB
    DB --> API[FastAPI + React site<br/>warnindex.com]
    DB --> M[Weekly dataset mirror<br/>Hugging Face · Kaggle]
    DB --> B[Bluesky alerts]
```

Each state is one small module with a `fetch()` and a `parse()`. When a state
redesigns its site and `parse()` breaks, the runner saves the raw page as a
snapshot, and the [`/heal-scraper`](docs/repairing-scrapers.md) Claude Code op
reproduces the break, fixes the parser against the live page and the golden
fixture, and opens a PR for a human to review.

**Coverage:** 48 jurisdictions (47 states + DC). Arkansas, New Hampshire and
Wyoming publish no usable notice list; see
[`docs/deferred-states.md`](docs/deferred-states.md).

## Quick start

You need Python 3.12+, [uv](https://docs.astral.sh/uv/) and a Postgres
database. Node 20 is only needed to work on the frontend.

```bash
uv sync --extra dev
export DATABASE_URL=postgresql+psycopg://warn:warn@localhost:5432/warn_v2
uv run alembic upgrade head        # create the schema

uv run warn-v2 scrape --state CA   # scrape one state
uv run warn-v2 serve               # API + site on http://localhost:8000
```

Run the tests with `uv run python -m pytest`. The tests use SQLite, so they
don't need Postgres. For a quick loop, skip the slow ML tests:
`-m "not slow" -n 4`.

Frontend development:

```bash
cd frontend && npm install && npm run dev   # Vite on :5173, proxies the API on :8000
```

The app reads its settings from environment variables (see
[`.env.example`](.env.example)); nothing loads a `.env` file for you. Company
enrichment also needs an `ANTHROPIC_API_KEY`:

```bash
uv run warn-v2 enrich --state CA --dry-run
```

## Repo layout

| Path | Purpose |
|------|---------|
| `warn_v2/scrapers/states/{state}.py` | One module per state |
| `warn_v2/scrapers/fixtures/{state}/` | Golden samples + expected counts |
| `warn_v2/pipeline/` | Runner, validation, de-duplication, storage |
| `warn_v2/enrichment/` | Company enrichment |
| `warn_v2/api/` | FastAPI app, embeds and share cards |
| `warn_v2/reports/`, `warn_v2/outlook/` | Weekly reports and statistical outlook |
| `warn_v2/social/` | Bluesky alerts |
| `warn_v2/db/` | SQLAlchemy models + Alembic migrations |
| `frontend/` | React site |
| `charts/warn-v2/` | Helm chart (K3s, deployed with Flux) |
| `.claude/` | Claude Code ops: `/heal-scraper`, `/layoff-sentiment`, … |

## More docs

- [Repairing a broken scraper](docs/repairing-scrapers.md)
- [Analytics: BLS indicators, sentiment reports, outlook](docs/analytics.md)
- [Operations: production deployment and local-testing notes](docs/operations.md)
- [Roadmap](docs/ROADMAP.md) · [Deferred states](docs/deferred-states.md) ·
  [Historical sources](docs/historical-sources.md)

## Background

This is the second version of a 2022 project. V1 had about 33 hand-written
scrapers that broke every time a state site changed. V2 keeps the original
goal (surface affected workers about 60 days before a layoff) but splits fetch
from parse, so a broken parser can be replayed and repaired quickly.

## License

- **Code:** [GNU AGPL-3.0-or-later](LICENSE), Copyright (C) 2026 Raphael
  Wieland. If you run a modified version as a network service, you must
  offer its users your source code (AGPL section 13).
- **Data:** WARN Index notice data is licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribute it with
  a link to [warnindex.com](https://warnindex.com); see the
  [citation guide](https://warnindex.com/cited-by).
